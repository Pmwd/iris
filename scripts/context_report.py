"""Read-only report of context recommendations and actual run manifests.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\context_report.py --db data/iris.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path


def _loads(value: str | None) -> dict:
    if not value:
        return {}
    try:
        result = json.loads(value)
        return result if isinstance(result, dict) else {}
    except json.JSONDecodeError:
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize Iris context usage")
    parser.add_argument("--db", type=Path, default=Path("data/iris.db"))
    args = parser.parse_args()
    if not args.db.is_file():
        print(f"database not found: {args.db}")
        return 1

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        runs = conn.execute(
            """
            SELECT r.id, r.status, r.created_at, r.permission_profile,
                   r.context_manifest_json, r.result_text,
                   t.title AS task_title, p.name AS project_name
            FROM runs r
            JOIN tasks t ON t.id = r.task_id
            JOIN projects p ON p.id = t.project_id
            ORDER BY r.created_at DESC
            """
        ).fetchall()
        note_rows = conn.execute(
            """
            SELECT id, title, pinned, use_count, last_used_at, 'project' AS scope
            FROM notes
            UNION ALL
            SELECT id, title, pinned, use_count, last_used_at, 'global' AS scope
            FROM global_notes
            """
        ).fetchall()
    finally:
        conn.close()

    note_usage = {row["id"]: dict(row) for row in note_rows}
    reason_counts: Counter[str] = Counter()
    scope_counts: Counter[str] = Counter()
    selection_counts: Counter[str] = Counter()

    print("# Iris 上下文使用报告")
    print()
    print(f"数据库：`{args.db}`")
    print(f"运行数量：{len(runs)}")
    print()
    print("| 项目 / 任务 | 运行 | 模式 | 实际注入 | 推荐差异 | 估算 tokens |")
    print("|---|---|---|---|---|---|")
    for run in runs:
        manifest = _loads(run["context_manifest_json"])
        included = manifest.get("included_notes") or []
        recommended = set(manifest.get("recommended_note_ids") or [])
        included_ids = {note.get("id") for note in included}
        mode = manifest.get("selection_mode") or "phase1"
        selection_counts[mode] += 1
        added = len(included_ids - recommended) if recommended else 0
        removed = len(recommended - included_ids) if recommended else 0
        diff = []
        if added:
            diff.append(f"+{added}")
        if removed:
            diff.append(f"-{removed}")
        labels = []
        for note in included:
            scope = note.get("scope", "project")
            reason = note.get("reason") or "—"
            scope_counts[scope] += 1
            reason_counts[reason] += 1
            labels.append(f"{note.get('title')} [{scope}/{reason}]")
        tokens = manifest.get("estimated_tokens") or manifest.get("recommended_tokens") or "—"
        task_label = f"{run['project_name']} / {run['task_title']}"
        print(
            f"| {task_label} | {run['status']} `{run['created_at'][:16]}` | "
            f"{mode} | {'<br>'.join(labels) if labels else '—'} | "
            f"{' '.join(diff) or '—'} | {tokens} |"
        )

    print()
    print("## 汇总")
    print()
    print(f"- selection mode：{dict(selection_counts)}")
    print(f"- scope 使用：{dict(scope_counts)}")
    print(f"- reason 使用：{dict(reason_counts)}")
    print()
    print("## Note 使用次数")
    print()
    print("| Note | scope | 使用次数 | 最近使用 | 置顶 |")
    print("|---|---|---|---|---|")
    for note_id, item in sorted(
        note_usage.items(), key=lambda pair: -(pair[1].get("use_count") or 0)
    ):
        if not item.get("use_count"):
            continue
        print(
            f"| {item['title']} | {item.get('scope', 'project')} | "
            f"{item['use_count']} | {item.get('last_used_at') or '—'} | "
            f"{'是' if item.get('pinned') else '否'} |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
