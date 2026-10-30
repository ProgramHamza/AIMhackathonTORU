"""Evaluation prompts: eval/cases.yaml plus, when present, eval/private/challenge-cases.yaml.

The challenge situations (D01-D05) quote the challenge dataset, so they live in the gitignored
private file; without it the evaluation runs on the public prompts only.
"""
from __future__ import annotations

from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
PRIVATE = HERE / "private" / "challenge-cases.yaml"


def load_cases(path: Path = HERE / "cases.yaml") -> list[dict]:
    cases = yaml.safe_load(path.read_text(encoding="utf-8"))["cases"]
    if PRIVATE.is_file():
        cases = yaml.safe_load(PRIVATE.read_text(encoding="utf-8"))["cases"] + cases
    return cases
