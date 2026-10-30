import unittest
from types import SimpleNamespace as NS
from prep.evidence.schema import Passage
from prep.extraction.coverage import uncovered_passages, with_headings


class CoverageTests(unittest.TestCase):
    def passage(self, id, text, kind='paragraph'):
        return Passage(id=id,document_id='independent',kind=kind,section='Befund',start=0,end=len(text),text=text)

    def test_uncited_sided_finding_is_selected(self):
        p=self.passage('finding','Rechts zeigt sich eine Einengung durch Kalkplaques zu etwa 40%.')
        self.assertEqual(uncovered_passages([p],[]),[p])
        fact=NS(evidence=[NS(passage_id=p.id)],category='imaging',clinical_time=NS(value=None,basis='unknown'))
        self.assertEqual(uncovered_passages([p],[fact]),[])

    def test_admission_does_not_mask_missing_discharge_in_same_paragraph(self):
        p=self.passage('events','Patient wurde am 02.08.2024 aufgenommen. Patient wurde am 06.08.2024 nach Hause entlassen.')
        def event(day):
            return NS(evidence=[NS(passage_id=p.id)],category='encounters',clinical_time=NS(value=day,basis='explicit'))
        self.assertEqual(uncovered_passages([p],[event('2024-08-02')]),[p])
        self.assertEqual(uncovered_passages([p],[event('2024-08-02'),event('2024-08-06')]),[])

    def test_heading_context_is_retained_and_admin_not_selected(self):
        heading=self.passage('heading','Befund:',kind='heading')
        finding=self.passage('finding','Links 40% Stenose.')
        admin=self.passage('admin','Patienten-ID: 9999')
        selected=uncovered_passages([heading,finding,admin],[])
        self.assertEqual(with_headings(selected,[heading,finding,admin]),[heading,finding])
