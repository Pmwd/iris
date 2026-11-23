"""Read-only report of Iris session turns, summaries, and fact injection.

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
    parser = argparse.ArgumentParser(description="Summarize Iris session memory usage")
    parser.add_argument("--db", type=Path, default=Path("data/iris.db"))
    args = parser.parse_args()
    if not args.db.is_file():
        print(f"database not found: {args.db}")
        return 1

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        turns = conn.execute(
            """
            SELECT t.id, t.seq, t.status, t.mode, t.permission_profile,
                   t.context_manifest_json, t.created_at,
                   s.title AS session_title, s.role AS role,
                   p.name AS workspace_name
            FROM turns t
            JOIN sessions s ON s.id = t.session_id
            LEFT JOIN projects p ON p.id = s.project_id
            ORDER BY t.created_at DESC
            """
        ).fetchall()
        summaries = conn.execute(
            """
            SELECT status, kind, COUNT(*) AS n
            FROM session_summaries
            GROUP BY status, kind
            """
        ).fetchall()
        facts = conn.execute(
            """
            SELECT id, title, scope, kind, status, pinned, use_count, last_used_at
            FROM facts
            ORDER BY use_count DESC, updated_at DESC
            """
        ).fetchall()
    finally:
        conn.close()

    reason_counts: Counter[str] = Counter()
    scope_counts: Counter[str] = Counter()
    mode_counts: Counter[str] = Counter()

    print("# Iris 会话与记忆报告")
    print()
    print(f"数据库：`{args.db}`")
    print(f"Turn 数量：{len(turns)}")
    print()

    if turns:
        print("| 会话 / 工作区 | 角色 | # | 模式 | 状态 | 注入事实 | Summary | Tokens |")
        print("|---|---|---|---|---|---|---|---|")
        for turn in turns:
            manifest = _loads(turn["context_manifest_json"])
            mode = turn["mode"]
            mode_counts[mode] += 1
            labels = []
            for fact in manifest.get("included_facts") or []:
                scope = fact.get("scope", "global")
                reason = fact.get("reason") or "—"
                scope_counts[scope] += 1
                reason_counts[reason] += 1
                labels.append(f"{fact.get('title')} [{scope}/{reason}]")
            workspace = turn["workspace_name"] or "无工作区"
            session_label = f"{turn['session_title']} / {workspace}"
            tokens = manifest.get("estimated_tokens") or "—"
            print(
                f"| {session_label} | {turn['role']} | {turn['seq']} | "
                f"{mode} | {turn['status']} | "
                f"{'<br>'.join(labels) if labels else '—'} | "
                f"{'是' if manifest.get('summary_included') else '否'} | {tokens} |"
            )
    else:
        print("尚无 Session Turn。")

    print()
    print("## 汇总")
    print()
    print(f"- Turn 模式：{dict(mode_counts)}")
    print(f"- 注入事实 scope：{dict(scope_counts)}")
    print(f"- 注入 reason：{dict(reason_counts)}")
    print("- 摘要状态：" + (
        ", ".join(
            f"{row['status']}/{row['kind']}={row['n']}" for row in summaries
        )
        or "无"
    ))
    print()

    print("## 事实使用次数")
    print()
    if not facts:
        print("尚无长期事实。")
        return 0
    print("| 事实 | scope | kind | 状态 | 使用次数 | 最近使用 | 置顶 |")
    print("|---|---|---|---|---|---|---|")
    for fact in facts:
        print(
            f"| {fact['title']} | {fact['scope']} | {fact['kind']} | "
            f"{fact['status']} | {fact['use_count']} | "
            f"{fact['last_used_at'] or '—'} | {'是' if fact['pinned'] else '否'} |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
