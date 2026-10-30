"""Deterministic, provenance-preserving indexing of an existing evidence bundle.

No model calls, fact merging, clinical adjudication or drug-name inference.
"""
import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Literal

from pydantic import Field
from prep.evidence.schema import EvidenceBundle, EvidenceRef, Model

VERSION = 'normalization-v1'


def key(value):
    value = unicodedata.normalize('NFKC', value).casefold().strip()
    prefixes = {'diagnosis', 'symptom', 'vital', 'demographics', 'encounter', 'history', 'medical_history', 'imaging', 'functional_test'}
    if ':' in value and value.split(':', 1)[0] in prefixes:
        value = value.split(':', 1)[1]
    return re.sub(r'[^\w]+', '_', value).strip('_')


# Explicit aliases only; a concept group is NOT a claim that two facts are duplicates.
ALIASES = {
    'birth_date': ['patient_birth_date'],
    'admission': ['hospital_admission'],
    'discharge': [],
    'hypertensive_crisis': ['hypertensive_krise'],
    'dizziness': ['schwindel'],
    'visual_impairment': ['visual_disturbance', 'sehbeeintraechtigung', 'sehbeeinträchtigung'],
    'amaurosis_fugax': [],
    'carotid_stenosis': ['internal_carotid_artery_stenosis', 'stenose_der_a_carotis_sin'],
    'hollenhorst_plaques': [],
    'fundus_hypertonicus': [],
    'hypertensive_retinopathy': [],
    'type_2_diabetes_mellitus': ['diabetes_mellitus_type_2', 'diabetes_mellitus_typ_ii', 'type_2_diabetes_mellitus'],
    'gastroesophageal_reflux_disease': ['gerd'],
    'systemic_lupus_erythematosus': ['systemischer_lupus_erythematodes'],
    'hypercholesterolemia': ['hypercholesterinaemie', 'hypercholesterinämie'],
    'hyperlipidemia': ['hyperlipidaemie', 'hyperlipidämie'],
    'hba1c': [],
    'systolic_blood_pressure': [], 'diastolic_blood_pressure': [],
    'body_height': [], 'body_weight': [], 'body_mass_index': [], 'body_temperature': [],
    'heart_rate': [], 'ejection_fraction': [],
    'sinus_rhythm': [], 'supraventricular_extrasystoles': [],
    'cholecystectomy': [], 'sleep_apnea': [], 'osteoporosis': [], 'vitamin_d_deficiency': [],
    'invasive_ductal_breast_carcinoma': [], 'breast_cancer': [],
    'bi_rads': [], 'acr': [], 'ki67': [], 'her2': [],
    'estrogen_receptor': [], 'estrogen_receptor_percent': [], 'estrogen_receptor_allred': [],
    'progesterone_receptor': [], 'progesterone_receptor_percent': [], 'progesterone_receptor_allred': [],
    'tumour_stage': [], 'specimen_collection': [], 'mammography': [],
}
LOOKUP = {key(alias): canonical for canonical, aliases in ALIASES.items() for alias in [canonical, *aliases]}


class NormalizedEntry(Model):
    fact_id: str
    original_concept: str
    canonical_concept: str | None = None
    concept_rule: str | None = None
    reported_laterality: str = 'unspecified'
    laterality: Literal['left', 'right', 'bilateral', 'unspecified'] = 'unspecified'
    laterality_status: Literal['explicit', 'contextual', 'ambiguous', 'conflict', 'unconfirmed', 'not_stated']
    laterality_evidence: list[EvidenceRef] = Field(default_factory=list)


class NormalizationIndex(Model):
    schema_version: Literal['1.0.0'] = '1.0.0'
    normalization_version: str = VERSION
    source_evidence_version: str
    source_bundle_sha256: str
    entries: list[NormalizedEntry]

    def validate_against(self, bundle):
        if self.normalization_version != VERSION:
            raise ValueError('Unsupported normalization version; rebuild index')
        if self.source_evidence_version != bundle.manifest.evidence_version or self.source_bundle_sha256 != bundle_hash(bundle):
            raise ValueError('Normalization index belongs to a different bundle')
        facts = {f.id:f for f in bundle.facts}
        if len(self.entries) != len(facts) or {e.fact_id for e in self.entries} != set(facts):
            raise ValueError('Normalization index must contain each source fact exactly once')
        passages = {p.id:p for p in bundle.passages}
        docs = {d.id:d for d in bundle.documents}
        for entry in self.entries:
            fact = facts[entry.fact_id]
            if entry.original_concept != fact.concept:
                raise ValueError('Original concept mismatch')
            if (entry.canonical_concept, entry.concept_rule) != canonicalize(fact):
                raise ValueError('Concept mapping does not match the declared rules')
            allowed = {e.passage_id for e in fact.evidence}
            for ref in entry.laterality_evidence:
                p = passages.get(ref.passage_id)
                if p is None or p.id not in allowed or not p.start <= ref.start < ref.end <= p.end:
                    raise ValueError('Laterality evidence must stay in a source-cited passage')
                if docs[p.document_id].normalized_text[ref.start:ref.end] != ref.quote:
                    raise ValueError('Laterality quote mismatch')
            expected = laterality(fact, passages)
            actual = (entry.reported_laterality, entry.laterality, entry.laterality_status, entry.laterality_evidence)
            if actual != expected:
                raise ValueError('Laterality does not match the declared rules')


def bundle_hash(bundle):
    return hashlib.sha256(bundle.model_dump_json().encode()).hexdigest()


def canonicalize(fact):
    source_key = key(fact.concept)
    if source_key in LOOKUP:
        return LOOKUP[source_key], 'alias:' + source_key
    # Ambiguous names are only specialized using their structured fields or source wording.
    text = ' '.join(e.quote for e in fact.evidence).casefold()
    if source_key == 'diabetes_mellitus' and re.search(r'\b(?:typ\s*(?:ii|2)|dmii|diab\.\s*mell\.\s*ii)\b', text):
        return 'type_2_diabetes_mellitus', 'context:explicit_type_2'
    if source_key == 'stenosis' and 'carotis' in (getattr(fact.value, 'site', '') or '').casefold():
        return 'carotid_stenosis', 'context:carotid_site'
    if source_key in ('blood_pressure', 'blood_pressure_peak'):
        method = (getattr(fact.value, 'method', '') or '').casefold()
        if re.search(r'\bsystolic\b|\bsystolisch', method):
            return 'systolic_blood_pressure', 'context:explicit_systolic_method'
        if re.search(r'\bdiastolic\b|\bdiastolisch', method):
            return 'diastolic_blood_pressure', 'context:explicit_diastolic_method'
    if source_key == 'rhythm' and 'sinusrhythmus' in text:
        return 'sinus_rhythm', 'context:sinus_rhythm'
    return None, None


SIDE = re.compile(r'\b(?P<bilateral>beidseits\b|beiderseits\b|bilateral\b|bds\.(?!\w))|\b(?P<left>links\b|linke[nmrs]?\b|li\b(?:\.)?|sin\.(?!\w))|\b(?P<right>rechts\b|rechte[nmrs]?\b|re\b(?:\.)?|dex\.(?!\w))', re.I)


def laterality(fact, passages):
    reported = getattr(fact.value, 'laterality', 'unspecified')
    # Do not attach anatomical sides to demographics, doses, or unrelated vital signs.
    if fact.category not in {'diagnoses', 'symptoms', 'imaging', 'functional_tests', 'pathology', 'procedures', 'medical_history', 'care_plans'}:
        return reported, 'unspecified', 'unconfirmed' if reported != 'unspecified' else 'not_stated', []
    # A side elsewhere in a broad quote must not make systemic disease sided.
    anatomical_concepts = {'amaurosis_fugax', 'visual_impairment', 'carotid_stenosis',
        'invasive_ductal_breast_carcinoma', 'breast_cancer', 'hollenhorst_plaques',
        'fundus_hypertonicus', 'hypertensive_retinopathy', 'mammography'}
    if not getattr(fact.value, 'site', None) and canonicalize(fact)[0] not in anatomical_concepts:
        return reported, 'unspecified', 'unconfirmed' if reported != 'unspecified' else 'not_stated', []
    sides, refs, contextual = set(), [], False
    for evidence in fact.evidence:
        p = passages[evidence.passage_id]
        start, end = evidence.start - p.start, evidence.end - p.start
        markers = list(SIDE.finditer(p.text))
        inside = [m for m in markers if start <= m.start() < end]
        if inside:
            selected = inside
            ref_start = start
        else:
            before = [m for m in markers if m.end() <= start and start - m.start() <= 250]
            if not before:
                continue
            selected = [before[-1]]
            between = p.text[selected[0].end():start+1]
            # Never borrow a side across a new sentence; keep abbreviations/decimal dots intact.
            if re.search(r'[!?;]|\n\s*\n|\.\s+(?=[A-ZÄÖÜ])', between):
                continue
            ref_start = selected[0].start()
            contextual = True
        sides.update(m.lastgroup for m in selected)
        refs.append(EvidenceRef(passage_id=p.id,start=p.start+ref_start,end=evidence.end,quote=p.text[ref_start:end]))
    refs = list({(r.passage_id,r.start,r.end):r for r in refs}.values())
    if not sides:
        return reported, 'unspecified', 'unconfirmed' if reported != 'unspecified' else 'not_stated', []
    if len(sides) != 1:
        return reported, 'unspecified', 'ambiguous', refs
    side = next(iter(sides))
    if reported not in ('unspecified', side):
        return reported, 'unspecified', 'conflict', refs
    return reported, side, 'contextual' if contextual else 'explicit', refs


def normalize_bundle(bundle):
    passages = {p.id:p for p in bundle.passages}
    entries = []
    for fact in bundle.facts:
        concept, rule = canonicalize(fact)
        reported, side, status, refs = laterality(fact, passages)
        entries.append(NormalizedEntry(fact_id=fact.id, original_concept=fact.concept,
            canonical_concept=concept, concept_rule=rule, reported_laterality=reported,
            laterality=side, laterality_status=status, laterality_evidence=refs))
    result = NormalizationIndex(source_evidence_version=bundle.manifest.evidence_version,
        source_bundle_sha256=bundle_hash(bundle), entries=entries)
    result.validate_against(bundle)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error('Output must not overwrite the source bundle')
    bundle = EvidenceBundle.model_validate_json(args.input.read_text(encoding='utf-8-sig'))
    result = normalize_bundle(bundle)
    from prep.preparation import write_bundle
    write_bundle(result,args.output)
    print(json.dumps({'facts_indexed':len(result.entries),
        'concepts_mapped':sum(e.canonical_concept is not None for e in result.entries),
        'laterality_assigned':sum(e.laterality!='unspecified' for e in result.entries),
        'laterality_ambiguous_or_conflicting':sum(e.laterality_status in ('ambiguous','conflict') for e in result.entries),
        'model_calls':0,'output':str(args.output)},indent=2))


if __name__ == '__main__':
    main()
