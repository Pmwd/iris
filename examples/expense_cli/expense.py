#!/usr/bin/env python3
"""A tiny stdlib-only expense tracker used as an Iris acceptance workspace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_DATA = Path("expenses.json")


def load_expenses(path: Path = DEFAULT_DATA) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_expenses(expenses: list[dict[str, Any]], path: Path = DEFAULT_DATA) -> None:
    path.write_text(json.dumps(expenses, indent=2), encoding="utf-8")


def add_expense(
    expenses: list[dict[str, Any]],
    amount: float,
    category: str,
    spent_on: str,
    note: str = "",
) -> list[dict[str, Any]]:
    expenses.append(
        {
            "amount": float(amount),
            "category": category,
            "date": spent_on,
            "note": note,
        }
    )
    return expenses


def format_expenses(expenses: list[dict[str, Any]]) -> str:
    lines = []
    for expense in expenses:
        note = f"  {expense['note']}" if expense.get("note") else ""
        lines.append(
            f"{expense['date']}  {expense['category']:<12} "
            f"{expense['amount']:>8.2f}{note}"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Track small personal expenses.")
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA,
        help="JSON data file (default: expenses.json)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("add", help="Add an expense")
    add.add_argument("amount", type=float)
    add.add_argument("category")
    add.add_argument("--date", default=None)
    add.add_argument("--note", default="")

    subparsers.add_parser("list", help="List expenses")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    expenses = load_expenses(args.data)

    if args.command == "add":
        spent_on = args.date or __import__("datetime").date.today().isoformat()
        add_expense(expenses, args.amount, args.category, spent_on, args.note)
        save_expenses(expenses, args.data)
        print(f"Added {args.amount:.2f} to {args.category}.")
        return 0

    if args.command == "list":
        print(format_expenses(expenses))
        return 0

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
