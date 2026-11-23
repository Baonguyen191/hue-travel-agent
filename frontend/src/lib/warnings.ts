// Vietnamese text for the warnings and attempt reasons the backend sends in English.
// Each rule matches one known pattern (numbers and names are kept). Anything unmatched is returned unchanged,
// so a new backend message still shows up instead of disappearing.

type Rule = [RegExp, (match: RegExpMatchArray) => string];

const PROVIDER_VN: Record<string, string> = {
  "POI source": "Nguồn địa điểm",
  "Transport provider": "Nhà cung cấp xe",
  "Hotel provider": "Nhà cung cấp khách sạn",
};

const RULES: Rule[] = [
  // Itinerary: per visit
  [/^Opening hours require verification before the visit\.?$/, () => "Giờ mở cửa cần xác minh trước khi đi."],
  [
    /^A same-day source hour range was applied; days of operation remain unverified\.?$/,
    () => "Đã áp dụng giờ mở cửa trong ngày từ nguồn; ngày mở cửa chưa được xác minh.",
  ],
  [/^No safely parseable opening-hour range was available\.?$/, () => "Không có khung giờ mở cửa đọc được an toàn từ nguồn."],
  [/^Visit duration is a category-based assumption\.?$/, () => "Thời gian tham quan là giả định theo loại địa điểm."],
  [
    /^Source visit duration (\d+) min looks wrong; category default used\.?$/,
    (m) => `Thời gian tham quan trong nguồn (${m[1]} phút) có vẻ sai; dùng mặc định theo loại.`,
  ],
  [
    /^Visit duration clamped from (\d+) to (\d+) minutes\.?$/,
    (m) => `Thời gian tham quan được điều chỉnh từ ${m[1]} xuống ${m[2]} phút.`,
  ],
  [/^(.+) did not fit its source opening-hour range\.?$/, (m) => `${m[1]} không vừa khung giờ mở cửa trong nguồn.`],
  [/^No restaurant candidate for dinner; no dinner is scheduled\.?$/, () => "Không có quán ăn tối phù hợp; không xếp bữa tối."],
  [
    /^No restaurant candidate for lunch; an anonymous meal break is scheduled\.?$/,
    () => "Không có quán ăn trưa phù hợp; xếp giờ nghỉ trưa không gắn địa điểm.",
  ],

  // Itinerary: whole plan
  [
    /^(\d+) places farther than ([\d.]+) km from the centre were skipped\.?$/,
    (m) => `Bỏ qua ${m[1]} địa điểm cách trung tâm hơn ${m[2]} km.`,
  ],
  [
    /^(\d+) places sharing a location with an already chosen site were merged \(for example inside (.+)\)\.?$/,
    (m) => `Gộp ${m[1]} địa điểm cùng vị trí với một điểm đã chọn (ví dụ trong ${m[2]}).`,
  ],
  [/^Some selected POIs did not fit in the available itinerary time\.?$/, () => "Một số địa điểm đã chọn không vừa thời gian của lịch trình."],
  [
    /^The hotel is assumed at the city centre; travel times are straight-line estimates, not road routes or ETAs\.?$/,
    () => "Giả định khách sạn ở trung tâm; thời gian di chuyển là ước lượng đường chim bay, không phải đường đi hay ETA.",
  ],
  [
    /^Opening hours are source-provided or absent and require confirmation\.?$/,
    () => "Giờ mở cửa lấy từ nguồn hoặc chưa có; cần xác nhận.",
  ],
  [/^Straight-line Haversine distance only; road route and ETA are unverified\.?$/, () => "Chỉ có khoảng cách đường chim bay; đường đi và ETA chưa được xác minh."],

  // Itinerary validation
  [/^Event '(.+)' is outside itinerary date (.+)\.?$/, (m) => `Sự kiện “${m[1]}” nằm ngoài ngày lịch trình ${m[2]}.`],
  [/^Overlapping events found on (.+)\.?$/, (m) => `Có sự kiện trùng giờ vào ${m[1]}.`],
  [/^POI (.+) is scheduled more than once\.?$/, (m) => `Địa điểm ${m[1]} được xếp hơn một lần.`],
  [/^'(.+)' is a (.+) scheduled as a visit\.?$/, (m) => `“${m[1]}” là ${m[2]} nhưng được xếp như điểm tham quan.`],
  [
    /^Long estimated straight-line leg \(([\d.]+) km\) to '(.+)'\.?$/,
    (m) => `Quãng đường đường chim bay ước lượng dài (${m[1]} km) đến “${m[2]}”.`,
  ],
  [/^Day (.+) has visits but no lunch\.?$/, (m) => `Ngày ${m[1]} có điểm tham quan nhưng không có bữa trưa.`],

  // Search
  [/^No Hue POIs matched the requested filters\.?$/, () => "Không có địa điểm Huế nào khớp bộ lọc."],
  [/^No transport quote is available; no price was inferred\.?$/, () => "Không có báo giá xe; không suy đoán giá."],
  [/^No hotel quote is available; no price was inferred\.?$/, () => "Không có báo giá khách sạn; không suy đoán giá."],
  [
    /^No (BUS|TRAIN|FLIGHT) offer is available; showing all transport modes\.?$/,
    () => "Không có xe theo phương tiện bạn chọn; đang hiện mọi phương tiện.",
  ],
  [
    /^No (HOMESTAY|THREE_STAR|FOUR_STAR) offer is available; showing all hotel tiers\.?$/,
    () => "Không có chỗ ở theo loại bạn chọn; đang hiện mọi loại.",
  ],
  [
    /^(POI source|Transport provider|Hotel provider) timed out; its offers were omitted\.?$/,
    (m) => `${PROVIDER_VN[m[1]]} quá thời gian chờ; bỏ qua các báo giá của nguồn này.`,
  ],
  [
    /^(POI source|Transport provider|Hotel provider) failed; its offers were omitted\.?$/,
    (m) => `${PROVIDER_VN[m[1]]} gặp lỗi; bỏ qua các báo giá của nguồn này.`,
  ],

  // Budget
  [/^Known total excludes items with an unknown amount\.?$/, () => "Tổng đã biết không gồm các mục chưa rõ giá."],
  [/^Estimated range straddles the budget\.?$/, () => "Khoảng ước tính vượt qua ngân sách."],
  [
    /^Transport costs are unknown because no provider offer was available\.?$/,
    () => "Chi phí đi lại chưa rõ vì không có báo giá nhà cung cấp.",
  ],
  [
    /^Lodging costs are unknown because no provider offer was available\.?$/,
    () => "Chi phí lưu trú chưa rõ vì không có báo giá nhà cung cấp.",
  ],
  [
    /^(\d+) people may not fit in (\d+) room\(s\)\.?$/,
    (m) => `${m[1]} người có thể không vừa ${m[2]} phòng.`,
  ],
  [
    /^Cheapest option exceeds the budget by ([\d,]+) VND\.?$/,
    (m) => `Phương án rẻ nhất vượt ngân sách ${m[1].replace(/,/g, ".")} ₫.`,
  ],

  // Cost line notes
  [/^Reference range from huetripo; assumed per person per meal; verify before travel.?$/, () => "Khoảng giá tham khảo từ huetripo; giả định mỗi người mỗi bữa; cần kiểm tra trước khi đi."],
  [/^Reference price from huetripo; assumed per person; verify before travel.?$/, () => "Giá tham khảo từ huetripo; giả định mỗi người; cần kiểm tra trước khi đi."],
  [/^No price on this POI; category median used. Assumed per person per meal.?$/, () => "Địa điểm chưa có giá; dùng trung vị của loại; giả định mỗi người mỗi bữa."],
  [/^Median of (.+) reference ranges in huetripo; assumed per person per meal; verify before travel.?$/, (m) => `Trung vị khoảng giá tham khảo loại “${m[1]}” từ huetripo; giả định mỗi người mỗi bữa; cần kiểm tra.`],
  [/^Assumed group cost per day; the source has no in-city transport prices.?$/, () => "Giả định chi phí cả nhóm mỗi ngày; nguồn không có giá đi lại trong thành phố."],
  [/^Free according to source.?$/, () => "Nguồn ghi là miễn phí."],
  [/^No admission price in the source.?$/, () => "Nguồn không có giá vé."],
  [/^No compatible provider offer.?$/, () => "Không có báo giá phù hợp từ nhà cung cấp."],

  // Itinerary shape (step 6)
  [/^Sunset time is an estimate for the month \(Huế, local time\)\.?$/, () => "Giờ hoàng hôn là ước lượng theo tháng (giờ Huế)."],

  // Plan attempts and approval
  [/^no budget option$/, () => "Không có phương án ngân sách."],
  [/^Plan has no budget option labelled (.+)\.?$/, (m) => `Kế hoạch không có phương án ngân sách nhãn ${m[1]}.`],

  // Booking provider
  [/^Provider timed out; status will be reconciled\.?$/, () => "Nhà cung cấp quá thời gian chờ; trạng thái sẽ được đối soát."],
  [/^Provider did not confirm the booking\.?$/, () => "Nhà cung cấp chưa xác nhận đặt chỗ."],
  [/^Provider has not confirmed the booking yet\.?$/, () => "Nhà cung cấp chưa xác nhận đặt chỗ."],
  [/^Offer no longer available$/, () => "Báo giá không còn hiệu lực."],
];

/** Vietnamese text for a backend warning, or the original text when no rule matches. */
export function translateWarning(text: string): string {
  const trimmed = text.trim();
  for (const [pattern, render] of RULES) {
    const match = trimmed.match(pattern);
    if (match) return render(match);
  }
  return text;
}

/** Translates each warning and drops repeats, keeping the first occurrence. */
export function translateWarnings(texts: string[]): string[] {
  return [...new Set(texts.map(translateWarning))];
}
