"""Validated startup loader; this example performs no model/network calls."""
import hashlib
import json
from pathlib import Path
from prep.evidence.schema import EvidenceBundle
from prep.evidence.normalization import NormalizationIndex, bundle_hash
from prep.evidence.reconciliation import ReconciliationIndex, presentation_facts
from prep.evidence.contradictions import ContradictionReport


def load_patient(directory=None):
    root = Path(directory) if directory else Path(__file__).resolve().parent / 'data/handoff/patient-0000-0001'
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        path = (root/name).resolve()
        if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Invalid package file or checksum')
    def read(name):
        return (root/name).read_text(encoding='utf-8-sig')
    source = EvidenceBundle.model_validate_json(read('source-evidence.json'))
    evidence = EvidenceBundle.model_validate_json(read('evidence.json'))
    normalization = NormalizationIndex.model_validate_json(read('normalization.json'))
    reconciliation = ReconciliationIndex.model_validate_json(read('reconciliation.json'))
    report = ContradictionReport.model_validate_json(read('contradiction-report.json'))
    normalization.validate_against(evidence)
    reconciliation.validate_against(evidence)
    report.validate_against(source)
    history = json.loads(read('history.json'))
    if manifest['evidence_version'] != evidence.manifest.evidence_version or history['source_evidence_version'] != evidence.manifest.evidence_version or history['source_bundle_sha256'] != bundle_hash(evidence):
        raise ValueError('Mixed evidence/index versions')
    return {'evidence':evidence, 'normalization':normalization, 'reconciliation':reconciliation,
        'history':history, 'facts_by_id':{f.id:f for f in evidence.facts},
        'presentation_facts':presentation_facts(evidence,reconciliation),
        'accepted_contradictions':[c for c in evidence.contradictions if c.status=='accepted'],
        'review_candidates':[c for c in evidence.contradictions if c.status=='candidate']}


if __name__ == '__main__':
    patient = load_patient()
    evidence = patient['evidence']
    print(json.dumps({'patient_id':evidence.manifest.patient_id, 'as_of':patient['history']['as_of'],
        'documents':len(evidence.documents), 'facts':len(evidence.facts), 'derived_values':len(evidence.derived_facts),
        'accepted_contradictions':len(patient['accepted_contradictions']),
        'review_candidates':len(patient['review_candidates']), 'model_calls':0},indent=2))
