"""Conservative presentation groups; immutable source facts remain authoritative."""
import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field
from prep.evidence.schema import Category, EvidenceBundle, Model
from prep.evidence.normalization import bundle_hash, canonicalize

VERSION = 'reconciliation-v1'


def presentation_category(fact):
    # Status is preserved: a negative procedure is not evidence of completion.
    if fact.category == 'procedures' and fact.value.kind == 'event' and fact.clinical_status in ('recommended', 'planned'):
        return 'care_plans'
    return fact.category


class CategoryChange(Model):
    fact_id: str
    original_category: Category
    presentation_category: Category
    rule: Literal['recommended_or_planned_procedure_is_care_plan'] = 'recommended_or_planned_procedure_is_care_plan'


class FactGroup(Model):
    id: str
    representative_fact_id: str
    source_fact_ids: list[str] = Field(min_length=1)
    category: Category


class ReconciliationIndex(Model):
    schema_version: Literal['1.0.0'] = '1.0.0'
    reconciliation_version: str = VERSION
    source_evidence_version: str
    source_bundle_sha256: str
    groups: list[FactGroup]
    category_changes: list[CategoryChange]

    def validate_against(self, bundle):
        if self.model_dump() != reconcile_bundle(bundle).model_dump():
            raise ValueError('Stale or modified reconciliation index; rebuild from source bundle')


def duplicate_key(fact):
    # Exact payload/time/evidence only. Do not erase method, site, status or provenance.
    # Unknown event IDs may join one known ID, never bridge two distinct known IDs.
    data = {'category': presentation_category(fact), 'concept': canonicalize(fact)[0] or fact.concept,
        'value': fact.value.model_dump(mode='json'), 'assertion': fact.assertion,
        'clinical_status': fact.clinical_status, 'subject': fact.subject,
        'clinical_time': fact.clinical_time.model_dump(mode='json'),
        'related_fact_ids': sorted(fact.related_fact_ids),
        'evidence': sorted({(r.passage_id, r.start, r.end, r.quote) for r in fact.evidence})}
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def reconcile_bundle(bundle):
    buckets = {}
    for fact in bundle.facts:
        buckets.setdefault(duplicate_key(fact), []).append(fact)
    groups = []
    for members in buckets.values():
        known_events = {f.event_id for f in members if f.event_id is not None}
        partitions = [[f] for f in members] if len(known_events) > 1 else [members]
        for partition in partitions:
            ids = sorted(f.id for f in partition)
            # Deterministic representative; this preference is not a truth ranking.
            representative = min(partition, key=lambda f: (f.event_id is None, f.extraction_method != 'rule', f.id))
            group_id = hashlib.sha256(json.dumps(ids).encode()).hexdigest()[:24]
            groups.append(FactGroup(id='group-'+group_id, representative_fact_id=representative.id,
                source_fact_ids=ids, category=presentation_category(representative)))
    changes = [CategoryChange(fact_id=f.id, original_category=f.category, presentation_category=presentation_category(f))
        for f in bundle.facts if presentation_category(f) != f.category]
    return ReconciliationIndex(source_evidence_version=bundle.manifest.evidence_version,
        source_bundle_sha256=bundle_hash(bundle), groups=sorted(groups, key=lambda g:g.id),
        category_changes=sorted(changes, key=lambda c:c.fact_id))


def presentation_facts(bundle, index=None):
    """Return display/scoring copies, not a replacement EvidenceBundle.

    All IDs/links resolve through the original bundle. Use groups for complete lineage.
    """
    index = index or reconcile_bundle(bundle)
    index.validate_against(bundle)
    by_id = {f.id:f for f in bundle.facts}
    return [by_id[g.representative_fact_id].model_copy(deep=True, update={'category':g.category}) for g in index.groups]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.input.resolve()==args.output.resolve():
        parser.error('Output must not overwrite the source bundle')
    bundle=EvidenceBundle.model_validate_json(args.input.read_text(encoding='utf-8-sig'))
    index=reconcile_bundle(bundle)
    index.validate_against(bundle)
    from prep.preparation import write_bundle
    write_bundle(index,args.output)
    print(json.dumps({'source_facts':len(bundle.facts),'presentation_groups':len(index.groups),
        'duplicate_groups':sum(len(g.source_fact_ids)>1 for g in index.groups),
        'category_changes':len(index.category_changes),'model_calls':0},indent=2))


if __name__=='__main__':
    main()
