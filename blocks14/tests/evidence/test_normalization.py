import unittest
from pathlib import Path

from prep.evidence.schema import EvidenceBundle, EvidenceRef, Fact, Passage
from prep.evidence.normalization import normalize_bundle, canonicalize, laterality


class NormalizationTests(unittest.TestCase):
    def fact(self, concept='stenosis', site='A. carotis interna', text='Rechts 40% Stenose.', quote=None):
        quote = quote or text
        start = text.index(quote)
        p = Passage(id='p',document_id='d',kind='paragraph',start=10,end=10+len(text),text=text)
        f = Fact(id='f',category='imaging',concept=concept,label='Untrusted label links',
            value={'kind':'measurement','quantity':{'value':40,'unit':'%'},'site':site},
            assertion='affirmed',clinical_status='unknown',clinical_time={'precision':'unknown','basis':'unknown'},
            evidence=[EvidenceRef(passage_id='p',start=10+start,end=10+start+len(quote),quote=quote)],
            extraction_method='llm',extractor_version='test',validation={'quote_match':'passed','field_check':'not_checked','semantic_check':'model_checked'})
        return f,{'p':p}

    def test_aliases_ignore_case_spacing_and_known_namespace(self):
        f,_=self.fact(concept='Diagnosis: Hypertensive Krise')
        self.assertEqual(canonicalize(f)[0],'hypertensive_crisis')
        f.concept='patient_birth_date'
        self.assertEqual(canonicalize(f)[0],'birth_date')

    def test_unspecified_diabetes_is_not_silently_type_two(self):
        f,_=self.fact(concept='diabetes_mellitus',text='Diabetes mellitus')
        self.assertIsNone(canonicalize(f)[0])
        f.evidence[0].quote='Diabetes mellitus Typ II'
        self.assertEqual(canonicalize(f)[0],'type_2_diabetes_mellitus')

    def test_generic_stenosis_requires_carotid_site(self):
        f,_=self.fact(site='Aortenklappe')
        self.assertIsNone(canonicalize(f)[0])
        f.value.site='A. carotis interna'
        self.assertEqual(canonicalize(f)[0],'carotid_stenosis')

    def test_explicit_source_overrides_untrusted_label_for_measurement(self):
        f,ps=self.fact()
        reported,side,status,refs=laterality(f,ps)
        self.assertEqual((reported,side,status),('unspecified','right','explicit'))
        self.assertEqual(refs[0].quote,'Rechts 40% Stenose.')

    def test_context_expansion_stops_before_opposite_side(self):
        text='Rechts zeigt sich an der A. carotis interna eine Einengung zu 40%. Links keine Plaques.'
        f,ps=self.fact(text=text,quote='Einengung zu 40%')
        _,side,status,refs=laterality(f,ps)
        self.assertEqual((side,status),('right','contextual'))
        self.assertTrue(refs[0].quote.startswith('Rechts'))
        self.assertNotIn('Links',refs[0].quote)
        self.assertEqual(refs[0].start,10)

    def test_context_not_borrowed_across_new_sentence(self):
        f,ps=self.fact(text='Links unauffällig. Stenose zu 40%.',quote='Stenose zu 40%')
        self.assertEqual(laterality(f,ps)[1:3],('unspecified','not_stated'))

    def test_mixed_sides_are_ambiguous_not_invented_bilateral(self):
        f,ps=self.fact(text='Links 40%, rechts 20%.')
        self.assertEqual(laterality(f,ps)[1:3],('unspecified','ambiguous'))

    def test_comparative_side_abbreviations_are_ambiguous(self):
        f,ps=self.fact(text='Papillenödem li > re.')
        self.assertEqual(laterality(f,ps)[1:3],('unspecified','ambiguous'))

    def test_conflicting_reported_laterality_is_flagged(self):
        f,ps=self.fact()
        raw=f.model_dump()
        raw['value']={'kind':'assertion','text':'Stenose','site':'A. carotis interna','laterality':'left'}
        f=Fact.model_validate(raw)
        self.assertEqual(laterality(f,ps)[1:3],('unspecified','conflict'))

    def test_does_not_match_side_inside_longer_word(self):
        f,ps=self.fact(text='Normale rechtsventrikuläre Funktion.')
        self.assertEqual(laterality(f,ps)[1:3],('unspecified','not_stated'))

    def test_systemic_disease_does_not_inherit_eye_laterality(self):
        f,ps=self.fact(concept='hypertensive_crisis',site=None,
            text='Hypertensive Krise mit Sehstörung links.')
        f.category='diagnoses'
        self.assertEqual(laterality(f,ps)[1:3],('unspecified','not_stated'))

    def test_index_rejects_modified_mapping(self):
        b=EvidenceBundle.model_validate_json(Path('contracts/examples/independent-patient.json').read_text(encoding='utf-8'))
        index=normalize_bundle(b)
        index.entries[0].canonical_concept='invented'
        with self.assertRaisesRegex(ValueError,'Concept mapping'):
            index.validate_against(b)

    def test_index_preserves_source_and_rejects_stale_or_bad_links(self):
        b=EvidenceBundle.model_validate_json(Path('contracts/examples/independent-patient.json').read_text(encoding='utf-8'))
        original=b.model_dump_json()
        index=normalize_bundle(b)
        self.assertEqual(original,b.model_dump_json())
        self.assertEqual(index.model_dump(),normalize_bundle(b).model_dump())
        self.assertEqual(len(index.entries),len(b.facts))
        index.source_evidence_version='different'
        with self.assertRaisesRegex(ValueError,'different bundle'):
            index.validate_against(b)


if __name__=='__main__':
    unittest.main()
