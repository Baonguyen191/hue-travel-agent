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

/**
 * One message of the transcript. A user message is a cream bubble. A bot message is a son bubble holding only its
 * text and source tag; its cards and buttons sit below the bubble on the page background.
 */
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
  const cards = reply?.cards ?? [];
  const hasBelow = cards.length > 0 || confirm || chips.length > 0;

  return (
    <article aria-label="Trợ lý" className="flex flex-col items-start gap-2">
      <div className="max-w-[92%] rounded-2xl rounded-bl-sm bg-son px-4 py-3 text-on-son md:max-w-[80%]">
        <p className="whitespace-pre-wrap break-words">{message.text}</p>
        {reply ? <p className="mt-2 text-xs text-on-son/75">{sourceTagText(reply.understanding.source)}</p> : null}
      </div>
      {hasBelow ? (
        <div className="flex w-full max-w-[92%] flex-col gap-2 md:max-w-[80%]">
          {cards.map((card, index) => (
            <ChatCardView
              key={`${card.kind}-${index}`}
              card={card}
              live={isLast}
              disabled={disabled}
              onSend={onSend}
            />
          ))}
          {confirm ? (
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={disabled}
                onClick={() => onSend(CONFIRM_BUTTON.text)}
                className={buttonClass("primary", "sm")}
              >
                {CONFIRM_BUTTON.label}
              </button>
              <button
                type="button"
                disabled={disabled}
                onClick={() => onSend(CANCEL_BUTTON.text)}
                className={buttonClass("outline", "sm")}
              >
                {CANCEL_BUTTON.label}
              </button>
            </div>
          ) : null}
          {chips.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {chips.map((text) => (
                <button
                  key={text}
                  type="button"
                  disabled={disabled}
                  onClick={() => onSend(text)}
                  className={buttonClass("outline", "sm")}
                >
                  {quickReplyLabel(text)}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
