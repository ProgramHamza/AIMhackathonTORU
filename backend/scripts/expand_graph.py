"""Offline: distil LLM knowledge into the decision graph (run once, then review).

Two outputs, both machine-generated and kept apart from the hand-written tree.yaml:

  data/generated/aliases.yaml   more phrases per existing node and item: German and English
                                synonyms, lay terms, abbreviations, brand names
  data/generated/concepts.yaml  common clinical concepts the graph lacks (symptoms,
                                conditions, procedures, drug classes, devices, lab findings),
                                each with match phrases, implied nodes and checklist items

The compiler merges them into the graph, so at query time they cost nothing. Everything the
model returns is validated against the graph (unknown IDs dropped, generic words dropped,
role aliases must name a person). Review the files before relying on them clinically.

Usage (from backend/):  python -m scripts.expand_graph [--aliases] [--concepts]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.llm_client import GeminiClient, LLMError, load_env_file  # noqa: E402
from app.tree import STOPWORDS, TREE_YAML, normalize  # noqa: E402

OUT_DIR = ROOT / "data" / "generated"
BATCH = 12
PAUSE_S = 4.0  # stay under free-tier request limits
PERSON = re.compile(r"(doctor|physician|surgeon|nurse|specialist|consultant|registrar|resident|"
                    r"therapist|pharmacist|midwife|ist$|ists$|ician|iatrist|loge$|login$|arzt|aerztin|"
                    r"mediziner|chirurg|pfleger|schwester|apotheker|hebamme|team|clinic|ambulanz|dienst)")

ALIAS_SYSTEM = """\
You extend the vocabulary of a clinical decision graph. Clinicians type short requests in
English or German, e.g. "anaesthetist, pre-op check before breast surgery" or
"Hausärztin: Kontrolle Blutdruck". For each entry you get its ID, label and the phrases it
already matches. Add the other ways clinicians write the same thing:
- English and German synonyms, including Austrian and Swiss usage
- abbreviations and acronyms used on wards (both languages)
- lay terms patients or nurses use
- for drug entries: common generic and brand names
Rules: lower case; 1 to 4 words per phrase; no phrase that is generic outside medicine
(not "check", "review", "test", "patient", "doctor" alone); at most 12 new phrases per entry;
do not repeat phrases already listed. For role entries, every phrase must name a person or
profession (e.g. "heart doctor", "kardiologin"), never a body part or disease alone.
"""

CONCEPT_SYSTEM = """\
You extend a clinical decision graph used to decide which facts from a patient's record a
clinician needs. Each concept you add is something clinicians mention in a short request
(symptom, condition, procedure, drug class, device, lab finding). For each concept give:
- id: snake_case
- label_en, label_de
- match: 3 to 12 phrases in English and German as clinicians write them (lower case, 1 to 4
  words; include abbreviations, lay terms, common drug names for drug classes). A phrase must
  not be generic outside medicine.
- implies: IDs from the CONTEXT list this concept belongs to (may be empty)
- critical / high / normal: checklist item IDs the clinician needs because of this concept.
  critical = must not be missed, normal = useful background. Think about safety: blood
  thinners before bleeding or procedures, kidney function before contrast or renally cleared
  drugs, allergies before new drugs, cardiac causes of collapse, and so on.
Use only IDs from the lists given. Skip concepts that already exist in EXISTING.
"""

ALIAS_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["entries"],
    "properties": {"entries": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "phrases"],
        "properties": {"id": {"type": "string"}, "phrases": {"type": "array", "items": {"type": "string"}}}}}},
}
_IDS = {"type": "array", "items": {"type": "string"}}
CONCEPT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["concepts"],
    "properties": {"concepts": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["id", "label_en", "label_de", "match", "implies", "critical", "high", "normal"],
        "properties": {"id": {"type": "string"}, "label_en": {"type": "string"}, "label_de": {"type": "string"},
                       "match": _IDS, "implies": _IDS, "critical": _IDS, "high": _IDS, "normal": _IDS}}}},
}

CATEGORIES = [
    "symptoms and complaints (general, cardiovascular, respiratory, gastrointestinal, urinary)",
    "symptoms and complaints (neurological, psychiatric, musculoskeletal, skin, eye, ear-nose-throat, gynaecological)",
    "chronic conditions and diagnoses (cardiovascular, respiratory, metabolic, renal, liver)",
    "chronic conditions and diagnoses (neurological, psychiatric, autoimmune, infectious, oncological, haematological)",
    "operations and surgical procedures across specialties",
    "diagnostic and interventional procedures (endoscopy, catheter, imaging, punctures, biopsies)",
    "drug classes and high-risk medicines not yet covered",
    "medical devices, implants, therapies and care situations (dialysis, CPAP, pacemaker, wounds, pressure ulcers, nutrition)",
    "abnormal laboratory findings and electrolyte disturbances",
    "acute and emergency presentations",
]


def load_spec() -> dict:
    return yaml.safe_load(TREE_YAML.read_text(encoding="utf-8"))


def clean_phrase(p: str) -> str | None:
    if not isinstance(p, str):
        return None
    n = normalize(p.replace("*", ""))
    words = n.split()
    if not 1 <= len(words) <= 4 or len(n) < 3:
        return None
    if all(w in STOPWORDS for w in words):
        return None
    return n


def entries(spec: dict) -> list[dict]:
    out = []
    for group in ("roles", "tasks", "context", "concepts"):
        for nid, nd in (spec["nodes"].get(group) or {}).items():
            out.append({"id": nid, "kind": group[:-1] if group != "context" else "context",
                        "label": nd["label"]["en"] + " / " + nd["label"]["de"],
                        "existing": [m.strip("*") for m in nd.get("match", [])]})
    for iid, it in spec["items"].items():
        out.append({"id": iid, "kind": "item", "label": it["label"]["en"] + " / " + it["label"]["de"],
                    "existing": [m.strip("*") for m in it.get("ask", [])]})
    return out


def gen_aliases(client: GeminiClient, spec: dict) -> dict:
    todo = entries(spec)
    kinds = {e["id"]: e["kind"] for e in todo}
    known = {normalize(x) for e in todo for x in e["existing"]}
    result: dict[str, list[str]] = {}
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        user = json.dumps({"entries": batch}, ensure_ascii=False)
        try:
            data = client.complete_json(ALIAS_SYSTEM, user, ALIAS_SCHEMA, 90).data
        except LLMError as e:
            print(f"  batch {i // BATCH}: {e}")
            continue
        for e in data.get("entries", []):
            eid = e.get("id")
            if eid not in kinds:
                continue
            phrases = []
            for p in e.get("phrases", [])[:12]:
                n = clean_phrase(p)
                if not n or n in known or n in phrases:
                    continue
                if kinds[eid] == "role" and not PERSON.search(n):
                    continue  # a role alias must name a person
                phrases.append(n)
            if phrases:
                result[eid] = phrases
        print(f"  aliases batch {i // BATCH + 1}/{(len(todo) + BATCH - 1) // BATCH}: {len(result)} entries so far")
        time.sleep(PAUSE_S)
    return result


def gen_concepts(client: GeminiClient, spec: dict) -> dict:
    context_ids = list(spec["nodes"]["context"])
    item_ids = list(spec["items"])
    existing = set(context_ids) | set(spec["nodes"].get("concepts") or {}) | set(spec["nodes"]["roles"])
    existing_labels = sorted(existing)
    out: dict[str, dict] = {}
    for cat in CATEGORIES:
        user = json.dumps({
            "category": cat, "how_many": 20,
            "CONTEXT": context_ids, "ITEMS": item_ids,
            "EXISTING": existing_labels + sorted(out),
        }, ensure_ascii=False)
        try:
            data = client.complete_json(CONCEPT_SYSTEM, user, CONCEPT_SCHEMA, 120).data
        except LLMError as e:
            print(f"  {cat[:40]}: {e}")
            continue
        for c in data.get("concepts", []):
            cid = re.sub(r"[^a-z0-9_]", "_", str(c.get("id", "")).lower()).strip("_")
            if not cid or cid in existing or cid in out:
                continue
            match = []
            for p in c.get("match", [])[:12]:
                n = clean_phrase(p)
                if n and n not in match:
                    match.append(n)
            levels = {}
            seen = set()
            for lvl in ("critical", "high", "normal"):
                ids = [x for x in c.get(lvl, []) if x in item_ids and x not in seen]
                seen.update(ids)
                if ids:
                    levels[lvl] = ids
            if not match or not levels:
                continue
            out[cid] = {
                "label": {"en": str(c.get("label_en", cid))[:80], "de": str(c.get("label_de", cid))[:80]},
                "match": match,
                "implies": {x: 0.9 for x in c.get("implies", []) if x in context_ids},
                **levels,
            }
        print(f"  {cat[:60]}: {len(out)} concepts so far")
        time.sleep(PAUSE_S)
    return out


def write(name: str, data: dict, header: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=True, width=120)
    (OUT_DIR / name).write_text(header + text, encoding="utf-8")
    print(f"wrote {OUT_DIR / name}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aliases", action="store_true")
    ap.add_argument("--concepts", action="store_true")
    args = ap.parse_args(argv)
    if not (args.aliases or args.concepts):
        args.aliases = args.concepts = True
    load_env_file()
    client = GeminiClient(attempt_timeout=110)
    spec = load_spec()
    if args.aliases:
        write("aliases.yaml", gen_aliases(client, spec),
              "# Machine-generated by scripts/expand_graph.py (Gemini). Review before clinical use.\n"
              "# node or item id -> extra phrases it matches\n")
    if args.concepts:
        write("concepts.yaml", gen_concepts(client, spec),
              "# Machine-generated by scripts/expand_graph.py (Gemini). Review before clinical use.\n"
              "# concept id -> label, match phrases, implied context nodes, checklist items by priority\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
