import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { asRecord, asText } from "../format";
import type { Approval, Turn, TurnEvent } from "../types";
import { ApprovalCard } from "./ApprovalCard";
import { ToolCallCard, type ToolCall } from "./ToolCallCard";

type ActivityItem =
  | { type: "tool"; call: ToolCall }
  | { type: "text"; text: string; streaming?: boolean }
  | { type: "error"; text: string }
  | { type: "approval"; approval: Approval };

function approvalFromPayload(payload: Record<string, unknown>): Approval | null {
  const id = typeof payload.approval_id === "string" ? payload.approval_id : "";
  if (!id) return null;
  const status =
    payload.status === "allowed" ||
    payload.status === "denied" ||
    payload.status === "expired"
      ? payload.status
      : "pending";
  const decision =
    payload.decision === "allow" ||
    payload.decision === "deny" ||
    payload.decision === "always"
      ? payload.decision
      : null;
  return {
    id,
    turn_id: String(payload.turn_id ?? ""),
    session_id: String(payload.session_id ?? ""),
    tool_name: String(payload.tool_name ?? "tool"),
    input: asRecord(payload.input),
    status,
    decision,
    message: String(payload.message ?? ""),
    decided_by:
      typeof payload.decided_by === "string" ? payload.decided_by : null,
    created_at: String(payload.created_at ?? ""),
    decided_at:
      typeof payload.decided_at === "string" ? payload.decided_at : null,
    title: typeof payload.title === "string" ? payload.title : null,
    description:
      typeof payload.description === "string" ? payload.description : null,
  };
}

function buildItems(events: TurnEvent[]): ActivityItem[] {
  const items: ActivityItem[] = [];
  const byId = new Map<string, ToolCall>();
  const approvalIndex = new Map<string, number>();
  let lastTool: ToolCall | null = null;
  let streamIndex: number | null = null;

  const sealStream = () => {
    if (streamIndex === null) return;
    const item = items[streamIndex];
    if (item && item.type === "text") item.streaming = false;
    streamIndex = null;
  };

  for (const event of events) {
    const payload = asRecord(event.payload);
    if (event.kind === "tool.use") {
      sealStream();
      const call: ToolCall = {
        id: typeof payload.id === "string" ? payload.id : undefined,
        name: String(payload.name ?? "tool"),
        input: payload.input,
      };
      items.push({ type: "tool", call });
      if (call.id) byId.set(call.id, call);
      lastTool = call;
    } else if (event.kind === "tool.result") {
      sealStream();
      const id =
        typeof payload.tool_use_id === "string" ? payload.tool_use_id : undefined;
      const target = (id ? byId.get(id) : undefined) ?? lastTool;
      if (target) {
        target.result = payload.content;
        target.isError = Boolean(payload.is_error);
      }
    } else if (event.kind === "assistant.delta") {
      const text = typeof payload.text === "string" ? payload.text : "";
      if (!text) continue;
      const item = streamIndex !== null ? items[streamIndex] : undefined;
      if (item && item.type === "text") {
        item.text += text;
      } else {
        items.push({ type: "text", text, streaming: true });
        streamIndex = items.length - 1;
      }
    } else if (event.kind === "assistant.text") {
      const text = typeof payload.text === "string" ? payload.text : "";
      const item = streamIndex !== null ? items[streamIndex] : undefined;
      if (item && item.type === "text") {
        item.text = text;
        item.streaming = false;
        streamIndex = null;
      } else if (text.trim()) {
        items.push({ type: "text", text });
      }
    } else if (
      event.kind === "approval.requested" ||
      event.kind === "approval.decided"
    ) {
      const approval = approvalFromPayload(payload);
      if (!approval) continue;
      const index = approvalIndex.get(approval.id);
      if (index !== undefined) {
        const existing = items[index];
        if (existing.type === "approval") {
          existing.approval = { ...existing.approval, ...approval };
        }
      } else {
        approvalIndex.set(approval.id, items.length);
        items.push({ type: "approval", approval });
      }
    } else if (event.kind === "cli.stderr") {
      const lines = Array.isArray(payload.lines)
        ? (payload.lines as unknown[]).map(String).join("\n")
        : asText(payload);
      items.push({ type: "error", text: lines });
    } else if (event.kind === "permission.denied") {
      items.push({ type: "error", text: `权限被拒绝：${asText(payload)}` });
    } else if (event.kind === "cli.unparsed") {
      items.push({ type: "error", text: String(payload.text ?? "") });
    }
  }
  return items;
}

export function TurnActivity({
  turn,
  live,
  liveEvents,
}: {
  turn: Turn;
  live?: boolean;
  liveEvents?: TurnEvent[];
}) {
  const [open, setOpen] = useState(Boolean(live));
  const [events, setEvents] = useState<TurnEvent[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (live) setOpen(true);
  }, [live]);

  const source = live ? liveEvents ?? [] : events;
  const items = useMemo(() => buildItems(source), [source]);
  const toolCount = items.filter((item) => item.type === "tool").length;

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && !live && !loaded && !loading) {
      setLoading(true);
      try {
        const history = await api.listTurnEvents(turn.id, 0);
        setEvents(history);
        setLoaded(true);
      } finally {
        setLoading(false);
      }
    }
  }

  return (
    <div className="turn-activity">
      <button type="button" className="activity-toggle" onClick={() => void toggle()}>
        <span className={`activity-dot${live ? " pulse" : ""}`} />
        <span>{live ? "正在运行" : "工具与过程"}</span>
        {toolCount ? <span className="pill">{toolCount} 次工具调用</span> : null}
        {!live && turn.error_type ? (
          <span className="pill pill-error">{turn.error_type}</span>
        ) : null}
        <span className="tool-chevron">{open ? "▾" : "▸"}</span>
      </button>
      {open ? (
        <div className="activity-body">
          {loading ? (
            <div className="muted">加载事件…</div>
          ) : items.length === 0 ? (
            <div className="muted">
              {live ? "等待模型输出…" : "没有记录到工具调用。"}
            </div>
          ) : (
            items.map((item, index) =>
              item.type === "tool" ? (
                <ToolCallCard key={index} call={item.call} />
              ) : item.type === "text" ? (
                <div
                  className={
                    item.streaming ? "activity-text streaming" : "activity-text"
                  }
                  key={index}
                >
                  {item.text}
                </div>
              ) : item.type === "approval" ? (
                <ApprovalCard
                  key={`approval-${item.approval.id}-${item.approval.status}`}
                  approval={item.approval}
                />
              ) : (
                <pre className="activity-error" key={index}>
                  {item.text}
                </pre>
              ),
            )
          )}
        </div>
      ) : null}
    </div>
  );
}
