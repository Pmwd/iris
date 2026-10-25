const LABELS: Record<string, string> = {
  ready: "就绪",
  running: "运行中",
  needs_review: "待审查",
  interrupted: "已中断",
  failed: "失败",
  canceled: "已取消",
  done: "已完成",
  starting: "启动中",
  canceling: "取消中",
  succeeded: "成功",
  draft: "草稿",
  accepted: "已接受",
  archived: "已归档",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`badge badge-${status}`}>{LABELS[status] ?? status}</span>
  );
}
