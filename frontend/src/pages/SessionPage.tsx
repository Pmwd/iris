import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { ChatTimeline } from "../components/ChatTimeline";
import {
  Composer,
  DEFAULT_PROFILE,
  ROLE_PROFILES,
} from "../components/Composer";
import { MemoryPanel } from "../components/MemoryPanel";
import { StatusBadge } from "../components/StatusBadge";
import { errorText, formatTime } from "../format";
import { useTurnStream } from "../hooks/useTurnStream";
import { ROLE_LABELS } from "../labels";
import type {
  Message,
  PermissionProfile,
  RoleId,
  Session,
  SummaryResponse,
  Turn,
  Workspace,
} from "../types";

const ACTIVE = new Set(["starting", "running", "canceling"]);

const SUGGESTIONS: Record<RoleId, string[]> = {
  coding: [
    "阅读这个仓库，说明项目结构和主要入口。",
    "定位一个 bug 并修复，运行相关测试。",
    "把这段逻辑重构得更清晰，保持行为不变。",
  ],
  scholar: [
    "比较三种方案的优缺点，并标明不确定性。",
    "总结这些资料里的已知事实、观点与假设。",
    "为这个问题列出需要进一步查证的点。",
  ],
};

export function SessionPage() {
  const { role, sessionId } = useParams();
  const roleId: RoleId | null =
    role === "scholar" ? "scholar" : role === "coding" ? "coding" : null;
  const [session, setSession] = useState<Session | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [input, setInput] = useState("");
  const [profile, setProfile] = useState<PermissionProfile>("edit");
  const [titleDraft, setTitleDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  async function load() {
    if (!sessionId) return;
    try {
      const data = await api.getSession(sessionId);
      const [messageList, turnList, summaryData] = await Promise.all([
        api.listMessages(sessionId),
        api.listTurns(sessionId),
        api.getSummary(sessionId),
      ]);
      setSession(data);
      setWorkspace(data.workspace ?? null);
      setMessages(messageList);
      setTurns(turnList);
      setSummary(summaryData);
      setTitleDraft(data.title);
      setProfile((current) =>
        ROLE_PROFILES[data.role].includes(current)
          ? current
          : DEFAULT_PROFILE[data.role],
      );
      setError(null);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setSession(null);
    setWorkspace(null);
    setMessages([]);
    setTurns([]);
    setSummary(null);
    setInput("");
    setProfile("edit");
    setLoading(true);
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const activeTurn = turns.find((turn) => ACTIVE.has(turn.status)) ?? null;
  const { events: liveEvents, status: liveStatus } = useTurnStream(
    activeTurn?.id ?? null,
    activeTurn?.status ?? "",
    () => {
      void load();
    },
  );
  const lastTurn = turns.length ? turns[turns.length - 1] : null;

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, turns.length, liveEvents.length]);

  async function send() {
    if (!session || !input.trim()) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api.sendMessage(session.id, {
        content: input,
        permission_profile: profile,
      });
      setTurns((current) => [...current, result.turn]);
      setMessages((current) => [...current, result.user_message]);
      setInput("");
      await load();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    if (!activeTurn) return;
    setBusy(true);
    setError(null);
    try {
      await api.cancelTurn(activeTurn.id);
      await load();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function saveTitle() {
    if (!session) return;
    const next = titleDraft.trim();
    if (!next || next === session.title) return;
    try {
      await api.updateSession(session.id, { title: next });
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function endSession() {
    if (!session) return;
    if (!window.confirm("结束会话会触发最终摘要。确定继续？")) return;
    setBusy(true);
    setError(null);
    try {
      await api.endSession(session.id);
      setMessage("会话已结束，最终摘要已排队。");
      await load();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function compactSession() {
    if (!session) return;
    if (
      !window.confirm(
        "压缩会生成一份摘要；摘要完成后，下一条消息将启动新的 CLI 会话并带上摘要与长期事实。继续？",
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const outcome = await api.compactSession(session.id);
      setMessage(
        outcome.queued
          ? "压缩已排队。摘要完成后下一条消息会使用新的 CLI 会话。"
          : "已有摘要任务在运行，请等它完成后再压缩。",
      );
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function resumeSession() {
    if (!session) return;
    setBusy(true);
    try {
      await api.updateSession(session.id, { status: "active" });
      setMessage("会话已重新打开。");
      await load();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  if (!roleId) {
    return (
      <div className="page-empty">
        <h2>未知角色</h2>
        <p className="muted">Iris 只有 Coding 和 Scholar 两个角色。</p>
      </div>
    );
  }

  if (loading || !session) {
    return (
      <div className="page">
        {error ? <div className="alert alert-error">{error}</div> : <div className="muted">加载会话…</div>}
      </div>
    );
  }

  const executeAllowed = Boolean(workspace?.allowed_tools?.length);
  const disabledReason =
    session.status === "active"
      ? null
      : session.status === "ended"
        ? "会话已结束。可以继续会话，或新建一个会话。"
        : "会话已归档。";

  return (
    <div className="session-layout">
      <div className="chat-column">
        <header className="chat-header">
          <div className="chat-header-main">
            <div className="chat-title-row">
              <span className="role-badge">{ROLE_LABELS[session.role]}</span>
              <input
                className="title-input"
                value={titleDraft}
                onChange={(event) => setTitleDraft(event.target.value)}
                onBlur={() => void saveTitle()}
                onKeyDown={(event) => {
                  if (event.key === "Enter") event.currentTarget.blur();
                  if (event.key === "Escape") {
                    setTitleDraft(session.title);
                    event.currentTarget.blur();
                  }
                }}
                aria-label="会话标题"
              />
              <StatusBadge status={session.status} />
            </div>
            <div className="chat-sub">
              {workspace ? (
                <Link className="chip" to={`/workspaces/${workspace.id}`}>
                  {workspace.name}
                </Link>
              ) : (
                <span className="chip">无工作区</span>
              )}
              <span>更新 {formatTime(session.updated_at)}</span>
              <span>
                {session.cli_session_id
                  ? `CLI ${session.cli_session_id.slice(0, 8)}`
                  : "新 CLI 会话"}
              </span>
              {activeTurn ? <StatusBadge status={liveStatus} /> : null}
            </div>
          </div>
          <div className="chat-actions">
            {session.status === "ended" ? (
              <button
                type="button"
                className="button small"
                onClick={() => void resumeSession()}
                disabled={busy}
              >
                继续会话
              </button>
            ) : null}
            <button
              type="button"
              className="button small ghost"
              onClick={() => void compactSession()}
              disabled={busy || Boolean(activeTurn)}
            >
              压缩并继续
            </button>
            {session.status === "active" ? (
              <button
                type="button"
                className="button small danger"
                onClick={() => void endSession()}
                disabled={busy || Boolean(activeTurn)}
              >
                结束会话
              </button>
            ) : null}
          </div>
        </header>

        {error ? <div className="alert alert-error">{error}</div> : null}
        {message ? <div className="alert alert-success">{message}</div> : null}

        <div className="chat-scroll" ref={scrollRef}>
          <ChatTimeline
            messages={messages}
            turns={turns}
            liveTurnId={activeTurn?.id ?? null}
            liveEvents={liveEvents}
            emptyHint={
              <div className="chat-empty">
                <div className="empty-illustration">◒</div>
                <h2>开始对话</h2>
                <p className="muted">
                  原始消息、工具调用与执行结果都会保存。结束会话或达到阈值后自动生成摘要。
                </p>
                <div className="suggestions">
                  {SUGGESTIONS[session.role].map((suggestion) => (
                    <button
                      type="button"
                      key={suggestion}
                      className="suggestion"
                      onClick={() => setInput(suggestion)}
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            }
          />
        </div>

        <Composer
          role={session.role}
          value={input}
          onChange={setInput}
          onSend={() => void send()}
          onStop={() => void stop()}
          profile={profile}
          onProfileChange={setProfile}
          busy={busy}
          active={Boolean(activeTurn)}
          executeAllowed={executeAllowed}
          disabledReason={disabledReason}
        />
      </div>

      <MemoryPanel
        session={session}
        summary={summary}
        lastTurn={lastTurn}
        onChanged={() => void load()}
      />
    </div>
  );
}
