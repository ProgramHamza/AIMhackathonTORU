"""Calibrate the embedding-match threshold for one embedder.

Uses phrases that occur in no test prompt: clinical phrasings the graph does not contain
verbatim (should link to a graph alias) and everyday words (should not link). Prints the
nearest alias and similarity for each, and the threshold range that separates them.

Usage (from backend/):  python -m eval.calibrate_semantic --provider jina
"""
from __future__ import annotations

import argparse
import time

from app.embeddings import make_embedder
from app.semantic import TASK, SemanticLinker
from app.tree import DecisionTree

CLINICAL = [
    "bed sore", "hyperkalaemia", "low sodium", "renal colic", "blood in urine", "stomach bleed",
    "chest tightness", "fainting spell", "heart failure swelling", "shortness of breath on exertion",
    "water tablets", "blood sugar too low", "blutverdünnung", "nierenschwäche", "atemnot bei belastung",
    "herzschwäche", "zuckerkrankheit", "wassereinlagerung", "pacemaker check", "kidney failure",
    "medicines",
]
EVERYDAY = [
    "holiday", "tuesday", "kitchen", "football", "computer", "garden", "uses", "machine", "risk",
    "phone call", "weather", "letter", "parking", "colleague", "yesterday evening",
    "nachbar", "urlaub", "einkaufen", "wochenende",
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default=None, help="jina | gemini")
    args = ap.parse_args(argv)
    tree = DecisionTree.load()
    linker = SemanticLinker(tree, make_embedder(args.provider), threshold=0.0)
    t = time.perf_counter()
    linker.build()
    print(f"index: {len(linker.aliases)} aliases, {time.perf_counter() - t:.1f} s, "
          f"model {linker.embedder.model}")
    best = {}
    for name, group in (("clinical", CLINICAL), ("everyday", EVERYDAY)):
        t = time.perf_counter()
        q = linker.embedder.embed(group, TASK)
        ms = (time.perf_counter() - t) * 1000
        sims = q @ linker._matrix.T
        print(f"\n{name} ({ms:.0f} ms for {len(group)} phrases)")
        vals = []
        for i, p in enumerate(group):
            j = int(sims[i].argmax())
            vals.append(float(sims[i, j]))
            print(f"  {p:32} -> {linker.aliases[j]:32} {sims[i, j]:.3f}")
        best[name] = sorted(vals)
    lo = max(best["everyday"])
    print(f"\nhighest everyday similarity: {lo:.3f}")
    for thr in (lo + 0.01, lo + 0.03, lo + 0.05):
        hit = sum(v >= thr for v in best["clinical"])
        print(f"threshold {thr:.3f}: clinical phrases linked {hit}/{len(CLINICAL)}, everyday linked 0")


if __name__ == "__main__":
    main()
