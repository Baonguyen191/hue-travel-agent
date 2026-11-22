import { PlacePhoto, SectionHeading } from "../ui";

export const SAMPLE_QUESTIONS = [
  "Từ Hà Nội, 2 người, đi Huế 2 ngày từ 20/12",
  "Đại Nội mấy giờ mở cửa?",
  "Quán cà phê nào gần Đại Nội?",
  "Từ Đà Nẵng, 3 người, đi Huế 3 ngày, thích lăng tẩm",
] as const;

const HERO_POI = "huetripo:531787";

/** Empty chat: a Huế photo, a greeting and sample questions that fill the composer. */
export function ChatWelcome({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-vien bg-nga">
      <div className="relative">
        <PlacePhoto poiId={HERO_POI} name="Đại Nội Huế" category="historic" size="lg" aspect="16/9" />
        <div className="absolute inset-0 bg-gradient-to-t from-muc/80 via-muc/20 to-transparent" aria-hidden="true" />
        <p className="absolute bottom-3 left-4 right-4 font-serif text-xl font-semibold text-nga md:text-2xl">
          Chào bạn, mình là trợ lý du lịch Huế
        </p>
      </div>
      <div className="space-y-3 p-4">
        <p className="text-sm leading-relaxed text-muc">
          Hãy kể chuyến đi Huế của bạn: ngày đi, số ngày, xuất phát từ đâu, số người và ngân sách. Bạn cũng có thể hỏi
          giờ mở cửa của một địa điểm.
        </p>
        <SectionHeading as="h2" className="text-sm md:text-base">
          Thử hỏi
        </SectionHeading>
        <ul className="flex flex-wrap gap-2">
          {SAMPLE_QUESTIONS.map((question) => (
            <li key={question}>
              <button
                type="button"
                onClick={() => onPick(question)}
                className="rounded-full border border-vien bg-giay px-3 py-1.5 text-left text-sm text-muc hover:border-kim hover:bg-kim-soft"
              >
                {question}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
