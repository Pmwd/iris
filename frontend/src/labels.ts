import type {
  FactKind,
  FactRole,
  FactScope,
  PermissionProfile,
  RoleId,
} from "./types";

export const ROLE_LABELS: Record<RoleId, string> = {
  coding: "Coding",
  scholar: "Scholar",
};

export const ROLE_DESCRIPTIONS: Record<RoleId, string> = {
  coding: "修改本地工作区代码、运行测试、交付改动。",
  scholar: "研究问题、区分事实/观点/假设、保留来源。",
};

export const PROFILE_LABELS: Record<PermissionProfile, string> = {
  read_only: "只读",
  edit: "编辑",
  execute: "执行/测试",
  research: "研究/联网",
};

export const PROFILE_HINTS: Record<PermissionProfile, string> = {
  read_only: "分析，不修改文件",
  edit: "修改文件，不执行命令",
  execute: "允许白名单 PowerShell",
  research: "允许 WebSearch / WebFetch",
};

export const FACT_KINDS: FactKind[] = [
  "preference",
  "decision",
  "constraint",
  "artifact",
  "insight",
  "open_question",
  "profile",
];

export const FACT_KIND_LABELS: Record<FactKind, string> = {
  preference: "偏好",
  decision: "决策",
  constraint: "约束",
  artifact: "产出/文件",
  insight: "洞察",
  open_question: "未决问题",
  profile: "用户档案",
};

export const FACT_KIND_HINTS: Record<FactKind, string> = {
  preference: "长期偏好或习惯",
  decision: "已确认的选择和理由",
  constraint: "必须遵守的限制",
  artifact: "重要文件、项目、路径",
  insight: "可复用的经验或结论",
  open_question: "尚未解决的问题",
  profile: "稳定的人物/身份信息",
};

export const FACT_SCOPE_LABELS: Record<FactScope, string> = {
  global: "全局",
  workspace: "工作区",
};

export const FACT_ROLE_LABELS: Record<FactRole, string> = {
  coding: "仅 Coding",
  scholar: "仅 Scholar",
  both: "两个角色",
};

export const FACT_STATUS_LABELS: Record<string, string> = {
  candidate: "候选",
  accepted: "已接受",
  rejected: "已拒绝",
  archived: "已归档",
  pending: "排队中",
  running: "运行中",
  succeeded: "成功",
  failed: "失败",
};

export const SESSION_STATUS_LABELS: Record<string, string> = {
  active: "进行中",
  ended: "已结束",
  archived: "已归档",
};

export const TURN_STATUS_LABELS: Record<string, string> = {
  starting: "启动中",
  running: "运行中",
  canceling: "取消中",
  succeeded: "完成",
  failed: "失败",
  canceled: "已取消",
  interrupted: "已中断",
};

export const PROCESS_STATUS_LABELS: Record<string, string> = {
  starting: "启动中",
  running: "运行中",
  stopping: "停止中",
  stopped: "已停止",
  failed: "启动失败",
};

export const STATUS_LABELS: Record<string, string> = {
  ...FACT_STATUS_LABELS,
  ...SESSION_STATUS_LABELS,
  ...TURN_STATUS_LABELS,
  ...PROCESS_STATUS_LABELS,
};

export const FACT_REASON_LABELS: Record<string, string> = {
  matched: "相关",
  pinned: "置顶",
  manual: "手动选择",
  budget: "超出预算",
  not_relevant: "未匹配",
};

export function roleHomePath(role: RoleId): string {
  return `/${role}`;
}

export function sessionPath(role: RoleId, sessionId: string): string {
  return `/${role}/${sessionId}`;
}
