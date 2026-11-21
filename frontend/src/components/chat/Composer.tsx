import { useState, type FormEvent, type KeyboardEvent } from "react";

interface ComposerProps {
  disabled: boolean;
  onSend: (text: string) => void;
}

/** Message input. Enter sends; Shift+Enter starts a new line; IME composition never sends. */
export function Composer({ disabled, onSend }: ComposerProps) {
  const [draft, setDraft] = useState("");
  const canSend = !disabled && draft.trim() !== "";

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
        className="min-h-[3rem] w-full flex-1 resize-y rounded-md border border-slate-300 bg-white px-3 py-2 text-base focus:border-teal-600 focus:outline-none focus:ring-2 focus:ring-teal-200"
      />
      <button
        type="submit"
        disabled={!canSend}
        className="rounded-md bg-teal-700 px-5 py-2.5 font-medium text-white hover:bg-teal-800 disabled:opacity-50"
      >
        Gửi
      </button>
      <p className="text-xs text-slate-500">Enter để gửi, Shift+Enter để xuống dòng.</p>
    </form>
  );
}
