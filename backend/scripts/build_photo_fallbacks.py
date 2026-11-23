"""Build backend/app/data/photo_fallbacks.json from hand-picked Wikimedia Commons files.

About 12% of huetripo POIs have no photo. This script resolves the curated Commons files below into
thumbnail URLs with author and license, so the API can serve a real photo for every place:

- `PLACE_FILES`: a photo of that exact place (checked by hand).
- `CATEGORY_FILES`: generic photos per category, optionally narrowed by a keyword in the place name.
  The UI labels these "Ảnh minh hoạ" because they do not show the place itself.

Run once with network access: python backend/scripts/build_photo_fallbacks.py
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "HueTravelAgent/0.1 (https://www.mediawiki.org/wiki/API:Etiquette) httpx"
THUMB_WIDTH = 1280
OUTPUT = Path(__file__).resolve().parents[1] / "app" / "data" / "photo_fallbacks.json"
FREE_LICENSES = re.compile(r"^(CC0|CC BY(-SA)? \d\.\d|Public domain)$", re.IGNORECASE)

PLACE_FILES: dict[str, str] = {
    "huetripo:544139": "File:Điện Voi Ré.jpg",
    "huetripo:019472": "File:Trấn Bình đài.JPG",
    # Caption on Commons names the garden: "in his garden Lạc Tịnh Viên".
}

# Rules are tried in order; the first whose keywords match the lower-cased place name wins.
# An empty keyword tuple is the category default.
CATEGORY_FILES: dict[str, list[tuple[tuple[str, ...], list[str]]]] = {
    "restaurant": [
        (("bánh canh",), ["File:Bánh canh cua.jpg", "File:Bánh canh tại Ngã Bảy.JPG", "File:Bánh canh cá lóc Sài Gòn 2012-07-02 11.53.24.jpg", "File:Bánh canh giò heo.jpg"]),
        (("hến",), ["File:Hến trộn.jpg", "File:Lễ hội ẩm thực Cửa Việt th4n2023 (gian hàng cơm hến Thôn Vĩ).jpg", "File:Lễ hội ẩm thực Cửa Việt th4n2023 đặc sản cơm hến Vĩ Dạ (3).jpg"]),
        (("bún đậu", "mắm tôm"), ["File:Bún đậu mắm tôm.jpg", "File:Bún đậu mắm tôm (2019).jpg", "File:Bún đậu mắm tôm (1).jpg", "File:Bún đậu mắm tôm, bún nem rán.JPG"]),
        (("thịt nướng",), ["File:Bun thit nuong.jpg", "File:Vietnamese bowl of grilled pork, bun thit nuong.jpg", "File:Bún thịt nướng cảng Cát Lái, ng10th5n2022 (thịt nướng than khói) (1).jpg"]),
        (("lẩu",), ["File:Lẩu bò tại quán Bò cười (3).jpg", "File:Món lẩu ăn với thịt bò ở Hà Nội tháng 7 năm 2018 (3).jpg", "File:Món lẩu ăn với thịt bò ở Hà Nội tháng 7 năm 2018 (5).jpg"]),
        (("lòng",), ["File:Cháo lòng.jpg", "File:Cháo lòng Bình Long ngày 02 tháng 11 năm 2018 (1).jpg", "File:Chao long.jpg"]),
        (("cháo",), ["File:Cháo gà nhà làm, tháng 5 năm 2020 (1).jpg", "File:Cháo gà nhà làm, tháng 5 năm 2020 (2).jpg", "File:Cháo gà xé phay ở P3 Đông Hà năm 2018.jpg"]),
        (("cơm tấm",), ["File:Cơm tấm Sài Gòn (sườn trứng), ng15th8n2022.jpg", "File:Com-Tam-2008.jpg", "File:Cơm tấm bì chả.jpg"]),
        (("ếch",), ["File:Cháo ếch Sing-ga-po Tân Phú tháng 1 năm 2018 (1).jpg", "File:Cháo ếch Sing-ga-po Tân Phú tháng 1 năm 2018 (4).jpg"]),
        (("gà",), ["File:Cơm gà chiên ở Đông Hà năm 2017 (1).jpg", "File:Gà nướng ngũ vị ở nhà làm, tháng 5 năm 2021 (1).jpg", "File:Cơm gà kiểu Việt Nam (cơm chiên gà rán) eHy tháng 6 năm 2018.jpg"]),
        (("quay",), ["File:Phở vịt quay.jpg"]),
        (("hải sản", "hàu"), ["File:Lễ hội ẩm thực Cửa Việt th4n2023 đặc sản hàu nướng và tôm nướng (1).jpg", "File:Lễ hội ẩm thực Cửa Việt th4n2023 đặc sản hàu nướng và tôm nướng (2).jpg"]),
        (("chay",), ["File:Gỏi Cuốn Chay Vietnamese Fresh Vegetarian Spring Roll 2019-1599.jpg", "File:Món chay cúng Ông năm 2017 (2).jpg", "File:Vegan Vietnamese at H&D Chay, Berlin.jpg"]),
        (("cơm",), ["File:Cơm chiên Dương Châu ở Đông Hà năm 2017.jpg", "File:Cơm trứng chiên tại sân bay Phú Bài (tháng 9 năm 2018) (1).jpg", "File:Cơm chiên cá mặn ở cf Quốc Hùng ngày 01.10 năm 2018 (2).jpg"]),
        (("pizza",), ["File:Pizza Việt Nam tại Lottemart 2016.jpg", "File:Pizza Việt Nam (SNaT 2018) (10).jpg", "File:Pizza Việt Nam (SNaT 2018) (8).jpg"]),
        (("bánh xèo",), ["File:Bánh xèo 1.jpg", "File:Bánh xèo 2.jpg", "File:Bánh xèo (20-8-2020).jpg"]),
        (("bánh cuốn",), ["File:Bánh cuốn nhân thịt.JPG", "File:Banh Cuon 2.jpg", "File:Bánh cuốn chả lụa.jpg"]),
        (("bánh bao",), ["File:Bánh bao 2.jpg", "File:Bánh bao 3.jpg", "File:Bánh bao.jpg"]),
        (("chè",), ["File:Lễ hội ẩm thực Cửa Việt th4n2023 đặc sản món chè Huế (chè hạt sen) (1).jpg", "File:Lễ hội ẩm thực Cửa Việt th4n2023 đặc sản món chè Huế (chè đậu xanh đánh).jpg", "File:Lễ hội ẩm thực Cửa Việt th4n2023 đặc sản món chè Huế (chè hạt sen) (2).jpg"]),
        (("khoai lang",), ["File:Roasted Sweet Potato.jpg", "File:Roasted sweet potato.jpg"]),
        (("trà",), ["File:Milk Tea 1.jpg", "File:Fresh Milk Tea 1.jpg", "File:Fresh Milk Tea 2.jpg"]),
        (("cafe", "coffee"), ["File:Ca Phe Sua Da.jpg", "File:Vietnamese Hot Drip Coffee - The Big Bowl.jpg", "File:CÀ PHÊ SỮA PHA PHIN.jpg"]),
        (("bánh",), ["File:Một vài loại bánh Việt Nam.jpg", "File:Banhchay.JPG"]),
        (
            (),
            [
                "File:Bun-Bo-Hue-from-Huong-Giang-2011.jpg",
                "File:Bún bò Huế minh28397.jpg",
                "File:Bún bò Huế-Feb 2025.jpg",
                "File:Bun Bo Hue 1.jpg",
                "File:Bún bò Huế (20201109).jpg",
                "File:Bún bò giò Đông Ba ng17th10n2020 (1).jpg",
            ],
        ),
    ],
    "cafe": [
        (("trà",), ["File:Milk Tea 1.jpg", "File:Fresh Milk Tea 1.jpg", "File:Fresh Milk Tea 2.jpg"]),
        (
            (),
            [
                "File:Ca Phe Sua Da.jpg",
                "File:Vietnamese Hot Drip Coffee - The Big Bowl.jpg",
                "File:CÀ PHÊ SỮA PHA PHIN.jpg",
                "File:Cà Phê Sữa Đá - Đặc trưng của Việt Nam.jpg",
                "File:Một ly cà phê nguyên chất ở Việt Nam.jpg",
                "File:Cà phê tách đen năm 2018.jpg",
            ],
        ),
    ],
    "market": [
        (("kẹo",), ["File:Peanut-&-White-Sesame-Candy.jpg"]),
        (
            (),
            [
                "File:Dong Ba Market (Hue) - Chợ Đông Ba Huế (July 2024) - img 01.jpg",
                "File:Dong Ba Market (Hue) - Chợ Đông Ba Huế (July 2024) - img 02.jpg",
                "File:Dong Ba Market (Hue) - Chợ Đông Ba Huế (July 2024) - img 03.jpg",
                "File:Dong Ba Market (Hue) - Chợ Đông Ba Huế (July 2024) - img 04.jpg",
                "File:Dong Ba Market (Hue) - Chợ Đông Ba Huế (July 2024) - img 05.jpg",
                "File:Dong Ba Market (Hue) - Chợ Đông Ba Huế (July 2024) - img 06.jpg",
            ],
        ),
    ],
    "historic": [
        (
            ("đình",),
            [
                "File:Đình làng Kim Long.jpg",
                "File:Đình Làng Quang Điểm.jpg",
                "File:Đình làng An Nông.jpg",
                "File:Đình làng Vũ Đại.JPG",
                "File:Kiến trúc đình làng ở Cát Sơn, Tết năm 2017 (5).jpg",
            ],
        ),
        (
            ("địa đạo",),
            [
                "File:W Củ Chi Địa đạo Củ Chi x.JPG",
                "File:W Củ Chi Địa đạo Củ Chi 5.JPG",
                "File:Rừng cây trong địa đạo Củ Chi.jpg",
            ],
        ),
        (
            ("lăng", "tẩm", "mộ"),
            [
                "File:Mausoleum of Emperor Dong Khanh (Hue) - Lăng Đồng Khánh (2024 July) - img 05.jpg",
                "File:Hue Vietnam Tomb-of-Emperor-Minh-Mang-01.jpg",
                "File:Hue Vietnam Tomb-of-Emperor-Minh-Mang-11.jpg",
                "File:Hue Vietnam Tomb-of-Emperor-Minh-Mang-16.jpg",
                "File:Lăng Khải Định.JPG",
                "File:Lăng vua Thiệu Trị.JPG",
                "File:Lăng vua Gia Long 6.JPG",
                "File:Xung Khiêm Tạ (Lăng Tự Đức).JPG",
            ],
        ),
        (
            (),
            [
                "File:Vietnam, Hue, Imperial City of Hue, Meridian Gate.jpg",
                "File:Meridian Gate, Hue (I).jpg",
                "File:Vietnam, Hue, Imperial City of Hue, Meridian Gate 2.jpg",
                "File:Vietnam, Hue, Imperial City of Hue, Gate.jpg",
                "File:Diên Thọ palace Hue Imperial City.jpg",
                "File:Diên Thọ palace Hue Imperial City (85648).jpg",
            ],
        ),
    ],
    "religious": [
        (("chùa",), ["File:Hue Vietnam Thien-Mu-Temple-and-Pagoda-03.jpg"]),
        (
            (),
            ["File:A set of incense burners- you can imagine the scale and grandeur in the citadel's heydays (30961094834).jpg"],
        ),
    ],
}


# Commons "Artist" fields that are sentences rather than names.
AUTHOR_OVERRIDES: dict[str, str] = {
    "File:Gate in Imperial City, Huế (III).jpg": "Supanut Arunoprayote",
}


def strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def clean_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def resolve(client: httpx.Client, titles: list[str]) -> dict[str, dict[str, str]]:
    resolved: dict[str, dict[str, str]] = {}
    for start in range(0, len(titles), 20):
        batch = titles[start : start + 20]
        response = client.get(
            API,
            params={
                "action": "query",
                "format": "json",
                "titles": "|".join(batch),
                "prop": "imageinfo",
                "iiprop": "url|extmetadata",
                "iiurlwidth": THUMB_WIDTH,
                "iiextmetadatafilter": "LicenseShortName|Artist",
            },
        )
        response.raise_for_status()
        data = response.json()["query"]
        normalized = {item["to"]: item["from"] for item in data.get("normalized", [])}
        for page in data["pages"].values():
            title = normalized.get(page["title"], page["title"])
            if "imageinfo" not in page:
                raise SystemExit(f"missing on Commons: {title}")
            info = page["imageinfo"][0]
            meta = info.get("extmetadata", {})
            license_name = meta.get("LicenseShortName", {}).get("value", "")
            if not FREE_LICENSES.match(license_name):
                raise SystemExit(f"license not allowed for {title}: {license_name!r}")
            resolved[title] = {
                "url": clean_url(info.get("thumburl") or info["url"]),
                "page_url": info["descriptionurl"],
                "author": AUTHOR_OVERRIDES.get(title)
                or strip_tags(meta.get("Artist", {}).get("value", ""))
                or "Wikimedia Commons",
                "license": license_name,
            }
        time.sleep(1)
    return resolved


def main() -> None:
    titles = sorted(
        set(PLACE_FILES.values())
        | {title for rules in CATEGORY_FILES.values() for _, files in rules for title in files}
    )
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
        photos = resolve(client, titles)
    output = {
        "places": {poi_id: photos[title] for poi_id, title in PLACE_FILES.items()},
        "categories": {
            category: [{"keywords": list(keywords), "photos": [photos[t] for t in files]} for keywords, files in rules]
            for category, rules in CATEGORY_FILES.items()
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT} with {len(photos)} photos")


if __name__ == "__main__":
    main()
