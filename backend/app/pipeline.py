"""Blocks 5-8 wired together with the best measured configuration.

    prompt --(5) PromptAnalyzer--> QueryPlan --(6/7) Remarker--> RemarkerResult
           --(8) Finalizer--> FinalResult (summary, ranked items, conflicts, records)

Defaults (see report3 for the measurements behind them):
  5  decision graph incl. generated vocabulary, no model call (prompt_analysis.default_settings).
     On the unseen "blind 3" prompts the Gemini check (PROMPT_LLM=auto) and the Jina embedding
     step (PROMPT_EMBEDDINGS=jina) added no accuracy but 1.6-2.6 s per prompt
     (docs/prompt-analysis-report.html).
  6/7 lexical + embeddings, no reranker (the reranker added no accuracy).
  8  two parallel Gemini Flash-Lite calls (ranking check, summary) with code checks and a
     template fallback.

Keys: GEMINI_API_KEY_2 (preferred for the LLM calls) or API_KEY / GEMINI_API_KEY.
Embeddings use the first key; the index is built once per patient and cached.

CLI
  python -m app.pipeline "anaesthetist, pre-operative check before breast surgery" --patient <dir>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .contracts import QueryPlan, RemarkerResult
from .final_contracts import FinalResult, Lang
from .keywords import annotate
from .llm_client import GeminiClient, LLMClient, gemini_key, load_env_file
from .prompt_analysis import PromptAnalyzer, default_settings, make_default_analyzer
from .remarker import Remarker
from .summary import Finalizer
from .tree import DecisionTree

PROMPT_MODELS = ["gemini-3.5-flash", "gemini-flash-lite-latest"]
PROMPT_LLM_TIMEOUT_S = 4.0   # a slow prompt check falls back to the keyword plan


@dataclass
class PipelineResult:
    plan: QueryPlan
    remark: RemarkerResult
    final: FinalResult
    timings_ms: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"plan": self.plan.model_dump(mode="json"), "remark": self.remark.model_dump(mode="json"),
                "final": self.final.model_dump(mode="json"), "timings_ms": self.timings_ms}


def prompt_client() -> LLMClient | None:
    """Gemini for the prompt check; Flash first (measured best), Flash-Lite as backup."""
    from .summary import summary_keys
    keys = summary_keys()
    if not keys:
        return None
    c = GeminiClient(PROMPT_MODELS[0], api_key=keys[0])
    c.api_keys = keys  # rotate to the next key on a rate limit
    c.models = list(PROMPT_MODELS)
    return c


class Pipeline:
    def __init__(self, analyzer: PromptAnalyzer, remarker: Remarker, finalizer: Finalizer, patient: dict):
        self.analyzer = analyzer
        self.remarker = remarker
        self.finalizer = finalizer
        self.patient = patient

    @classmethod
    def from_env(cls, patient_dir: Path | str | None = None, use_llm: bool = True,
                 use_evidence: bool = True, wait_on_quota: bool = True) -> "Pipeline":
        load_env_file()
        patient_dir = Path(patient_dir or os.environ.get("PATIENT_DIR") or "")
        if not (patient_dir / "patient.json").exists():
            raise FileNotFoundError("Pass the patient folder (with patient.json and documents/) "
                                    "or set PATIENT_DIR.")
        tree = DecisionTree.load()
        # Block 5 default: graph + generated vocabulary, no model call (PROMPT_LLM=auto turns
        # the Gemini check back on; it added no accuracy on unseen prompts once the
        # generated vocabulary was in, see docs/prompt-analysis-report.html).
        client = prompt_client() if use_llm and default_settings()["llm"] != "off" else None
        analyzer = make_default_analyzer(tree, client)
        analyzer.timeout = PROMPT_LLM_TIMEOUT_S
        remarker = Remarker.for_patient(patient_dir, tree, evidence=use_evidence, wait_on_quota=wait_on_quota)
        finalizer = Finalizer.from_env() if use_llm else Finalizer(None, None)
        patient = json.loads((patient_dir / "patient.json").read_text(encoding="utf-8"))
        return cls(analyzer, remarker, finalizer, patient)

    def run(self, prompt: str, lang: Lang = "en") -> PipelineResult:
        t0 = time.perf_counter()
        plan = self.analyzer.analyse(prompt)
        t1 = time.perf_counter()
        rem = self.remarker.remark(plan)
        annotate(rem, getattr(self.remarker, "evidence", None), getattr(self.remarker, "tree", None),
                 getattr(getattr(self.remarker, "ix", None), "docs", None))
        t2 = time.perf_counter()
        final = self.finalizer.finalize(plan, rem, self.patient, lang)
        t3 = time.perf_counter()
        final.issues = list(dict.fromkeys(plan.issues + rem.issues + final.issues))
        return PipelineResult(plan, rem, final, {
            "prompt_analysis": round((t1 - t0) * 1000, 1), "remarker": round((t2 - t1) * 1000, 1),
            "final": round((t3 - t2) * 1000, 1), "total": round((t3 - t0) * 1000, 1)})


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.pipeline")
    ap.add_argument("prompt")
    ap.add_argument("--patient", type=Path, default=os.environ.get("PATIENT_DIR"))
    ap.add_argument("--lang", default="en", choices=["en", "de"])
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    t = time.perf_counter()
    pipe = Pipeline.from_env(args.patient, use_llm=not args.no_llm)
    load_ms = (time.perf_counter() - t) * 1000
    res = pipe.run(args.prompt, args.lang)
    if args.json:
        print(json.dumps(res.to_dict(), ensure_ascii=False, indent=1))
        return 0
    f = res.final
    print(f"{f.patient.name}, age {f.patient.age_at_as_of} as of {f.patient.as_of} | mode {f.mode} | "
          f"prompt via {res.plan.method}")
    for c in f.summary:
        print(f"  [{c.kind}] {c.text}")
    print("conflicts:", [c.explanation for c in f.conflicts] or "-")
    print("issues:", f.issues or "-")
    print(f"startup {load_ms:.0f} ms, timings {res.timings_ms}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
