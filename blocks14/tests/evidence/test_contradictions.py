import json
from pathlib import Path
import tempfile
import unittest

from prep.preparation import prepare_patient
from prep.evidence.schema import ClinicalTime, EvidenceRef, Fact
from prep.evidence.contradictions import detect_contradictions, display_contradictions, attach_report, ContradictionReport


class ContradictionTests(unittest.TestCase):
    def bundle(self, *texts):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for i,text in enumerate(texts):
                (root/f'd{i}.json').write_text(json.dumps({'metadata':{'id':f'd{i}','date':'2024-03-06'},'text':text},ensure_ascii=False),encoding='utf-8')
            return prepare_patient(root,'independent-conflicts','independent_synthetic')

    def bmi(self, height='170 cm', weight='80 kg', bmi='35'):
        return self.bundle(f'Vitalparameter:<BR>Größe: {height}<BR>Gewicht: {weight}<BR>BMI: {bmi}')

    def add_measurement(self,bundle,quote,*,side_site='A. carotis interna',date=None):
        p=next(p for p in bundle.passages if quote in p.text)
        start=p.start+p.text.index(quote)
        fact=Fact(id=f'test-{len(bundle.facts)}',category='imaging',concept='carotid_stenosis',label='Independent finding',
            value={'kind':'measurement','quantity':{'value':50,'unit':'%'},'site':side_site},assertion='affirmed',clinical_status='unknown',
            clinical_time={'precision':'day','value':date,'basis':'explicit'} if date else {'precision':'unknown','basis':'unknown'},
            evidence=[EvidenceRef(passage_id=p.id,start=start,end=start+len(quote),quote=quote)],extraction_method='rule',extractor_version='independent-fixture',
            validation={'quote_match':'passed','field_check':'passed','semantic_check':'not_checked'})
        bundle.facts.append(fact)
        return fact

    def test_large_bmi_disagreement_has_formula_and_all_sources(self):
        bundle=self.bmi()
        original=bundle.model_dump_json()
        report=detect_contradictions(bundle)
        self.assertEqual(len(report.contradictions),1)
        self.assertEqual(report.contradictions[0].status,'accepted')
        self.assertAlmostEqual(report.derived_facts[0].result.value,27.6817,places=4)
        refs={(r.passage_id,r.start,r.end) for r in report.contradictions[0].evidence}
        self.assertTrue(all((r.passage_id,r.start,r.end) in refs for f in bundle.facts for r in f.evidence))
        self.assertEqual(bundle.model_dump_json(),original)

    def test_correct_and_small_bmi_differences_are_not_conflicts(self):
        for bmi in ('27.7','28','28.1'):
            with self.subTest(bmi=bmi):
                self.assertEqual(detect_contradictions(self.bmi(bmi=bmi)).contradictions,[])

    def test_explicit_unit_conversion(self):
        report=detect_contradictions(self.bmi(height='1,70 m',weight='80000 g'))
        self.assertEqual(len(report.contradictions),1)
        self.assertAlmostEqual(report.derived_facts[0].result.value,27.6817,places=4)

    def test_nonpositive_bmi_input_skipped(self):
        for height,weight in (('0 cm','80 kg'),('170 cm','0 kg')):
            report=detect_contradictions(self.bmi(height=height,weight=weight))
            self.assertEqual(report.contradictions,[])
            self.assertIn('invalid_bmi_inputs',{d.code for d in report.diagnostics})

    def test_unsupported_bmi_unit_skipped(self):
        bundle=self.bmi()
        next(f for f in bundle.facts if f.concept=='body_weight').value.quantity.unit='lb'
        report=detect_contradictions(bundle)
        self.assertEqual(report.contradictions,[])
        self.assertIn('unsupported_bmi_units',{d.code for d in report.diagnostics})

    def test_valid_unit_name_must_also_match_source_unit(self):
        bundle=self.bmi()
        next(f for f in bundle.facts if f.concept=='body_height').value.quantity.unit='m'
        report=detect_contradictions(bundle)
        self.assertEqual(report.contradictions,[])
        self.assertIn('unsupported_bmi_source_fields',{d.code for d in report.diagnostics})

    def test_unknown_or_different_input_times_are_not_equal(self):
        bundle=self.bmi()
        bundle.facts[0].clinical_time=ClinicalTime(precision='unknown',basis='unknown')
        self.assertEqual(detect_contradictions(bundle).contradictions,[])

    def test_multiple_weights_in_one_block_do_not_get_arbitrarily_selected(self):
        bundle=self.bundle('Vitalparameter:<BR>Größe: 170 cm<BR>Gewicht: 80 kg<BR>Gewicht: 72 kg<BR>BMI: 35')
        report=detect_contradictions(bundle)
        self.assertEqual(report.contradictions,[])
        self.assertIn('ambiguous_bmi_inputs',{d.code for d in report.diagnostics})

    def test_shared_heading_does_not_join_separate_blocks(self):
        bundle=self.bundle('Vitalparameter:<BR>Größe: 170 cm<BR><BR>Gewicht: 80 kg<BR><BR>BMI: 35')
        self.assertEqual(detect_contradictions(bundle).derived_facts,[])

    def test_qualified_historical_block_not_compared(self):
        bundle=self.bundle('Vitalparameter:<BR>Früher gemessen.<BR>Größe: 170 cm<BR>Gewicht: 80 kg<BR>BMI: 35')
        self.assertEqual(detect_contradictions(bundle).contradictions,[])

    def test_multiple_dates_in_block_are_not_hidden_by_fallback_metadata(self):
        bundle=self.bundle('Vitalparameter:<BR>01.03.2020 Größe: 170 cm<BR>06.03.2024 Gewicht: 80 kg<BR>BMI: 35')
        self.assertEqual(detect_contradictions(bundle).contradictions,[])

    def test_distinct_source_events_not_joined_for_bmi(self):
        bundle=self.bmi()
        for i,f in enumerate(bundle.facts):
            f.event_id=f'event-{i}'
        self.assertEqual(detect_contradictions(bundle).contradictions,[])

    def test_exact_copied_bmi_conflict_counted_once_with_all_claims(self):
        text='Vitalparameter:<BR>Größe: 170 cm<BR>Gewicht: 80 kg<BR>BMI: 35'
        bundle=self.bundle(text,text)
        report=detect_contradictions(bundle)
        self.assertEqual(len(report.contradictions),1)
        self.assertEqual(len(report.derived_facts),2)
        self.assertEqual(len(report.contradictions[0].claim_ids),8)

    def test_repeated_rule_model_facts_do_not_duplicate_conflict(self):
        bundle=self.bmi()
        copies=[]
        for f in bundle.facts:
            copied=f.model_copy(deep=True)
            copied.id+='-model'
            copied.extraction_method='llm'
            copies.append(copied)
        bundle.facts.extend(copies)
        report=detect_contradictions(bundle)
        self.assertEqual(len(report.contradictions),1)
        self.assertEqual(len(report.contradictions[0].claim_ids),7)

    def dates(self):
        return self.bundle('Aufnahme am 02.03.2024<BR><BR>Aufnahme am 04.03.2024')

    def test_unlinked_document_dates_are_review_only(self):
        bundle=self.dates()
        report=detect_contradictions(bundle)
        self.assertEqual([c.status for c in report.contradictions],['candidate'])
        self.assertEqual(display_contradictions(bundle,report),[])

    def test_explicit_same_event_dates_accepted_once(self):
        bundle=self.dates()
        for f in bundle.facts:
            f.event_id='encounter-A'
        report=detect_contradictions(bundle)
        self.assertEqual([c.status for c in report.contradictions],['accepted'])
        self.assertEqual(report.contradictions[0].kind,'event_date')

    def test_separate_encounters_do_not_conflict(self):
        bundle=self.dates()
        for i,f in enumerate(bundle.facts):
            f.event_id=f'encounter-{i}'
        self.assertEqual(detect_contradictions(bundle).contradictions,[])

    def test_planned_and_completed_dates_do_not_conflict(self):
        bundle=self.dates()
        bundle.facts[0].clinical_status='planned'
        self.assertEqual(detect_contradictions(bundle).contradictions,[])

    def test_document_date_fallback_is_not_event_date(self):
        bundle=self.dates()
        bundle.facts[0].clinical_time.basis='document_fallback'
        self.assertEqual(detect_contradictions(bundle).contradictions,[])

    def test_different_documents_do_not_establish_same_encounter(self):
        bundle=self.bundle('Aufnahme am 02.03.2024','Aufnahme am 04.03.2024')
        self.assertEqual(detect_contradictions(bundle).contradictions,[])

    def test_uncited_event_date_is_not_compared(self):
        bundle=self.dates()
        bundle.facts[0].clinical_time.value='2024-03-03'
        report=detect_contradictions(bundle)
        self.assertEqual(report.contradictions,[])
        self.assertIn('unconfirmed_event_date',{d.code for d in report.diagnostics})

    def test_malformed_date_not_repaired_or_counted_as_conflict(self):
        bundle=self.bundle('Aufnahme am 02.03.20244<BR><BR>Aufnahme am 04.03.2024')
        self.assertEqual(detect_contradictions(bundle).contradictions,[])
        self.assertTrue(bundle.processing_gaps)

    def sided(self, summary=True, right='Rechts 50% Stenose.',left='Links 50% Stenose.'):
        heading='Gesamtbeurteilung:' if summary else 'Weitere Befunde:'
        bundle=self.bundle(f'Duplex:<BR>{right}<BR><BR>{heading}<BR>{left}')
        self.add_measurement(bundle,right)
        self.add_measurement(bundle,left)
        return bundle

    def test_opposite_sides_alone_are_not_contradictions(self):
        self.assertEqual(detect_contradictions(self.sided(summary=False)).contradictions,[])

    def test_summary_side_disagreement_is_candidate_not_accepted(self):
        bundle=self.sided()
        report=detect_contradictions(bundle)
        self.assertEqual([(c.kind,c.status) for c in report.contradictions],[('laterality','candidate')])
        self.assertEqual(display_contradictions(bundle,report),[])

    def test_sided_findings_on_different_dates_are_not_candidates(self):
        bundle=self.sided()
        for f,date in zip(bundle.facts,('2024-03-02','2024-03-04')):
            f.clinical_time=ClinicalTime(precision='day',basis='explicit',value=date)
        self.assertEqual(detect_contradictions(bundle).contradictions,[])

    def test_ambiguous_side_not_used(self):
        bundle=self.sided(right='Rechts und links 50% Stenose.')
        self.assertEqual(detect_contradictions(bundle).contradictions,[])

    def test_suspected_or_family_findings_not_compared(self):
        for field,value in (('assertion','suspected'),('subject','family_member')):
            bundle=self.sided()
            setattr(bundle.facts[0],field,value)
            self.assertEqual(detect_contradictions(bundle).contradictions,[])

    def test_tampered_report_cannot_promote_candidate(self):
        bundle=self.dates()
        report=detect_contradictions(bundle)
        report.contradictions[0].status='accepted'
        with self.assertRaises(ValueError):
            display_contradictions(bundle,report)

    def test_stale_report_rejected(self):
        bundle=self.bmi()
        report=detect_contradictions(bundle)
        bundle.manifest.evidence_version='changed'
        with self.assertRaises(ValueError):
            report.validate_against(bundle)

    def test_report_roundtrip_and_determinism(self):
        bundle=self.bmi()
        report=detect_contradictions(bundle)
        self.assertEqual(report,ContradictionReport.model_validate_json(report.model_dump_json()))
        self.assertEqual(report,detect_contradictions(bundle))

    def test_enrichment_changes_version_not_sources_or_gaps(self):
        bundle=self.bmi()
        original=bundle.model_dump_json()
        enriched=attach_report(bundle,detect_contradictions(bundle))
        self.assertNotEqual(enriched.manifest.evidence_version,bundle.manifest.evidence_version)
        self.assertEqual(enriched.facts,bundle.facts)
        self.assertEqual(enriched.documents,bundle.documents)
        self.assertEqual(enriched.processing_gaps,bundle.processing_gaps)
        self.assertEqual(len(enriched.derived_facts),1)
        self.assertEqual(len(enriched.contradictions),1)
        self.assertEqual(bundle.model_dump_json(),original)

    def test_enrichment_does_not_promote_review_candidates(self):
        bundle=self.dates()
        enriched=attach_report(bundle,detect_contradictions(bundle))
        self.assertEqual([c.status for c in enriched.contradictions],['candidate'])

    def test_exported_schema_is_current(self):
        schema=json.loads(Path('contracts/contradiction-report.schema.json').read_text(encoding='utf-8'))
        self.assertEqual(schema,ContradictionReport.model_json_schema())

    def test_independent_source_corpus_and_frozen_labels(self):
        from evaluation.score_contradictions import score_case
        from evaluation.build_contradiction_development import build
        root=Path('tests/fixtures/contradictions')
        with tempfile.TemporaryDirectory() as directory:
            rebuilt=Path(directory)
            build(rebuilt)
            for path in root.rglob('*.json'):
                self.assertEqual(path.read_bytes(),(rebuilt/path.relative_to(root)).read_bytes())
        golds=list((root/'gold').glob('*.json'))
        self.assertEqual(len(golds),12)
        for path in golds:
            gold=json.loads(path.read_text(encoding='utf-8'))
            with self.subTest(case=gold['case_id']):
                bundle=prepare_patient(root/'inputs'/gold['case_id'],gold['case_id'],'independent_synthetic')
                result,_=score_case(bundle,gold)
                self.assertTrue(result['passed'])
                self.assertEqual(result['accepted_false_alarms'],0)

    def test_evaluation_rejects_stale_sources_and_invalid_gold_quotes(self):
        from evaluation.score_contradictions import score_case
        bundle=self.bmi()
        gold={'case_id':'test','source_hashes':{d.id:d.source_sha256 for d in bundle.documents},
            'expected_findings':[{'kind':'numeric_inconsistency','status':'accepted','required_quotes':[{'document_id':'d0','quote':'invented'}]}]}
        with self.assertRaisesRegex(ValueError,'Gold quote'):
            score_case(bundle,gold)
        gold['source_hashes']['d0']='0'*64
        with self.assertRaisesRegex(ValueError,'hash mismatch'):
            score_case(bundle,gold)


if __name__=='__main__':
    unittest.main()
