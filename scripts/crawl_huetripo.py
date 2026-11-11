"""Crawl all public data and images from https://huetripo.hue.gov.vn.

Uses the site's anonymous JSON API (/api/Public/...). Output layout:

    <out>/lists/<name>.json         full list per endpoint (all pages merged)
    <out>/categories/loai_<id>.json DanhMucChung categories
    <out>/details/<kind>/<id>.json  GetById detail per record
    <out>/images/<site path>        downloaded images (mirrors /uploads/... path)
    <out>/images/_external/<host>/  images hosted elsewhere
    <out>/manifest.json             summary + url -> local file map

Resumable: existing detail/image files are skipped. Stdlib only.

    python scripts/crawl_huetripo.py --out data/raw/huetripo
"""

from __future__ import annotations

import argparse
import http.client
import json
import re
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = "https://huetripo.hue.gov.vn"
UA = "Mozilla/5.0 (TravelAgent research crawler)"

# name -> (endpoint, id field, detail kind)
LISTS = {
    "luu_tru": ("/api/Public/DiaDiem/ListLuuTru", "diaDiemID", "dia_diem"),
    "am_thuc": ("/api/Public/DiaDiem/ListAmThuc", "diaDiemID", "dia_diem"),
    "dich_vu_khac": ("/api/Public/DiaDiem/ListDichVuKhac", "diaDiemID", "dia_diem"),
    "diem_tham_quan": ("/api/Public/DiaDiem/ListDiemThamQuan", "diaDiemID", "dia_diem"),
    "lu_hanh": ("/api/Public/DiaDiem/ListLuHanh", "diaDiemID", "dia_diem"),
    "cong_ty_van_chuyen": ("/api/Public/DiaDiem/ListCongTyVanChuyen", "diaDiemID", "dia_diem"),
    "dich_vu_thue": ("/api/Public/DiaDiemDichVu/ListDichVuThue", None, None),
    "san_pham": ("/api/Public/SanPham/GetList", None, None),
    "tour": ("/api/Public/Tour/List", "tourID", "tour"),
    "su_kien": ("/api/Public/SuKien/ListSuKien", "suKienID", "su_kien"),
    "le_hoi": ("/api/Public/SuKien/ListLeHoi", "suKienID", "su_kien"),
}

DETAIL = {
    "dia_diem": "/api/Public/DiaDiem/GetById?id={id}&language={lang}",
    "tour": "/api/Public/Tour/GetById?id={id}&maNgonNgu={lang}",
    "su_kien": "/api/Public/SuKien/GetById?id={id}&language={lang}",
}

IMG_EXT = r"(?:jpe?g|png|gif|webp|svg|bmp|avif)"
# Site-relative uploads/assets paths, or absolute URLs ending in an image extension.
RE_SITE = re.compile(r"(?<![\w.])/(?:uploads|assets)/[^\s\"'<>()\\]+?\." + IMG_EXT + r"\b", re.I)
RE_ABS = re.compile(r"https?://[^\s\"'<>()\\]+?\." + IMG_EXT + r"\b", re.I)

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


class HTTPStatusError(Exception):
    def __init__(self, url: str, code: int):
        super().__init__(f"HTTP {code}: {url}")
        self.code = code


_local = threading.local()


def _keepalive_get(url: str, timeout: int) -> bytes:
    """GET over a per-thread persistent connection.

    The site's IIS truncates the last bytes of a response when the client sends
    `Connection: close` (which urllib always does), so huetripo requests must use
    keep-alive. Redirects are followed manually.
    """
    for _ in range(5):
        u = urllib.parse.urlsplit(url)
        key = (u.scheme, u.netloc)
        conns = getattr(_local, "conns", None)
        if conns is None:
            conns = _local.conns = {}
        conn = conns.get(key)
        if conn is None:
            cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
            conn = conns[key] = cls(u.netloc, timeout=timeout)
        target = u.path + (f"?{u.query}" if u.query else "")
        try:
            conn.request("GET", target, headers={"User-Agent": UA, "Accept": "*/*"})
            r = conn.getresponse()
            body = r.read()
        except Exception:
            conn.close()
            conns.pop(key, None)
            raise
        if r.status in (301, 302, 303, 307, 308) and r.getheader("Location"):
            url = urllib.parse.urljoin(url, r.getheader("Location"))
            continue
        if r.status >= 400:
            raise HTTPStatusError(url, r.status)
        return body
    raise RuntimeError(f"too many redirects: {url}")


def http_get(url: str, retries: int = 3, timeout: int = 60) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            return _keepalive_get(url, timeout)
        except HTTPStatusError as e:
            if e.code in (400, 401, 403, 404, 410):
                raise
            last = e
        except Exception as e:  # network errors, timeouts, truncated bodies
            last = e
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET failed {url}: {last}")


def get_json(path: str) -> dict:
    return json.loads(http_get(BASE + path).decode("utf-8"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def fetch_list(endpoint: str, lang: str, page_size: int = 100) -> list[dict]:
    """Merge all pages. Some endpoints honour pageSize=-1, others cap at 20."""
    items: list[dict] = []
    seen: set[str] = set()
    page = 1
    while True:
        q = urllib.parse.urlencode(
            {"pageIndex": page, "pageSize": page_size, "language": lang, "maNgonNgu": lang}
        )
        res = get_json(f"{endpoint}?{q}")
        batch = res.get("value") or []
        if not isinstance(batch, list) or not batch:
            break
        new = 0
        for it in batch:
            key = json.dumps(it, sort_keys=True, ensure_ascii=False)
            if key not in seen:
                seen.add(key)
                items.append(it)
                new += 1
        total = res.get("totalRecords") or 0
        if new == 0 or (total and len(items) >= total):
            break
        page += 1
    return items


def fetch_categories(out: Path, lang: str) -> dict[int, int]:
    counts: dict[int, int] = {}
    for loai in range(1, 61):
        try:
            res = get_json(f"/api/Public/DanhMucChung/List?loaiId={loai}&maNgonNgu={lang}")
        except Exception:
            continue
        data = res.get("value", res.get("data", res)) if isinstance(res, dict) else res
        if isinstance(data, list) and data:
            write_json(out / "categories" / f"loai_{loai}.json", data)
            counts[loai] = len(data)
    return counts


def collect_image_urls(obj, acc: set[str]) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            collect_image_urls(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            collect_image_urls(v, acc)
    elif isinstance(obj, str) and obj:
        s = obj.replace("\\/", "/")
        for m in RE_ABS.findall(s):
            acc.add(m)
        for m in RE_SITE.findall(s):
            acc.add(BASE + m)


def local_image_path(images_dir: Path, url: str) -> Path:
    u = urllib.parse.urlsplit(url)
    path = urllib.parse.unquote(u.path).lstrip("/")
    safe = re.sub(r'[<>:"|?*]', "_", path)
    if u.netloc.lower() == urllib.parse.urlsplit(BASE).netloc:
        return images_dir / safe
    return images_dir / "_external" / u.netloc / safe


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", default="data/raw/huetripo")
    ap.add_argument("--lang", default="vi")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument(
        "--limit", type=int, default=0, help="max details per list (0 = all); for testing"
    )
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument(
        "--no-external", action="store_true", help="skip images hosted outside huetripo"
    )
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "source": BASE,
        "lang": args.lang,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    log("== categories")
    manifest["categories"] = fetch_categories(out, args.lang)
    log(f"   {manifest['categories']}")

    log("== lists")
    lists: dict[str, list[dict]] = {}
    for name, (endpoint, _, _) in LISTS.items():
        try:
            items = fetch_list(endpoint, args.lang)
        except Exception as e:
            log(f"   {name}: FAILED {e}")
            continue
        lists[name] = items
        write_json(out / "lists" / f"{name}.json", items)
        log(f"   {name}: {len(items)}")
    manifest["lists"] = {k: len(v) for k, v in lists.items()}

    # Unique (kind, id) detail jobs.
    jobs: dict[tuple[str, str], str] = {}
    for name, (_, id_field, kind) in LISTS.items():
        if not id_field or name not in lists:
            continue
        rows = lists[name][: args.limit] if args.limit else lists[name]
        for row in rows:
            rid = row.get(id_field)
            if rid:
                jobs[(kind, str(rid))] = name

    log(f"== details: {len(jobs)}")
    details_failed: list[str] = []

    def do_detail(kind: str, rid: str) -> tuple[str, str, dict | None]:
        path = out / "details" / kind / f"{rid}.json"
        if path.exists():
            return kind, rid, json.loads(path.read_text(encoding="utf-8"))
        try:
            res = get_json(DETAIL[kind].format(id=urllib.parse.quote(rid), lang=args.lang))
        except Exception as e:
            log(f"   detail fail {kind}/{rid}: {e}")
            return kind, rid, None
        write_json(path, res)
        return kind, rid, res

    image_urls: set[str] = set()
    for items in lists.values():
        collect_image_urls(items, image_urls)

    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(do_detail, k, i) for (k, i) in jobs]
        for f in as_completed(futs):
            kind, rid, res = f.result()
            if res is None:
                details_failed.append(f"{kind}/{rid}")
            else:
                collect_image_urls(res, image_urls)
            done += 1
            if done % 200 == 0:
                log(f"   {done}/{len(jobs)}")
    manifest["details"] = {"total": len(jobs), "failed": details_failed}

    if args.no_external:
        host = urllib.parse.urlsplit(BASE).netloc
        image_urls = {u for u in image_urls if urllib.parse.urlsplit(u).netloc == host}

    images_dir = out / "images"
    image_map: dict[str, str] = {}
    images_failed: list[str] = []
    if not args.no_images:
        log(f"== images: {len(image_urls)}")

        def do_image(url: str) -> tuple[str, Path | None]:
            dest = local_image_path(images_dir, url)
            if dest.exists() and dest.stat().st_size > 0:
                return url, dest
            try:
                fetch_url = urllib.parse.quote(url, safe=":/?&=%#+,;@!$'~")
                data = http_get(fetch_url, timeout=90)
            except Exception as e:
                log(f"   image fail {url}: {e}")
                return url, None
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return url, dest

        done = 0
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(do_image, u) for u in sorted(image_urls)]
            for f in as_completed(futs):
                url, dest = f.result()
                if dest is None:
                    images_failed.append(url)
                else:
                    image_map[url] = dest.relative_to(out).as_posix()
                done += 1
                if done % 500 == 0:
                    log(f"   {done}/{len(image_urls)}")
    manifest["images"] = {
        "found": len(image_urls),
        "saved": len(image_map),
        "failed": images_failed,
    }
    manifest["image_map"] = image_map
    manifest["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    write_json(out / "manifest.json", manifest)

    log(
        f"== done. details {len(jobs) - len(details_failed)}/{len(jobs)}, "
        f"images {len(image_map)}/{len(image_urls)} -> {out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
