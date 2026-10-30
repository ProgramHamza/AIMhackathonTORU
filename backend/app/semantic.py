"""Block 5c: embedding fallback for prompt words the graph does not know.

Alias-based retrieval (the SapBERT / BioELX idea): every phrase the graph matches, plus the
English and German labels, is embedded once and cached. At query time only the unknown
words (and pairs of adjacent unknown words) are embedded, in one batched call, and each is
linked to the nearest alias if the cosine similarity clears a threshold. Linked words
activate their node (or ask for their item) with a weight below an exact keyword match.

Typical cost: one embedding request (~0.2-0.5 s) instead of an LLM call (~1.5-2 s), and
only when the keyword graph left something unaccounted for.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .embeddings import EmbeddingError, make_embedder
from .tree import DecisionTree, normalize

TASK = "SEMANTIC_SIMILARITY"
DEFAULT_THRESHOLD = 0.80
# Per embedder class, from eval/calibrate_semantic.py (phrases not in any test prompt).
THRESHOLDS: dict[str, float] = {"JinaEmbedder": 0.80}
NODE_ACTIVATION_CAP = 0.85
ITEM_SCORE = 0.7


@dataclass
class SemanticLink:
    phrase: str        # the unknown prompt phrase
    alias: str         # the graph phrase it matched
    target_kind: str   # "node" or "item"
    target: int        # node or item index
    similarity: float


class SemanticLinker:
    def __init__(self, tree: DecisionTree, embedder=None,
                 threshold: float = DEFAULT_THRESHOLD) -> None:
        self.tree = tree
        self.embedder = embedder or make_embedder()
        self.threshold = threshold
        phrases: dict[str, tuple[str, int]] = {}
        # Roles are left to keywords and the LLM: phrases like "phone call" sit too close to
        # role phrases like "on call" (calibration), and a wrong role changes the whole checklist.
        for pat, _, _, (kind, idx) in tree.automaton.patterns:
            if kind == "node" and tree.nodes[idx]["kind"] == "role":
                continue
            if len(pat) >= 3:
                phrases.setdefault(pat, (kind, idx))
        for i, n in enumerate(tree.nodes):
            if n["kind"] == "role":
                continue
            for label in n["label"].values():
                if isinstance(label, str) and label:
                    phrases.setdefault(normalize(label), ("node", i))
        for i, it in enumerate(tree.items):
            for label in it["label"].values():
                if isinstance(label, str) and label:
                    phrases.setdefault(normalize(label), ("item", i))
        self.aliases = list(phrases)
        self.targets = [phrases[a] for a in self.aliases]
        self._matrix: np.ndarray | None = None

    def build(self) -> None:
        """Embed all aliases (cached on disk after the first run)."""
        if self._matrix is None:
            self._matrix = self.embedder.embed(self.aliases, TASK, wait_on_quota=True)

    @staticmethod
    def candidates(unaccounted: list[str]) -> list[str]:
        """Unknown words, plus adjacent pairs ("pressure sore", "black stools")."""
        words = [w for w in unaccounted if len(w) >= 3]
        pairs = [f"{a} {b}" for a, b in zip(unaccounted, unaccounted[1:])]
        return list(dict.fromkeys(pairs + words))

    def link(self, unaccounted: list[str]) -> list[SemanticLink]:
        cands = self.candidates(unaccounted)
        if not cands:
            return []
        self.build()
        q = self.embedder.embed(cands, TASK)
        sims = q @ self._matrix.T
        links = []
        covered: set[str] = set()
        for ci in np.argsort(-sims.max(axis=1)):  # strongest first; pairs cover their words
            phrase = cands[ci]
            words = set(phrase.split())
            if words <= covered:
                continue
            j = int(np.argmax(sims[ci]))
            s = float(sims[ci, j])
            if s < self.threshold:
                continue
            kind, idx = self.targets[j]
            links.append(SemanticLink(phrase, self.aliases[j], kind, idx, round(s, 3)))
            covered |= words
        return links


def make_linker(tree: DecisionTree, threshold: float | None = None,
                provider: str | None = None) -> SemanticLinker | None:
    """A linker for the configured embedder, or None when no embedding key is configured."""
    try:
        embedder = make_embedder(provider)
    except EmbeddingError:
        return None
    if threshold is None:
        threshold = THRESHOLDS.get(type(embedder).__name__, DEFAULT_THRESHOLD)
    return SemanticLinker(tree, embedder, threshold=threshold)
