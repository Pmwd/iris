import type { Note } from "./types";

export const NOTE_KIND_LABELS: Record<Note["kind"], string> = {
  outcome: "任务结果",
  decision: "已确认选择",
  note: "普通说明",
  research: "研究笔记",
  goal: "长期目标",
  capability: "当前能力",
  blind_spot: "盲区 / 反复问题",
  progress: "阶段进展",
};

export const MENTOR_STATE_KINDS = [
  "goal",
  "capability",
  "blind_spot",
  "progress",
  "decision",
] as const;

export type MentorStateKind = (typeof MENTOR_STATE_KINDS)[number];
