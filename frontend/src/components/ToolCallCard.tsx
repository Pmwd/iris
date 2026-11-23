import { useState } from "react";
import { asText } from "../format";

export interface ToolCall {
  id?: string;
  name: string;
  input: unknown;
  result?: unknown;
  isError?: boolean;
}

export function ToolCallCard({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(false);
  const done = call.result !== undefined;
  return (
    <div className={`tool-card${call.isError ? " tool-card-error" : ""}`}>
      <button type="button" className="tool-head" onClick={() => setOpen(!open)}>
        <span className="tool-icon">⚙</span>
        <span className="tool-name">{call.name || "tool"}</span>
        {done ? (
          <span className={`pill ${call.isError ? "pill-error" : "pill-ok"}`}>
            {call.isError ? "失败" : "完成"}
          </span>
        ) : (
          <span className="pill pill-live">进行中</span>
        )}
        <span className="tool-chevron">{open ? "▾" : "▸"}</span>
      </button>
      {open ? (
        <div className="tool-body">
          <div className="tool-label">输入</div>
          <pre className="tool-pre">{asText(call.input)}</pre>
          {done ? (
            <>
              <div className="tool-label">{call.isError ? "错误" : "结果"}</div>
              <pre className="tool-pre">{asText(call.result)}</pre>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
