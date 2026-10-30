"""Bounded recovery of uncited clinical paragraphs and missing dated encounter claims.

These are omission heuristics, not a claim of exhaustive clinical coverage.
"""
import re
from prep.extraction.source_checks import source_dates

VERSION = 'omission-recovery-v1'
SALIENT = re.compile(r'stenos|plaqu|lymphknoten|biops|karzinom|tumor', re.I)
DATED_EVENT = re.compile(r'\bam\s+(\d{1,2}[./]\d{1,2}[./]\d{4})(?!\d)[^.;\n]{0,100}\b(?:aufgenommen|entlassen)\b', re.I)


def uncovered_passages(passages, facts):
    result = []
    for p in passages:
        if p.kind != 'paragraph':
            continue
        supported = [f for f in facts if any(e.passage_id == p.id for e in f.evidence)]
        salient = SALIENT.search(p.text) and re.search(r'\d|\blinks\b|\brechts\b', p.text, re.I)
        event_dates = set().union(*(source_dates(m[1]) for m in DATED_EVENT.finditer(p.text)))
        recorded_dates = {f.clinical_time.value for f in supported if f.category == 'encounters' and f.clinical_time.basis in ('explicit', 'contextual')}
        if (salient and not supported) or event_dates - recorded_dates:
            result.append(p)
    return result


def with_headings(selected, all_passages):
    ids = {p.id for p in selected}
    heading = None
    for p in all_passages:
        if p.kind == 'heading':
            heading = p
        elif p.id in ids and heading and heading.section == p.section:
            ids.add(heading.id)
    return [p for p in all_passages if p.id in ids]
