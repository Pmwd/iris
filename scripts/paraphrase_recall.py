"""Compare lexical recall before/after user-authored note aliases.

Read-only experiment in temporary databases; no real Iris data or model calls.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.db import Database
from app.repository import Repository
from app.services.retrieval import collect_candidates
from app.text import query_terms

CASES = [
    {
        "name": "control: mango allergy",
        "note_title": "饮食禁忌",
        "note": "对芒果严重过敏，任何含芒果的食品都不要。",
        "aliases": ["饮食禁忌", "安全", "聚会", "身体不适"],
        "task_title": "芒果过敏",
        "goal": "列出不能吃的水果。",
        "kind": "control",
    },
    {
        "name": "paraphrase: food safety",
        "note_title": "饮食禁忌",
        "note": "对芒果严重过敏，任何含芒果的食品都不要。",
        "aliases": ["饮食禁忌", "安全", "聚会", "身体不适"],
        "task_title": "聚会食物安全",
        "goal": "为聚会准备一份安全的食物，避免身体不适。",
        "kind": "paraphrase",
    },
    {
        "name": "control: full body",
        "note_title": "运动偏好",
        "note": "偏好全身锻炼，不做单一部位分化。",
        "aliases": ["复合动作", "杠铃", "力量训练"],
        "task_title": "全身训练",
        "goal": "安排三次训练。",
        "kind": "control",
    },
    {
        "name": "paraphrase: compound movements",
        "note_title": "运动偏好",
        "note": "偏好全身锻炼，不做单一部位分化。",
        "aliases": ["复合动作", "杠铃", "力量训练"],
        "task_title": "杠铃复合动作",
        "goal": "安排三次杠铃复合动作训练。",
        "kind": "paraphrase",
    },
    {
        "name": "control: prose romance",
        "note_title": "阅读偏好",
        "note": "喜欢文笔细腻、情感克制的言情小说。",
        "aliases": ["文字质量", "感情线", "好书"],
        "task_title": "文笔言情",
        "goal": "推荐三本书。",
        "kind": "control",
    },
    {
        "name": "paraphrase: writing quality",
        "note_title": "阅读偏好",
        "note": "喜欢文笔细腻、情感克制的言情小说。",
        "aliases": ["文字质量", "感情线", "好书"],
        "task_title": "文字质量和感情线",
        "goal": "推荐几本文字质量高、感情线写得好的书。",
        "kind": "paraphrase",
    },
    {
        "name": "control: csv header",
        "note_title": "导出约定",
        "note": "CSV 导出保留 date,category,amount,note 表头。",
        "aliases": ["表格", "输出", "支出记录", "日期", "分类"],
        "task_title": "CSV 表头",
        "goal": "确认导出格式。",
        "kind": "control",
    },
    {
        "name": "paraphrase: spreadsheet output",
        "note_title": "导出约定",
        "note": "CSV 导出保留 date,category,amount,note 表头。",
        "aliases": ["表格", "输出", "支出记录", "日期", "分类"],
        "task_title": "支出记录输出",
        "goal": "把支出记录输出成表格文件，带日期和分类列。",
        "kind": "paraphrase",
    },
    {
        "name": "control: fruit budget",
        "note_title": "预算偏好",
        "note": "水果采购预算控制在 60 元以内。",
        "aliases": ["少花钱", "采买", "控制金额"],
        "task_title": "水果预算",
        "goal": "控制采购金额。",
        "kind": "control",
    },
    {
        "name": "paraphrase: spend less",
        "note_title": "预算偏好",
        "note": "水果采购预算控制在 60 元以内。",
        "aliases": ["少花钱", "采买", "控制金额"],
        "task_title": "这次采买",
        "goal": "这次采买尽量少花钱。",
        "kind": "paraphrase",
    },
]


def run_case(case: dict, use_aliases: bool) -> dict:
    with tempfile.TemporaryDirectory(prefix="iris-paraphrase-") as temp:
        root = Path(temp)
        db = Database(root / "iris.db")
        db.init()
        repo = Repository(db)
        project = repo.create_project(
            case["name"], str(root / "workspace"), "temp experiment"
        )
        note = repo.create_global_note(
            case["note_title"],
            case["note"],
            status="accepted",
            aliases=case["aliases"] if use_aliases else [],
        )
        task = repo.create_task(project["id"], case["task_title"], case["goal"])
        query = f"{case['task_title']}\n{case['goal']}"
        search_hits = repo.search_global_notes(query)
        result = collect_candidates(repo, project, task, 16000)
        selected = {n["id"] for n in result["notes"] if n["recommended"]}
        return {
            **case,
            "mode": "aliases" if use_aliases else "plain",
            "terms": query_terms(query),
            "selected": note["id"] in selected,
            "reason": next(
                (n["reason"] for n in result["notes"] if n["id"] == note["id"]),
                None,
            ),
        }


def main() -> int:
    print("| Mode | Case | Search terms | Selected | Reason |")
    print("|---|---|---|---|---|")
    results = []
    for mode in (False, True):
        for case in CASES:
            item = run_case(case, mode)
            results.append(item)
            print(
                f"| {item['mode']} | {item['name']} | "
                f"{', '.join(item['terms'])} | "
                f"{'yes' if item['selected'] else 'no'} | {item['reason'] or '—'} |"
            )

    print()
    for mode in ("plain", "aliases"):
        controls = [
            r for r in results if r["mode"] == mode and r["kind"] == "control"
        ]
        paraphrases = [
            r for r in results if r["mode"] == mode and r["kind"] == "paraphrase"
        ]
        print(
            f"{mode.upper()}_CONTROL_RECALL",
            f"{sum(r['selected'] for r in controls)}/{len(controls)}",
        )
        print(
            f"{mode.upper()}_PARAPHRASE_RECALL",
            f"{sum(r['selected'] for r in paraphrases)}/{len(paraphrases)}",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
