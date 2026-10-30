"""Strict field-and-provenance scoring against frozen, development-only labels."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from prep.evidence.schema import EvidenceBundle


def subset(actual, expected):
    """Only annotated fields count; lists are exact, not fuzzy or judge-scored."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and subset(actual[k], v) for k, v in expected.items())
    return actual == expected


def score(bundle, gold, *, reconcile=False):
    docs = {d.id: d for d in bundle.documents}
    passages = {p.id: p for p in bundle.passages}
    if set(docs) != set(gold['source_hashes']):
        raise ValueError('Gold and bundle must contain the same documents')
    for doc_id, expected_hash in gold['source_hashes'].items():
        if docs[doc_id].source_sha256 != expected_hash:
            raise ValueError('Source hash mismatch; do not score stale labels')
    labels = gold['expected_facts']
    if len({g['id'] for g in labels}) != len(labels):
        raise ValueError('Duplicate gold IDs')
    for g in labels:
        if not g['evidence']:
            raise ValueError('Gold fact requires evidence')
        for span in g['evidence']:
            doc = docs[span['document_id']]
            if not 0 <= span['start'] < span['end'] <= len(doc.normalized_text) or doc.normalized_text[span['start']:span['end']] != span['quote']:
                raise ValueError('Gold evidence does not match source')
    # Whole documents are exhaustively labelled for the explicitly declared categories.
    if reconcile:
        from prep.evidence.reconciliation import presentation_facts
        candidates = presentation_facts(bundle)
    else:
        candidates = bundle.facts
    predictions = [f for f in candidates if f.category in gold['categories']]

    def fields_match(f, g):
        raw = f.model_dump(mode='json')
        return subset(raw, g['fields']) and (not g.get('concepts') or f.concept in g['concepts'])

    def evidence_match(f, g):
        # Every required gold span must be covered; extra heading refs are permitted.
        return all(any(passages[r.passage_id].document_id == s['document_id'] and r.start <= s['start'] and r.end >= s['end'] for r in f.evidence) for s in g['evidence'])

    edges = {i: [j for j, f in enumerate(predictions) if fields_match(f, g) and evidence_match(f, g)] for i, g in enumerate(labels)}
    # Maximum one-to-one matching prevents duplicate predictions inflating recall.
    owner = {}
    def assign(i, seen):
        for j in edges[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in owner or assign(owner[j], seen):
                owner[j] = i
                return True
        return False
    for i in edges:
        assign(i, set())
    matched = set(owner.values())
    tp, total, count = len(owner), len(predictions), len(labels)
    by_category = {}
    for category in gold['categories']:
        gcount = sum(g['fields']['category'] == category for g in labels)
        pcount = sum(f.category == category for f in predictions)
        hits = sum(labels[i]['fields']['category'] == category for i in matched)
        by_category[category] = {'matched': hits, 'expected': gcount, 'predicted': pcount}
    forbidden = [{'id': rule['id'], 'fact_ids': [f.id for f in predictions if subset(f.model_dump(mode='json'), rule['fields'])]} for rule in gold.get('forbidden_claims', [])]
    return {'case_id': gold['case_id'], 'review_status': gold['review_status'],
        'matched': tp, 'expected': count, 'predicted': total,
        'precision': tp / total if total else None, 'recall': tp / count if count else None,
        'by_category': by_category,
        'matches': [{'gold_id': labels[i]['id'], 'fact_id': predictions[j].id} for j, i in sorted(owner.items())],
        'missing_gold_ids': [g['id'] for i, g in enumerate(labels) if i not in matched],
        'unmatched_predictions': [{'fact_id': f.id, 'concept': f.concept,
            'reason': 'duplicate_or_ambiguous_match' if any(j in e for e in edges.values()) else
                'wrong_or_incomplete_evidence' if any(fields_match(f, g) for g in labels) else 'fields_or_gold_coverage_require_review'}
            for j, f in enumerate(predictions) if j not in owner],
        'forbidden_claim_violations': [v for v in forbidden if v['fact_ids']],
        'processing_gaps': len(bundle.processing_gaps), 'bundle_status': bundle.manifest.status}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, default=Path('tests/fixtures/independent'))
    parser.add_argument('--predictions', type=Path, help='Directory of CASE-ID.json bundles; otherwise run rules-only baseline')
    parser.add_argument('--case', action='append', help='Restrict to named development case; repeatable')
    parser.add_argument('--reconcile', action='store_true', help='Score conservative presentation groups; preserve raw bundles')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from prep.preparation import prepare_patient, write_bundle
    results = []
    for path in sorted((args.corpus / 'gold').glob('*.json')):
        gold = json.loads(path.read_text(encoding='utf-8'))
        if args.case and gold['case_id'] not in args.case:
            continue
        if gold['split'] != 'development':
            raise ValueError('This runner only supports development cases')
        if args.predictions:
            bundle = EvidenceBundle.model_validate_json((args.predictions / (gold['case_id'] + '.json')).read_text(encoding='utf-8-sig'))
        else:
            bundle = prepare_patient(args.corpus / 'inputs' / gold['case_id'], gold['case_id'], 'independent_synthetic')
            write_bundle(bundle, args.output.parent / 'baseline-bundles' / (gold['case_id'] + '.json'))
        result = score(bundle, gold, reconcile=args.reconcile)
        result['gold_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        result['evidence_version'] = bundle.manifest.evidence_version
        results.append(result)
    if not results:
        raise ValueError('No labelled cases found')
    if args.case and set(args.case) != {r['case_id'] for r in results}:
        raise ValueError('Some requested cases have no gold labels')
    totals = {k: sum(r[k] for r in results) for k in ('matched', 'expected', 'predicted')}
    categories = {}
    for result in results:
        for category, counts in result['by_category'].items():
            categories.setdefault(category, Counter()).update(counts)
    report = {'scorer_version': 'strict-fields-and-spans-v1', 'mode': 'saved_predictions' if args.predictions else 'rules_only',
        'reconciled': args.reconcile,
        'limitations': 'AI-authored development labels, not clinician-reviewed; exact annotated fields and explicit concept alternatives only. Unmatched predictions require review, not automatic hallucination classification. No held-out or clinical accuracy claim.',
        'totals': {**totals, 'precision': totals['matched']/totals['predicted'] if totals['predicted'] else None,
            'recall': totals['matched']/totals['expected'] if totals['expected'] else None},
        'by_category': categories, 'cases': results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'cases': len(results), **report['totals'], 'output': str(args.output)}, indent=2))


if __name__ == '__main__':
    main()
