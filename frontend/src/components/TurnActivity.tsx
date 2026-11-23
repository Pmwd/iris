import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { asRecord, asText } from "../format";
import type { Turn, TurnEvent } from "../types";
import { ToolCallCard, type ToolCall } from "./ToolCallCard";

type ActivityItem =
  | { type: "tool"; call: ToolCall }
  | { type: "text"; text: string }
  | { type: "error"; text: string };

function buildItems(events: TurnEvent[]): ActivityItem[] {
  const items: ActivityItem[] = [];
  const byId = new Map<string, ToolCall>();
  let lastTool: ToolCall | null = null;
  for (const event of events) {
    const payload = asRecord(event.payload);
    if (event.kind === "tool.use") {
      const call: ToolCall = {
        id: typeof payload.id === "string" ? payload.id : undefined,
        name: String(payload.name ?? "tool"),
        input: payload.input,
      };
      items.push({ type: "tool", call });
      if (call.id) byId.set(call.id, call);
      lastTool = call;
    } else if (event.kind === "tool.result") {
      const id =
        typeof payload.tool_use_id === "string" ? payload.tool_use_id : undefined;
      const target = (id ? byId.get(id) : undefined) ?? lastTool;
      if (target) {
        target.result = payload.content;
        target.isError = Boolean(payload.is_error);
      }
    } else if (event.kind === "assistant.text") {
      const text = typeof payload.text === "string" ? payload.text : "";
      if (text.trim()) items.push({ type: "text", text });
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
                <div className="activity-text" key={index}>
                  {item.text}
                </div>
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
