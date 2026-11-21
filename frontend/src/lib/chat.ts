// Chat helpers: the conversation id in localStorage, transcript shaping, and the rules for which
// quick replies and confirmation buttons a bot reply shows. The backend decides every answer.
import type { ChatHistory, ChatPlanCard, ChatReply } from "../api/types";
import { optionLabelText } from "./budget";
import { newUuid } from "./ids";
import { safeGet, safeSet } from "./storage";

export const CHAT_ID_KEY = "hue.chatId";
/** The model named in the "Hiểu bằng: LLM" tag. The backend reads QU_MODEL; this is the default. */
export const CHAT_LLM_MODEL = "qwen3.5:4b";

const APPROVE_PREFIX = "Duyệt ";
const CONFIRM_TEXT = "đồng ý";
const CANCEL_TEXT = "huỷ";
const DEFAULTS_KIND = "defaults";
const AWAITING = "AWAITING_APPROVAL";

export interface ChatMessage {
  key: string;
  role: "user" | "assistant";
  text: string;
  reply: ChatReply | null;
}

/** A 32-character hex id, the same shape the backend's conversation ids use. */
export function newConversationId(): string {
  return newUuid().replace(/-/g, "");
}

/** The stored conversation id, or a new one saved for next time. Storage failures fall back to memory. */
export function loadConversationId(): string {
  const stored = safeGet(CHAT_ID_KEY);
  if (stored && /^[0-9a-f]{32}$/.test(stored)) return stored;
  return startNewConversation();
}

/** Starts a fresh conversation and remembers its id. */
export function startNewConversation(): string {
  const id = newConversationId();
  safeSet(CHAT_ID_KEY, id);
  return id;
}

/** The text shown on a bot reply's tag. OLLAMA means the LLM read the message; anything else is the rules. */
export function sourceTagText(source: string): string {
  if (source === "OLLAMA") return `Hiểu bằng: LLM (${CHAT_LLM_MODEL})`;
  return "Hiểu bằng: luật (Ollama không chạy)";
}

/** "Duyệt BUDGET" is sent as-is but shown with the Vietnamese budget name. Other texts are unchanged. */
export function quickReplyLabel(text: string): string {
  if (!text.startsWith(APPROVE_PREFIX)) return text;
  const code = text.slice(APPROVE_PREFIX.length);
  const name = optionLabelText(code);
  return name === "—" ? text : `${APPROVE_PREFIX}${name}`;
}

/** Only the last bot message keeps its confirmation: an older pending step was already cancelled by the backend. */
export function showsConfirmation(reply: ChatReply, isLast: boolean): boolean {
  const kind = reply.pending_confirmation?.kind;
  return isLast && kind !== undefined && kind !== DEFAULTS_KIND;
}

/**
 * Quick replies to show under a bot reply. A pending approve or book step is answered with the
 * confirmation buttons instead, and an approve chip is dropped when the plan card already offers it.
 */
export function visibleQuickReplies(reply: ChatReply): string[] {
  const kind = reply.pending_confirmation?.kind;
  if (kind !== undefined && kind !== DEFAULTS_KIND) return [];
  const card = reply.cards.find((item): item is ChatPlanCard => item.kind === "plan_summary");
  const offersApprove = card !== undefined && approvable(card.status, card.budget_options.length);
  return reply.quick_replies.filter((text) => !(offersApprove && text.startsWith(APPROVE_PREFIX)));
}

/** Approve buttons are offered only while the plan waits for approval and has labelled options. */
export function approvable(status: string, optionCount: number): boolean {
  return status === AWAITING && optionCount > 0;
}

export const CONFIRM_BUTTON = { label: "Xác nhận", text: CONFIRM_TEXT } as const;
export const CANCEL_BUTTON = { label: "Huỷ", text: CANCEL_TEXT } as const;

/** Turns a stored conversation into transcript messages, in the order the server returned them. */
export function messagesFromHistory(history: ChatHistory): ChatMessage[] {
  return history.messages.map((record) => ({
    key: record.id,
    role: record.role,
    text: record.text,
    reply: record.role === "assistant" ? record.payload : null,
  }));
}
