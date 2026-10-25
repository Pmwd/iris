export function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatCost(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `$${value.toFixed(4)}`;
}

export function formatDuration(start: string | null, end: string | null): string {
  if (!start) return "—";
  const startTime = new Date(start).getTime();
  const endTime = end ? new Date(end).getTime() : Date.now();
  const seconds = Math.max(0, Math.round((endTime - startTime) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

export function splitLines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function asText(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}
