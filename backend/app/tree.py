"""Block 5a: decision graph.

tree.yaml (human-editable) is compiled once into tree.compiled.json with integer indices.
At runtime one request takes three steps:

1. Match: one pass of an Aho-Corasick automaton over the normalised prompt finds role,
   task, context and concept phrases (EN and DE), plus items the prompt asks for.
   Words no phrase covers are reported as unaccounted, for the LLM step.
2. Activate: matched nodes get activation 1.0 (0.85 for typo matches). Activation spreads
   to ancestors (is-a, full strength) and along weighted `implies` edges (max-product).
3. Score: rules are hyperedges. A rule fires when all its nodes are active and gives each
   of its items priority weight x the weakest node activation. Rules are grouped by
   level = number of conditions; within a level the highest score wins and suppression
   wins over adding; a higher level overrides lower levels for the items it mentions.
   Item links then add one hop (e.g. anticoagulants -> coagulation). Explicitly asked
   items are always shown. Scores map to critical / high / normal; low scores drop out.

CLI
  python -m app.tree compile
  python -m app.tree explain "anaesthetist, pre-operative check before breast surgery"
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .contracts import Checklist, ChecklistEntry, Coverage, LocalizedText, NodeHit

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TREE_YAML = DATA_DIR / "tree.yaml"
TREE_COMPILED = DATA_DIR / "tree.compiled.json"

PRIORITIES = ("critical", "high", "normal")
PRIORITY_WEIGHT = {"critical": 1.0, "high": 0.7, "normal": 0.45}
THRESHOLDS = (("critical", 0.85), ("high", 0.6), ("normal", 0.4))
ASKED_SCORE = 0.75
FUZZY_ACTIVATION = 0.85
NODE_GROUPS = {"roles": "role", "tasks": "task", "context": "context", "concepts": "concept"}
ROOT_ROLE = "physician"
FUZZY_MIN_LEN = 5
FUZZY_MIN_RATIO = 0.86

# Words that carry no clinical meaning for the checklist (EN and DE, umlauts folded).
STOPWORDS = frozenset("""
a an the and or but of to in on at for from with without by as is are was were be been being am
i you he she it we they me him her his hers its our their them my your this that these those there here
who whom whose which what when where why how do does did done doing have has had having can could
will would shall should may might must not no yes also any all some each every other another such
than then so very just only about into over under again further once more most few both own same
too s t pt w eval patient patients pat person man woman mrs mr ms lady
please check checking look looking see show tell need needs want wants know give get got make
today tomorrow tonight yesterday now soon later next last week weeks month months year years day days
night morning evening afternoon hour hours minute minutes since ago am pm time date
january february march april may june july august september october november december spring summer
autumn winter
new old one two three four five first second third
planned planning plan scheduled schedule start starting started considering consider doing done
going ward hospital clinic stay visit home house won wont stop again
der die das den dem des ein eine einen einem einer eines und oder aber mit ohne von vom zu zum zur
im in am an auf aus bei nach vor fuer ueber unter ist sind war waren wird werden hat haben hatte
sie er es ich wir ihr ihre ihren ihrem sein seine seinem nimmt nehmen soll sollen kann koennen
muss bitte heute morgen gestern naechste naechsten woche monat jahr nacht uhr
patientin frau herr geplant geplante
after before left right high low hoch niedrig up down take takes taking took starts feels feel felt
seems run runs work works open offene offen wie seit zwei drei vier wochen tagen beim nach
dose doses function functions treatment treatments major minor medical local department
abnormal suspected suspicious sudden suddenly declining painless partial placing cleared
measurement measurements cycle cycles shift shifts reaction some into
intraoperative appointment review case problem problems history issue issues status result
results value values level levels whether if still already nur noch auch sehr wegen
care umstellung switch switching change changing sleep
""".split())

_DATEISH = re.compile(r"^\d+([.:/]\d+)*(h|am|pm)?$")


class TreeError(ValueError):
    """tree.yaml is inconsistent."""


# ---------------------------------------------------------------------------
# Text normalisation, shared by compile time and runtime
# ---------------------------------------------------------------------------
_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
_NON_WORD = re.compile(r"[^a-z0-9.]+")


def normalize(text: str) -> str:
    """Lower-case, fold umlauts and accents, turn punctuation into single spaces."""
    text = text.lower().translate(_FOLD)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _NON_WORD.sub(" ", text)
    text = re.sub(r"\.(?=\s|$)", " ", text)  # sentence dots, keep dots inside "st.p"
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Aho-Corasick automaton (pure Python, no dependency)
# ---------------------------------------------------------------------------
class Automaton:
    """Finds all patterns in one pass.

    By default a pattern must cover whole words. `open_end` lets it stop inside a word
    ("anaesthetist*"), `open_start` lets it begin inside a word ("*ectomy")."""

    def __init__(self) -> None:
        self.goto: list[dict[str, int]] = [{}]
        self.fail: list[int] = [0]
        self.out: list[list[int]] = [[]]
        self.patterns: list[tuple[str, bool, bool, object]] = []

    def add(self, pattern: str, open_end: bool, payload: object, open_start: bool = False) -> None:
        state = 0
        for ch in pattern:
            nxt = self.goto[state].get(ch)
            if nxt is None:
                nxt = len(self.goto)
                self.goto[state][ch] = nxt
                self.goto.append({})
                self.fail.append(0)
                self.out.append([])
            state = nxt
        self.out[state].append(len(self.patterns))
        self.patterns.append((pattern, open_end, open_start, payload))

    def build(self) -> None:
        queue = list(self.goto[0].values())
        i = 0
        while i < len(queue):
            state = queue[i]
            i += 1
            for ch, nxt in self.goto[state].items():
                queue.append(nxt)
                f = self.fail[state]
                while f and ch not in self.goto[f]:
                    f = self.fail[f]
                cand = self.goto[f].get(ch, 0)
                self.fail[nxt] = cand if cand != nxt else 0
                self.out[nxt] = self.out[nxt] + self.out[self.fail[nxt]]

    def find(self, text: str):
        """Yield (start, end, pattern_index) for matches that respect word boundaries."""
        state = 0
        n = len(text)
        for i, ch in enumerate(text):
            while state and ch not in self.goto[state]:
                state = self.fail[state]
            state = self.goto[state].get(ch, 0)
            for pid in self.out[state]:
                pattern, open_end, open_start, _ = self.patterns[pid]
                start = i - len(pattern) + 1
                end = i + 1
                if not open_start and start > 0 and text[start - 1] != " ":
                    continue
                if not open_end and end < n and text[end] != " ":
                    continue
                yield start, end, pid


# ---------------------------------------------------------------------------
# Compile
# ---------------------------------------------------------------------------
def _split_pattern(raw: str) -> tuple[str, bool, bool]:
    raw = raw.strip()
    open_end = raw.endswith("*")
    open_start = raw.startswith("*")
    return normalize(raw.strip("*")), open_end, open_start


GENERATED_FILES = ("aliases.yaml", "concepts.yaml")
GENERATED_MAX_WEIGHT = "high"  # machine-generated rules never mark an item critical


def _source_bytes(yaml_path: Path) -> bytes:
    """tree.yaml plus the reviewed machine-generated files, for change detection."""
    data = yaml_path.read_bytes()
    gen_dir = yaml_path.parent / "generated"
    for name in GENERATED_FILES:
        if (gen_dir / name).exists():
            data += b"\n#--" + name.encode() + b"\n" + (gen_dir / name).read_bytes()
    return data


def _merge_generated(spec: dict, gen_dir: Path) -> None:
    """Add machine-generated aliases and concepts. Hand-written entries always win:
    a generated phrase that already belongs to another node or item is skipped."""
    import yaml

    taken: dict[str, str] = {}
    for group in NODE_GROUPS:
        for nid, nd in (spec["nodes"].get(group) or {}).items():
            for raw in nd.get("match", []):
                taken.setdefault(normalize(str(raw).strip("*")), nid)
    for iid, it in spec["items"].items():
        for raw in it.get("ask", []) or []:
            taken.setdefault(normalize(str(raw).strip("*")), iid)

    def free(phrase: str, owner: str) -> bool:
        p = normalize(phrase)
        if not p or taken.get(p, owner) != owner:
            return False
        taken[p] = owner
        return True

    alias_file = gen_dir / "aliases.yaml"
    if alias_file.exists():
        aliases = yaml.safe_load(alias_file.read_text(encoding="utf-8")) or {}
        node_owner = {nid: nd for g in NODE_GROUPS for nid, nd in (spec["nodes"].get(g) or {}).items()}
        for eid, phrases in aliases.items():
            target = node_owner.get(eid)
            key = "match"
            if target is None and eid in spec["items"]:
                target, key = spec["items"][eid], "ask"
            if target is None:
                continue
            target[key] = list(target.get(key) or []) + [p for p in phrases if free(p, eid)]

    concept_file = gen_dir / "concepts.yaml"
    if concept_file.exists():
        concepts = yaml.safe_load(concept_file.read_text(encoding="utf-8")) or {}
        known = {nid for g in NODE_GROUPS for nid in (spec["nodes"].get(g) or {})}
        spec["nodes"].setdefault("concepts", {})
        cap = PRIORITIES.index(GENERATED_MAX_WEIGHT)
        for cid, c in concepts.items():
            if cid in known or cid in spec["items"]:
                continue
            match = [p for p in c.get("match", []) if free(p, cid)]
            if not match:
                continue
            label = c.get("label") or {}
            en = str(label.get("en") or cid.replace("_", " "))
            spec["nodes"]["concepts"][cid] = {
                "label": {"en": en, "de": str(label.get("de") or en)}, "match": match,
                "implies": {k: v for k, v in (c.get("implies") or {}).items() if k in known},
            }
            rule = {"id": f"gen_{cid}", "when": [cid], "sources": ["generated"]}
            seen = set()
            for i, p in enumerate(PRIORITIES):
                level = PRIORITIES[max(i, cap)]
                ids = [x for x in c.get(p, []) or [] if x in spec["items"] and x not in seen]
                seen.update(ids)
                rule[level] = rule.get(level, []) + ids
            spec["rules"].append(rule)


def compile_tree(yaml_path: Path = TREE_YAML, out_path: Path = TREE_COMPILED,
                 use_generated: bool = True) -> dict:
    import yaml  # only needed at compile time

    source = _source_bytes(yaml_path) if use_generated else yaml_path.read_bytes()
    spec = yaml.safe_load(yaml_path.read_bytes())
    if use_generated:
        _merge_generated(spec, yaml_path.parent / "generated")
    errors: list[str] = []

    item_ids = list(spec["items"])
    item_index = {iid: i for i, iid in enumerate(item_ids)}
    domains = set(spec["domains"])
    items = []
    for iid in item_ids:
        it = spec["items"][iid]
        for d in it.get("domains", []):
            if d not in domains:
                errors.append(f"item {iid}: unknown domain {d}")
        if it.get("time_rule") not in ("current", "latest", "history"):
            errors.append(f"item {iid}: bad time_rule {it.get('time_rule')}")
        items.append({
            "id": iid, "label": it["label"], "question": it["question"],
            "domains": it.get("domains", []), "filters": it.get("filters", {}),
            "time_rule": it["time_rule"], "terms": it.get("terms", {}),
            "codes": it.get("codes", {}), "sources": it.get("sources", []),
        })

    nodes: list[dict] = []
    node_index: dict[str, int] = {}
    for group, kind in NODE_GROUPS.items():
        for nid, nd in (spec["nodes"].get(group) or {}).items():
            if nid in node_index or nid in item_index:
                errors.append(f"duplicate id {nid}")
            node_index[nid] = len(nodes)
            nodes.append({"id": nid, "kind": kind, "label": nd["label"],
                          "parent": nd.get("parent"), "implies": nd.get("implies") or {},
                          "match": nd.get("match", [])})
    for nd in nodes:
        if nd["parent"] and nd["parent"] not in node_index:
            errors.append(f"node {nd['id']}: unknown parent {nd['parent']}")
        for target, w in nd["implies"].items():
            if target not in node_index:
                errors.append(f"node {nd['id']}: implies unknown node {target}")
            if not 0 < w <= 1:
                errors.append(f"node {nd['id']}: implies weight {w} not in (0, 1]")
    # parent chains must be acyclic
    for nd in nodes:
        seen, p = {nd["id"]}, nd["parent"]
        while p:
            if p in seen:
                errors.append(f"cycle in parents at {nd['id']}")
                break
            seen.add(p)
            p = nodes[node_index[p]]["parent"] if p in node_index else None

    rules = []
    for order, r in enumerate(spec["rules"]):
        rid = r["id"]
        when = []
        for nid in r["when"]:
            if nid not in node_index:
                errors.append(f"rule {rid}: unknown node {nid}")
            else:
                when.append(node_index[nid])
        weights: dict[int, float] = {}
        for p in PRIORITIES:
            for iid in r.get(p, []) or []:
                if iid not in item_index:
                    errors.append(f"rule {rid}: unknown item {iid}")
                elif item_index[iid] in weights:
                    errors.append(f"rule {rid}: item {iid} listed twice")
                else:
                    weights[item_index[iid]] = PRIORITY_WEIGHT[p]
        suppress = []
        for iid in r.get("suppress", []) or []:
            if iid not in item_index:
                errors.append(f"rule {rid}: unknown item {iid}")
            elif item_index[iid] in weights:
                errors.append(f"rule {rid}: item {iid} both added and suppressed")
            else:
                suppress.append(item_index[iid])
        rules.append({"id": rid, "level": len(when), "order": order, "when": when,
                      "weights": {str(k): v for k, v in weights.items()},
                      "suppress": suppress, "note": r.get("note", ""),
                      "sources": r.get("sources", [])})
    rules.sort(key=lambda r: (r["level"], r["order"]))
    if len({r["id"] for r in rules}) != len(rules):
        errors.append("duplicate rule ids")

    links = []
    for entry in spec.get("links", []) or []:
        a, b, w = entry
        if a not in item_index or b not in item_index:
            errors.append(f"link {a} -> {b}: unknown item")
        elif not 0 < w <= 1:
            errors.append(f"link {a} -> {b}: weight {w} not in (0, 1]")
        else:
            links.append([item_index[a], item_index[b], w])

    patterns = []
    for i, nd in enumerate(nodes):
        for raw in nd.pop("match"):
            pat, open_end, open_start = _split_pattern(str(raw))
            if pat:
                patterns.append([pat, open_end, open_start, "node", i])
        nd["parent"] = node_index.get(nd["parent"]) if nd["parent"] else None
        nd["implies"] = [[node_index[t], w] for t, w in nd["implies"].items() if t in node_index]
    for iid in item_ids:
        for raw in spec["items"][iid].get("ask", []) or []:
            pat, open_end, open_start = _split_pattern(str(raw))
            if pat:
                patterns.append([pat, open_end, open_start, "item", item_index[iid]])

    if errors:
        raise TreeError("tree.yaml has errors:\n  " + "\n  ".join(errors))

    compiled = {
        "version": spec.get("version", 2),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "items": items, "nodes": nodes, "rules": rules, "links": links, "patterns": patterns,
    }
    out_path.write_text(json.dumps(compiled, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
    return compiled


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
@dataclass
class _Rule:
    id: str
    level: int
    when: tuple[int, ...]
    weights: dict[int, float]
    suppress: tuple[int, ...]


@dataclass
class PromptMatch:
    activation: dict[int, float] = field(default_factory=dict)  # node -> activation
    source: dict[int, str] = field(default_factory=dict)        # node -> prompt / fuzzy
    words: dict[int, list[str]] = field(default_factory=dict)   # node -> matched words
    asked_items: set[int] = field(default_factory=set)
    coverage: Coverage = field(default_factory=lambda: Coverage(content_words=0, accounted_words=0, unaccounted=[]))


class DecisionTree:
    def __init__(self, compiled: dict) -> None:
        self.source_sha256 = compiled.get("source_sha256", "")
        self.items = compiled["items"]
        self.nodes = compiled["nodes"]
        self.node_index = {n["id"]: i for i, n in enumerate(self.nodes)}
        self.item_index = {it["id"]: i for i, it in enumerate(self.items)}
        self.parent_of = {n["id"]: (self.nodes[n["parent"]]["id"] if n["parent"] is not None else None)
                          for n in self.nodes}
        self.rules = [_Rule(r["id"], r["level"], tuple(r["when"]),
                            {int(k): v for k, v in r["weights"].items()}, tuple(r["suppress"]))
                      for r in compiled["rules"]]
        self.links: dict[int, list[tuple[int, float]]] = {}
        for a, b, w in compiled["links"]:
            self.links.setdefault(a, []).append((b, w))
        self.automaton = Automaton()
        self._fuzzy_vocab: dict[str, list[int]] = {}
        for pat, open_end, open_start, kind, idx in compiled["patterns"]:
            self.automaton.add(pat, open_end, (kind, idx), open_start)
            if kind == "node" and " " not in pat and len(pat) >= FUZZY_MIN_LEN and not open_start:
                self._fuzzy_vocab.setdefault(pat, []).append(idx)
        self.automaton.build()
        self._fuzzy_words = list(self._fuzzy_vocab)

    # --- loading -----------------------------------------------------------
    @classmethod
    def load(cls, yaml_path: Path = TREE_YAML, compiled_path: Path = TREE_COMPILED) -> "DecisionTree":
        """Load the compiled graph; recompile when tree.yaml changed since the last compile."""
        compiled = None
        if compiled_path.exists():
            compiled = json.loads(compiled_path.read_text(encoding="utf-8"))
            if yaml_path.exists():
                sha = hashlib.sha256(_source_bytes(yaml_path)).hexdigest()
                if sha != compiled.get("source_sha256"):
                    compiled = None
        if compiled is None:
            compiled = compile_tree(yaml_path, compiled_path)
        return cls(compiled)

    # --- catalogue for the LLM step -------------------------------------------
    def catalogue(self) -> dict[str, list[tuple[str, str]]]:
        out: dict[str, list[tuple[str, str]]] = {"role": [], "task": [], "context": [], "concept": [], "item": []}
        for n in self.nodes:
            out[n["kind"]].append((n["id"], n["label"]["en"]))
        for it in self.items:
            out["item"].append((it["id"], it["label"]["en"]))
        return out

    # --- step 1: match -----------------------------------------------------------
    def match(self, prompt: str) -> PromptMatch:
        text = normalize(prompt)
        result = PromptMatch()
        covered = [False] * len(text)
        for start, end, pid in self.automaton.find(text):
            _, _, _, (kind, idx) = self.automaton.patterns[pid]
            if kind == "node":
                result.activation[idx] = 1.0
                result.source[idx] = "prompt"
                result.words.setdefault(idx, []).append(text[start:end])
            else:
                result.asked_items.add(idx)
            for k in range(start, end):
                covered[k] = True

        content = accounted = 0
        unaccounted: list[str] = []
        pos = 0
        for word in text.split(" "):
            start, pos = pos, pos + len(word) + 1
            if not word or word in STOPWORDS or _DATEISH.match(word) or len(word) < 2:
                continue
            content += 1
            if any(covered[start:start + len(word)]):
                accounted += 1
                continue
            close = (difflib.get_close_matches(word, self._fuzzy_words, n=1, cutoff=FUZZY_MIN_RATIO)
                     if len(word) >= FUZZY_MIN_LEN else [])
            if close:
                accounted += 1
                for idx in self._fuzzy_vocab[close[0]]:
                    if result.activation.get(idx, 0) < FUZZY_ACTIVATION:
                        result.activation[idx] = FUZZY_ACTIVATION
                        result.source[idx] = "fuzzy"
                    result.words.setdefault(idx, []).append(word)
            elif word not in unaccounted:
                unaccounted.append(word)
        result.coverage = Coverage(content_words=content, accounted_words=accounted, unaccounted=unaccounted)
        return result

    # --- step 2: activate ---------------------------------------------------------
    def activate(self, seeds: dict[int, float]) -> tuple[dict[int, float], dict[int, str]]:
        """Spread activation over is-a (full) and implies (weighted) edges."""
        act = dict(seeds)
        how: dict[int, str] = {}
        if not any(self.nodes[i]["kind"] == "role" for i in act):
            act[self.node_index[ROOT_ROLE]] = 1.0
            how[self.node_index[ROOT_ROLE]] = "default"
        queue = list(act)
        while queue:
            i = queue.pop()
            a = act[i]
            nd = self.nodes[i]
            edges = list(nd["implies"])
            if nd["parent"] is not None:
                edges.append((nd["parent"], 1.0))
            for j, w in edges:
                cand = a * w
                if cand > act.get(j, 0) + 1e-9:
                    act[j] = cand
                    how[j] = "ancestor" if j == nd["parent"] else "implied"
                    queue.append(j)
        return act, how

    # --- step 3: score -------------------------------------------------------------
    def score(self, act: dict[int, float], asked: dict[int, float] | None = None,
              asked_reason: dict[int, str] | None = None) -> Checklist:
        """`asked`: items requested outside the rules (prompt or LLM), with their score.
        They override suppression only when the prompt asked (reason 'asked')."""
        scores: dict[int, float] = {}
        suppressed: set[int] = set()
        reasons: dict[int, list[str]] = {}

        level, applied = None, []
        for rule in self.rules + [None]:
            if rule is None or rule.level != level:
                if applied:
                    lvl_score: dict[int, float] = {}
                    lvl_sup: set[int] = set()
                    lvl_reason: dict[int, list[str]] = {}
                    for r, strength in applied:
                        for it, w in r.weights.items():
                            s = w * strength
                            if s > lvl_score.get(it, 0):
                                lvl_score[it] = s
                            lvl_reason.setdefault(it, []).append(r.id)
                        for it in r.suppress:
                            lvl_sup.add(it)
                            lvl_reason.setdefault(it, []).append(r.id)
                    for it, rs in lvl_reason.items():  # higher level overrides
                        reasons[it] = rs
                        if it in lvl_sup:
                            suppressed.add(it)
                            scores.pop(it, None)
                        else:
                            suppressed.discard(it)
                            scores[it] = lvl_score[it]
                if rule is None:
                    break
                level, applied = rule.level, []
            strength = min((act.get(n, 0.0) for n in rule.when), default=0.0)
            if strength > 0:
                applied.append((rule, strength))

        boosts: dict[int, tuple[float, int]] = {}
        for src, s in scores.items():  # one hop over item links
            for dst, w in self.links.get(src, ()):
                cand = s * w
                if dst not in suppressed and cand > scores.get(dst, 0) and cand > boosts.get(dst, (0, 0))[0]:
                    boosts[dst] = (cand, src)
        for dst, (cand, src) in boosts.items():
            scores[dst] = cand
            reasons.setdefault(dst, []).append(f"link:{self.items[src]['id']}")

        for it, s in (asked or {}).items():
            why = (asked_reason or {}).get(it, "asked")
            if it in suppressed:
                if why != "asked":
                    continue  # an expert suppression beats an LLM suggestion
                suppressed.discard(it)
            if s > scores.get(it, 0):
                scores[it] = s
            reasons.setdefault(it, []).append(why)

        entries = []
        for it, s in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0])):
            priority = next((p for p, t in THRESHOLDS if s >= t - 1e-9), None)
            if priority is None:
                continue
            item = self.items[it]
            entries.append(ChecklistEntry(
                item_id=item["id"], label=LocalizedText(**item["label"]), question=item["question"],
                priority=priority, score=round(s, 3), domains=item["domains"],
                filters=item["filters"], time_rule=item["time_rule"],
                terms={k: list(v) for k, v in item["terms"].items()}, codes=item["codes"],
                reasons=reasons.get(it, []),
            ))
        return Checklist(entries=entries,
                         suppressed=[self.items[i]["id"] for i in sorted(suppressed)])

    # --- convenience -----------------------------------------------------------------
    def hits(self, act: dict[int, float], how: dict[int, str], m: PromptMatch,
             llm_nodes: set[int] = frozenset()) -> list[NodeHit]:
        out = []
        for i, a in sorted(act.items(), key=lambda kv: (-kv[1], kv[0])):
            source = ("llm" if i in llm_nodes else m.source.get(i) or how.get(i, "implied"))
            out.append(NodeHit(node_id=self.nodes[i]["id"], kind=self.nodes[i]["kind"],
                               activation=round(a, 3), source=source,
                               matched=sorted(set(m.words.get(i, [])))))
        return out

    def plan(self, prompt: str) -> tuple[list[NodeHit], Checklist, Coverage]:
        """Keyword path only: prompt -> active nodes, checklist, coverage."""
        m = self.match(prompt)
        act, how = self.activate(m.activation)
        checklist = self.score(act, {i: ASKED_SCORE for i in m.asked_items})
        return self.hits(act, how, m), checklist, m.coverage


def _main(argv: list[str]) -> int:
    if argv[:1] == ["compile"]:
        t = time.perf_counter()
        c = compile_tree()
        print(f"compiled {len(c['items'])} items, {len(c['nodes'])} nodes, {len(c['rules'])} rules, "
              f"{len(c['links'])} links, {len(c['patterns'])} patterns "
              f"in {(time.perf_counter() - t) * 1000:.1f} ms -> {TREE_COMPILED.name}")
        return 0
    if argv[:1] == ["explain"] and len(argv) > 1:
        t = time.perf_counter()
        tree = DecisionTree.load()
        t_load = time.perf_counter() - t
        t = time.perf_counter()
        hits, checklist, coverage = tree.plan(" ".join(argv[1:]))
        t_plan = time.perf_counter() - t
        print("nodes:", ", ".join(f"{h.node_id}({h.activation:.2f},{h.source})" for h in hits))
        for e in checklist.entries:
            print(f"  {e.priority:<8} {e.score:.2f} {e.item_id:<28} <- {', '.join(e.reasons)}")
        if checklist.suppressed:
            print("suppressed:", ", ".join(checklist.suppressed))
        print(f"coverage {coverage.accounted_words}/{coverage.content_words}, "
              f"unaccounted: {coverage.unaccounted or '-'}")
        print(f"load {t_load * 1000:.1f} ms, plan {t_plan * 1000:.2f} ms")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
