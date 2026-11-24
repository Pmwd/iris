from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_eval_module():
    path = ROOT / "scripts" / "memory_eval.py"
    spec = importlib.util.spec_from_file_location("iris_memory_eval", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deterministic_memory_fixture_meets_baseline():
    module = _load_eval_module()
    fixture = json.loads(
        (ROOT / "backend/tests/fixtures/memory_eval.json").read_text(
            encoding="utf-8"
        )
    )
    report = module.run(fixture)
    summary = report["summary"]
    assert summary["recall"] >= 0.95
    assert summary["precision"] >= 0.95
    assert summary["abstain_accuracy"] >= 0.95
    assert summary["stale_injections"] == 0
    assert summary["false_injection_rate"] <= 0.05
