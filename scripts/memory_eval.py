"""Deterministic Memory 2.0 retrieval evaluation.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\memory_eval.py
    .\\.venv\\Scripts\\python.exe scripts\\memory_eval.py --out artifacts/memory-eval/results.json

This uses the real repository + ranking code against a throwaway SQLite DB and
the labeled fixture, so it is cheap enough to run in CI.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db import Database  # noqa: E402
from app.repository import Repository  # noqa: E402
from app.repository_facts import FactRepository  # noqa: E402
from app.services.facts import select_facts  # noqa: E402


def load_fixture(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run(fixture: dict, min_score: float = 0.55) -> dict:
    results = []
    with tempfile.TemporaryDirectory(prefix="iris-memory-eval-") as tmp:
        root = Path(tmp)
        database = Database(root / "iris.db")
        database.init()
        projects_repo = Repository(database)
        facts_repo = FactRepository(database)
        projects: dict[str, dict] = {}
        for key in ("A", "B"):
            workspace = root / f"ws-{key}"
            workspace.mkdir()
            projects[key] = projects_repo.create_project(
                f"Workspace {key}", str(workspace)
            )
        key_by_id: dict[str, str] = {}
        for item in fixture["facts"]:
            fact = facts_repo.create_fact(
                scope=item["scope"],
                project_id=projects[item["project"]]["id"] if item.get("project") else None,
                role=item["role"],
                kind=item["kind"],
                status="accepted",
                title=item["title"],
                content_md=item.get("content_md", ""),
                aliases=item.get("aliases") or [],
                tags=item.get("tags") or [],
                valid_until=item.get("valid_until"),
            )
            key_by_id[fact["id"]] = item["key"]

        for query in fixture["queries"]:
            project_id = (
                projects[query["project"]]["id"] if query.get("project") else None
            )
            selection = select_facts(
                facts_repo,
                role=query["role"],
                project_id=project_id,
                query=query["q"],
                budget_chars=4000,
                min_score=min_score,
                max_items=6,
            )
            selected = [key_by_id[item] for item in selection["selected_ids"]]
            expected = query.get("expect") or []
            absent = query.get("absent") or []
            results.append(
                {
                    "id": query["id"],
                    "q": query["q"],
                    "role": query["role"],
                    "project": query.get("project"),
                    "selected": selected,
                    "expected": expected,
                    "absent": absent,
                    "abstained": selection["abstained"],
                    "hits": len([key for key in selected if key in expected]),
                    "false_injections": [
                        key for key in selected if key not in expected
                    ],
                    "stale_injections": [key for key in selected if key in absent],
                    "top_score": selection["top_score"],
                    "threshold": selection["threshold"],
                }
            )

    expected_count = sum(len(item["expected"]) for item in results)
    hit_count = sum(item["hits"] for item in results)
    selected_count = sum(len(item["selected"]) for item in results)
    false_count = sum(len(item["false_injections"]) for item in results)
    stale_count = sum(len(item["stale_injections"]) for item in results)
    empty_queries = [item for item in results if not item["expected"]]
    abstain_correct = sum(1 for item in empty_queries if not item["selected"])
    summary = {
        "queries": len(results),
        "recall": round(hit_count / expected_count, 3) if expected_count else None,
        "precision": round(hit_count / selected_count, 3) if selected_count else 1.0,
        "false_injection_rate": round(false_count / selected_count, 3)
        if selected_count
        else 0.0,
        "abstain_accuracy": round(abstain_correct / len(empty_queries), 3)
        if empty_queries
        else None,
        "stale_injections": stale_count,
        "expected": expected_count,
        "selected": selected_count,
    }
    return {"summary": summary, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture",
        type=Path,
        default=ROOT / "backend/tests/fixtures/memory_eval.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "artifacts/memory-eval/results.json",
    )
    parser.add_argument("--min-score", type=float, default=0.55)
    args = parser.parse_args()
    fixture = load_fixture(args.fixture)
    report = run(fixture, min_score=args.min_score)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    for item in report["results"]:
        flag = "OK" if not item["false_injections"] and not item["stale_injections"] else "FAIL"
        if item["expected"] and not item["hits"]:
            flag = "MISS"
        print(
            f"{flag:4} {item['id']:3} selected={item['selected']} "
            f"expected={item['expected']} abstained={item['abstained']}"
        )
    print(f"report written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
