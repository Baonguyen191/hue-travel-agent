import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { buttonClass } from "../ui";

interface ComposerProps {
  disabled: boolean;
  onSend: (text: string) => void;
  /** Text to put in the field (not sent). A new nonce refills even with the same text. */
  prefill?: { text: string; nonce: number };
}

/** Message input. Enter sends; Shift+Enter starts a new line; IME composition never sends. */
export function Composer({ disabled, onSend, prefill }: ComposerProps) {
  const [draft, setDraft] = useState(prefill?.text ?? "");
  const canSend = !disabled && draft.trim() !== "";

  useEffect(() => {
    if (prefill) setDraft(prefill.text);
  }, [prefill?.nonce, prefill?.text]);

  function send() {
    if (!canSend) return;
    onSend(draft);
    setDraft("");
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    send();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    send();
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2 sm:flex-row sm:items-end">
      <label htmlFor="chat-input" className="sr-only">
        Tin nhắn
      </label>
      <textarea
        id="chat-input"
        rows={2}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Ví dụ: Tôi đi Huế 3 ngày 2 đêm từ 05/12, xuất phát Hà Nội, 2 người"
        className="min-h-[3rem] w-full flex-1 resize-y rounded-2xl border border-vien bg-nga px-4 py-2.5 text-base text-muc placeholder:text-muc-soft/70 focus:border-kim focus:outline-none focus:ring-2 focus:ring-kim/40"
      />
      <button type="submit" disabled={!canSend} className={buttonClass("primary")}>
        Gửi
      </button>
      <p className="text-xs text-muc-soft">Enter để gửi, Shift+Enter để xuống dòng.</p>
    </form>
  );
}
