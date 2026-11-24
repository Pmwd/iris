import { api } from "../api";
import { formatCost, formatTime } from "../format";
import { TURN_STATUS_LABELS } from "../labels";
import type { Message, Turn, TurnEvent } from "../types";
import { MarkdownMessage } from "./MarkdownMessage";
import { TurnActivity } from "./TurnActivity";
import { StatusBadge } from "./StatusBadge";

const ACTIVE = new Set(["starting", "running", "canceling"]);

export function ChatTimeline({
  messages,
  turns,
  liveTurnId,
  liveEvents,
  emptyHint,
  onRemember,
}: {
  messages: Message[];
  turns: Turn[];
  liveTurnId: string | null;
  liveEvents: TurnEvent[];
  emptyHint: React.ReactNode;
  onRemember?: (message: Message) => void;
}) {
  const byTurn = new Map<
    string,
    { user?: Message; assistant?: Message }
  >();
  const orphan: Message[] = [];
  for (const message of messages) {
    if (!message.turn_id) {
      orphan.push(message);
      continue;
    }
    const entry = byTurn.get(message.turn_id) ?? {};
    if (message.role === "user") entry.user = message;
    else if (message.role === "assistant") entry.assistant = message;
    byTurn.set(message.turn_id, entry);
  }

  if (turns.length === 0 && orphan.length === 0) {
    return <div className="chat-empty">{emptyHint}</div>;
  }

  return (
    <div className="chat-timeline">
      {orphan.map((message) => (
        <div className={`message message-${message.role}`} key={message.id}>
          <div className="message-body">
            <MarkdownMessage content={message.content} />
          </div>
        </div>
      ))}
      {turns.map((turn) => {
        const entry = byTurn.get(turn.id) ?? {};
        const live = turn.id === liveTurnId;
        const active = live || ACTIVE.has(turn.status);
        return (
          <div className="turn-block" key={turn.id}>
            {entry.user ? (
              <div className="message message-user">
                <div className="message-body">
                  <MarkdownMessage content={entry.user.content} />
                </div>
                <div className="message-meta">
                  你 · {formatTime(entry.user.created_at)}
                  {onRemember ? (
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => onRemember(entry.user as Message)}
                    >
                      记住
                    </button>
                  ) : null}
                </div>
              </div>
            ) : null}

            <TurnActivity
              turn={turn}
              live={live}
              liveEvents={live ? liveEvents : undefined}
            />

            {entry.assistant ? (
              <div className="message message-assistant">
                <div className="message-body">
                  <MarkdownMessage content={entry.assistant.content} />
                </div>
                <div className="message-meta">
                  Iris · {formatTime(turn.ended_at ?? turn.created_at)}
                  {onRemember ? (
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => onRemember(entry.assistant as Message)}
                    >
                      记住
                    </button>
                  ) : null}
                </div>
              </div>
            ) : active ? null : (
              <div className="message message-error">
                <div className="message-body">
                  {turn.error_message ||
                    (turn.status === "canceled"
                      ? "本次运行已取消。"
                      : turn.status === "interrupted"
                        ? "服务中断，运行未完成。"
                        : `运行${TURN_STATUS_LABELS[turn.status] ?? turn.status}，没有返回文本结果。`)}
                </div>
                <div className="message-meta">
                  <StatusBadge status={turn.status} />
                </div>
              </div>
            )}

            <div className="turn-meta">
              <span>#{turn.seq}</span>
              <span>{turn.mode === "resume" ? "续聊" : "新 CLI 会话"}</span>
              <span>{turn.permission_profile}</span>
              {turn.cost_usd !== null ? (
                <span>{formatCost(turn.cost_usd)}</span>
              ) : null}
              {turn.status !== "succeeded" ? (
                <StatusBadge status={turn.status} />
              ) : null}
              <a
                href={api.turnRawUrl(turn.id)}
                target="_blank"
                rel="noreferrer noopener"
              >
                原始日志
              </a>
            </div>
          </div>
        );
      })}
    </div>
  );
}
