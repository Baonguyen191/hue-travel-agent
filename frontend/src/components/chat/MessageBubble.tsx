import {
  CANCEL_BUTTON,
  CONFIRM_BUTTON,
  quickReplyLabel,
  showsConfirmation,
  sourceTagText,
  visibleQuickReplies,
  type ChatMessage,
} from "../../lib/chat";
import { buttonClass } from "../ui";
import { ChatCardView } from "./ChatCards";

interface MessageBubbleProps {
  message: ChatMessage;
  /** True for the newest bot message: only its confirmation and approve buttons are live. */
  isLast: boolean;
  disabled: boolean;
  onSend: (text: string) => void;
}

/** Outline button for use directly on the dark red bot bubble (the shared outline variant is son-on-son there). */
const ON_SON_OUTLINE =
  "inline-flex items-center justify-center rounded-full border-[1.5px] border-kim px-3 py-1.5 text-sm font-semibold text-on-son transition-colors hover:bg-son-dark focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-kim disabled:cursor-not-allowed disabled:opacity-50";

/** One message of the transcript: a user bubble, or a bot bubble with its cards, buttons and source tag. */
export function MessageBubble({ message, isLast, disabled, onSend }: MessageBubbleProps) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-sm border border-vien bg-nga px-4 py-2 text-muc md:max-w-[75%]">
          {message.text}
        </p>
      </div>
    );
  }

  const reply = message.reply;
  const confirm = reply !== null && showsConfirmation(reply, isLast);
  const chips = reply === null ? [] : visibleQuickReplies(reply);

  return (
    <article aria-label="Trợ lý" className="flex justify-start">
      <div className="max-w-[92%] rounded-2xl rounded-bl-sm bg-son px-4 py-3 text-on-son md:max-w-[80%]">
        <p className="whitespace-pre-wrap break-words">{message.text}</p>
        {reply?.cards.map((card, index) => (
          <ChatCardView
            key={`${card.kind}-${index}`}
            card={card}
            live={isLast}
            disabled={disabled}
            onSend={onSend}
          />
        ))}
        {confirm ? (
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={disabled}
              onClick={() => onSend(CONFIRM_BUTTON.text)}
              className={buttonClass("secondary", "sm")}
            >
              {CONFIRM_BUTTON.label}
            </button>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onSend(CANCEL_BUTTON.text)}
              className={ON_SON_OUTLINE}
            >
              {CANCEL_BUTTON.label}
            </button>
          </div>
        ) : null}
        {chips.length > 0 ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {chips.map((text) => (
              <button key={text} type="button" disabled={disabled} onClick={() => onSend(text)} className={ON_SON_OUTLINE}>
                {quickReplyLabel(text)}
              </button>
            ))}
          </div>
        ) : null}
        {reply ? (
          <p className="mt-2 text-xs text-on-son/75">{sourceTagText(reply.understanding.source)}</p>
        ) : null}
      </div>
    </article>
  );
}
