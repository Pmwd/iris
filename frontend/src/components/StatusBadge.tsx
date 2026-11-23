import { STATUS_LABELS } from "../labels";

export function StatusBadge({
  status,
  label,
}: {
  status: string;
  label?: string;
}) {
  return (
    <span className={`badge badge-${status.replace(/_/g, "-")}`}>
      {label ?? STATUS_LABELS[status] ?? status}
    </span>
  );
}
