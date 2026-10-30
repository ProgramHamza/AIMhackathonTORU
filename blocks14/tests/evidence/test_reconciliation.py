import json
from pathlib import Path
import unittest

from prep.evidence.reconciliation import ReconciliationIndex, reconcile_bundle, presentation_facts, presentation_category
from prep.preparation import prepare_patient


class ReconciliationTests(unittest.TestCase):
    def bundle(self):
        bundle=prepare_patient(Path('tests/fixtures/independent/inputs/DEV-MEAS-01'),'test','independent_synthetic')
        bundle.facts=bundle.facts[:1]
        duplicate=bundle.facts[0].model_copy(deep=True)
        duplicate.id='model-copy'
        duplicate.event_id=None
        duplicate.extraction_method='llm'
        bundle.facts.append(duplicate)
        return bundle

    def test_exact_rule_model_duplicate_preserves_originals(self):
        bundle=self.bundle()
        before=bundle.model_dump_json()
        index=reconcile_bundle(bundle)
        self.assertEqual(len(index.groups),1)
        self.assertEqual(len(index.groups[0].source_fact_ids),2)
        self.assertEqual(index.groups[0].representative_fact_id,bundle.facts[0].id)
        view=presentation_facts(bundle,index)
        self.assertEqual(len(view),1)
        view[0].value.quantity.value=999
        self.assertEqual(before,bundle.model_dump_json())

    def test_semantic_differences_never_merge(self):
        for field,value in [('assertion','negated'),('clinical_status','historical'),('subject','family_member')]:
            with self.subTest(field=field):
                bundle=self.bundle()
                setattr(bundle.facts[1],field,value)
                self.assertEqual(len(reconcile_bundle(bundle).groups),2)
        for field,value in [('site','left arm'),('method','standing')]:
            with self.subTest(field=field):
                bundle=self.bundle()
                setattr(bundle.facts[1].value,field,value)
                self.assertEqual(len(reconcile_bundle(bundle).groups),2)

    def test_different_date_and_unknown_date_do_not_merge(self):
        for date in ({'precision':'day','value':'2020-01-01','basis':'explicit'}, {'precision':'unknown','basis':'unknown'}):
            bundle=self.bundle()
            from prep.evidence.schema import ClinicalTime
            bundle.facts[1].clinical_time=ClinicalTime(**date)
            self.assertEqual(len(reconcile_bundle(bundle).groups),2)

    def test_different_value_and_unit_do_not_merge(self):
        for field,value in [('value',68.3),('unit','lb')]:
            bundle=self.bundle()
            setattr(bundle.facts[1].value.quantity,field,value)
            self.assertEqual(len(reconcile_bundle(bundle).groups),2)

    def test_unknown_event_cannot_bridge_distinct_known_events(self):
        bundle=self.bundle()
        third=bundle.facts[0].model_copy(deep=True)
        third.id='third'
        third.event_id='distinct-event'
        bundle.facts.append(third)
        self.assertEqual(len(reconcile_bundle(bundle).groups),3)

    def test_repeated_source_location_is_not_duplicate(self):
        bundle=prepare_patient(Path('tests/fixtures/independent/inputs/DEV-SOURCE-01'),'test','independent_synthetic')
        self.assertEqual(len(reconcile_bundle(bundle).groups),2)

    def test_citation_order_is_irrelevant_but_missing_context_is_not(self):
        bundle=self.bundle()
        bundle.facts[1].evidence.reverse()
        self.assertEqual(len(reconcile_bundle(bundle).groups),1)
        bundle.facts[1].evidence=bundle.facts[1].evidence[:1]
        self.assertEqual(len(reconcile_bundle(bundle).groups),2)

    def test_category_policy_preserves_negation_and_status(self):
        bundle=self.bundle()
        raw=bundle.facts[0].model_dump()
        raw.update(category='procedures',clinical_status='recommended',value={'kind':'event','name':'Test'})
        from prep.evidence.schema import Fact
        fact=Fact.model_validate(raw)
        self.assertEqual(presentation_category(fact),'care_plans')
        fact.clinical_status='unknown'
        fact.assertion='negated'
        self.assertEqual(presentation_category(fact),'procedures')
        fact.clinical_status='planned'
        for category in ('followups','encounters'):
            fact.category=category
            self.assertEqual(presentation_category(fact),category)

    def test_sided_event_values_do_not_merge(self):
        bundle=self.bundle()
        from prep.evidence.schema import EventValue
        for f,side in zip(bundle.facts,('left','right')):
            f.category='procedures'
            f.value=EventValue(kind='event',name='Test',laterality=side)
        self.assertEqual(len(reconcile_bundle(bundle).groups),2)

    def test_tampered_and_stale_indexes_rejected(self):
        bundle=self.bundle()
        index=reconcile_bundle(bundle)
        index.groups[0].source_fact_ids.pop()
        with self.assertRaises(ValueError):
            index.validate_against(bundle)
        index=reconcile_bundle(bundle)
        bundle.facts[0].label='new label'
        with self.assertRaises(ValueError):
            index.validate_against(bundle)

    def test_exported_schema_matches(self):
        schema=json.loads(Path('contracts/reconciliation-index.schema.json').read_text(encoding='utf-8'))
        self.assertEqual(schema,ReconciliationIndex.model_json_schema())


if __name__=='__main__':
    unittest.main()
