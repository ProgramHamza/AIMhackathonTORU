"""Build a consistent offline handoff from a saved source-evidence bundle."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

from prep.evidence.schema import EvidenceBundle
from prep.evidence.contradictions import detect_contradictions, attach_report
from prep.evidence.history import weight_change,measurement_history,latest_discharge_medications,latest_measurements,cutoff,VERSION as HISTORY_VERSION
from prep.evidence.normalization import normalize_bundle,bundle_hash,canonicalize
from prep.evidence.reconciliation import reconcile_bundle
from prep.preparation import write_bundle


def build_handoff(source,output):
    output=Path(output)
    report=detect_contradictions(source)
    enriched=attach_report(source,report)
    change=weight_change(source)
    if change:
        raw=enriched.model_dump(mode='json')
        if change.id not in {d['id'] for d in raw['derived_facts']}:
            raw['derived_facts'].append(change.model_dump(mode='json'))
        version=hashlib.sha256((enriched.manifest.evidence_version+change.model_dump_json()).encode()).hexdigest()
        raw['manifest'].update(evidence_version=version,bundle_id=source.manifest.patient_id+':'+version[:16],
            pipeline_version=enriched.manifest.pipeline_version+'+'+HISTORY_VERSION,
            configuration_hash=hashlib.sha256((enriched.manifest.configuration_hash+HISTORY_VERSION).encode()).hexdigest(),
            prepared_at=datetime.now(timezone.utc).isoformat())
        enriched=EvidenceBundle.model_validate(raw)
    normalization=normalize_bundle(enriched)
    reconciliation=reconcile_bundle(enriched)
    concepts=sorted({canonicalize(f)[0] or f.concept for f in enriched.facts if f.value.kind=='measurement'})
    history={'version':HISTORY_VERSION,'source_evidence_version':enriched.manifest.evidence_version,'source_bundle_sha256':bundle_hash(enriched),
        'as_of':cutoff(enriched),'latest_discharge_medications':latest_discharge_medications(enriched).model_dump(),
        'measurements':{c:{'history':[p.model_dump() for p in measurement_history(enriched,c)],
            'latest':latest_measurements(enriched,c).model_dump()} for c in concepts},
        'weight_change_id':change.id if change else None}
    artifacts={'source-evidence.json':source,'evidence.json':enriched,'contradiction-report.json':report,
        'normalization.json':normalization,'reconciliation.json':reconciliation}
    for name,value in artifacts.items():
        write_bundle(value,output/name)
    (output/'history.json').write_text(json.dumps(history,ensure_ascii=False,indent=2),encoding='utf-8')
    files=[*artifacts,'history.json']
    manifest={'patient_id':source.manifest.patient_id,'evidence_version':enriched.manifest.evidence_version,
        'as_of':history['as_of'],'files':{name:hashlib.sha256((output/name).read_bytes()).hexdigest() for name in files},
        'notes':['Validate file hashes before consuming this package.','contradiction-report.json is validated against source-evidence.json.',
            'Normalization, reconciliation and history refer to evidence.json.','Only accepted contradictions are default-display findings.',
            'Latest documented evidence does not prove current use or absent later documentation.']}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return enriched


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    # Prevent package output from replacing its own input artifact.
    if args.input.resolve().parent==args.output.resolve():
        parser.error('Input must be outside the output package directory')
    source=EvidenceBundle.model_validate_json(args.input.read_text(encoding='utf-8-sig'))
    result=build_handoff(source,args.output)
    print(json.dumps({'facts':len(result.facts),'derived':len(result.derived_facts),'as_of':cutoff(result),'model_calls':0,'output':str(args.output)},indent=2))


if __name__=='__main__':
    main()
