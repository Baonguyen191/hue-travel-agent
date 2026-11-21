import {
  CANCEL_BUTTON,
  CONFIRM_BUTTON,
  quickReplyLabel,
  showsConfirmation,
  sourceTagText,
  visibleQuickReplies,
  type ChatMessage,
} from "../../lib/chat";
import { ChatCardView } from "./ChatCards";

interface MessageBubbleProps {
  message: ChatMessage;
  /** True for the newest bot message: only its confirmation and approve buttons are live. */
  isLast: boolean;
  disabled: boolean;
  onSend: (text: string) => void;
}

const CHIP =
  "rounded-full border border-teal-700 bg-white px-3 py-1.5 text-sm font-medium text-teal-800 hover:bg-teal-50 disabled:opacity-50";

/** One message of the transcript: a user bubble, or a bot bubble with its cards, buttons and source tag. */
export function MessageBubble({ message, isLast, disabled, onSend }: MessageBubbleProps) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-sm bg-teal-700 px-4 py-2 text-white md:max-w-[75%]">
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
      <div className="max-w-[92%] rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm md:max-w-[80%]">
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
              className="rounded-md bg-teal-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-teal-800 disabled:opacity-50"
            >
              {CONFIRM_BUTTON.label}
            </button>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onSend(CANCEL_BUTTON.text)}
              className="rounded-md border border-slate-400 bg-white px-3 py-1.5 text-sm font-medium text-slate-800 hover:bg-slate-100 disabled:opacity-50"
            >
              {CANCEL_BUTTON.label}
            </button>
          </div>
        ) : null}
        {chips.length > 0 ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {chips.map((text) => (
              <button key={text} type="button" disabled={disabled} onClick={() => onSend(text)} className={CHIP}>
                {quickReplyLabel(text)}
              </button>
            ))}
          </div>
        ) : null}
        {reply ? (
          <p className="mt-2 text-xs text-slate-500">{sourceTagText(reply.understanding.source)}</p>
        ) : null}
      </div>
    </article>
  );
}
