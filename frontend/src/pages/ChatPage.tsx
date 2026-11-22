import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api, errorMessage, isForbidden, isNotFound } from "../api/client";
import { ErrorBanner } from "../components/ErrorBanner";
import { ChatWelcome } from "../components/chat/ChatWelcome";
import { Composer } from "../components/chat/Composer";
import { MessageBubble } from "../components/chat/MessageBubble";
import {
  loadConversationId,
  messagesFromHistory,
  startNewConversation,
  type ChatMessage,
} from "../lib/chat";
import { newUuid } from "../lib/ids";
import { LINK, SectionHeading, buttonClass } from "../components/ui";

const FORBIDDEN_NOTICE =
  "Cuộc trò chuyện đã lưu thuộc về người dùng khác, nên mình đã mở cuộc trò chuyện mới.";

/** Chat screen: one conversation id per browser, history on mount, one request per message. */
export function ChatPage() {
  const [conversationId, setConversationId] = useState<string>(() => loadConversationId());
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const currentId = useRef(conversationId);
  const endRef = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const [prefill, setPrefill] = useState<{ text: string; nonce: number } | undefined>(() => {
    const text = (location.state as { prefill?: unknown } | null)?.prefill;
    return typeof text === "string" && text ? { text, nonce: 0 } : undefined;
  });
  const pick = (text: string) => setPrefill((current) => ({ text, nonce: (current?.nonce ?? 0) + 1 }));

  useEffect(() => {
    let active = true;
    setLoading(true);
    api
      .chatHistory(conversationId)
      .then((history) => {
        if (active) setMessages(messagesFromHistory(history));
      })
      .catch((caught: unknown) => {
        if (!active) return;
        if (isNotFound(caught)) {
          setMessages([]);
          return;
        }
        if (isForbidden(caught)) {
          switchConversation(startNewConversation(), FORBIDDEN_NOTICE);
          return;
        }
        setError(errorMessage(caught));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [conversationId]);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages.length, waiting]);

  function switchConversation(id: string, notice: string | null = null) {
    currentId.current = id;
    setConversationId(id);
    setMessages([]);
    setWaiting(false);
    setError(notice);
  }

  async function send(text: string) {
    const trimmed = text.trim();
    if (trimmed === "" || waiting) return;
    const id = conversationId;
    setMessages((previous) => [...previous, { key: newUuid(), role: "user", text: trimmed, reply: null }]);
    setWaiting(true);
    setError(null);
    try {
      const reply = await api.chatSend(id, trimmed);
      if (currentId.current !== id) return;
      setMessages((previous) => [...previous, { key: newUuid(), role: "assistant", text: reply.text, reply }]);
    } catch (caught: unknown) {
      if (currentId.current !== id) return;
      if (isForbidden(caught)) {
        switchConversation(startNewConversation(), FORBIDDEN_NOTICE);
        return;
      }
      setError(errorMessage(caught));
    } finally {
      if (currentId.current === id) setWaiting(false);
    }
  }

  const lastAssistant = messages.reduce((found, message, index) => (message.role === "assistant" ? index : found), -1);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionHeading as="h1">Trò chuyện</SectionHeading>
        <div className="flex flex-wrap items-center gap-3">
          <Link to="/form" className={`${LINK} text-sm`}>
            Nhập bằng form
          </Link>
          <button
            type="button"
            onClick={() => switchConversation(startNewConversation())}
            className={buttonClass("outline", "sm")}
          >
            Cuộc trò chuyện mới
          </button>
        </div>
      </div>

      {error ? <ErrorBanner message={error} /> : null}

      <section aria-label="Nội dung trò chuyện" className="flex min-h-[12rem] flex-col gap-3 rounded-2xl p-1 md:p-2">
        {loading && messages.length === 0 ? <p className="text-sm text-muc-soft">Đang tải lịch sử…</p> : null}
        {!loading && messages.length === 0 ? <ChatWelcome onPick={pick} /> : null}
        <div role="log" aria-live="polite" className="flex flex-col gap-3">
          {messages.map((message, index) => (
            <MessageBubble
              key={message.key}
              message={message}
              isLast={index === lastAssistant}
              disabled={waiting}
              onSend={send}
            />
          ))}
          {waiting ? (
            <div role="status" className="flex justify-start">
              <p className="animate-pulse rounded-2xl rounded-bl-sm bg-son px-4 py-2 text-sm text-on-son">
                đang suy nghĩ…
              </p>
            </div>
          ) : null}
        </div>
        <div ref={endRef} />
      </section>

      <Composer disabled={waiting} onSend={(text) => void send(text)} prefill={prefill} />
    </div>
  );
}
