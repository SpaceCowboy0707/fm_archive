import json
import unittest
from src.evidence_gate import championship,validate_answer

class EvidenceTests(unittest.TestCase):
    def rows(self):
        return [dict(club_uid=i,club_name=str(i),played=38,won=10,drawn=0,lost=28,points=30) for i in range(20)]
    def test_title_missing_tied_games_in_hand(self):
        rows=self.rows();rows[0].update(won=11,lost=27,points=33)
        self.assertTrue(championship(rows,0)['mathematically_clinched'])
        rows[1].update(played=37,lost=27)
        self.assertFalse(championship(rows,0)['mathematically_clinched'])
        self.assertIn('error',championship(rows[:-1],0))
        rows[1]['points']=None
        self.assertIn('error',championship(rows,0))
    def query(self,value=10):
        return dict(name='season_statistics',arguments={'season':'2035/36','offset':0},result=dict(snapshot_date='2036-03-04',total=1,offset=0,next_offset=None,rows=[{'goals':value}]))
    def doc(self,value=10):
        return json.dumps(dict(season='2035/36',comparison_player_ids=[],facts=[dict(query=0,path=['rows',0,'goals'],value=value)],analysis="Qualitative explanation"))
    def test_reference_date_season_null_and_pagination(self):
        q=self.query();check=lambda:validate_answer(self.doc(),[q],'2036-03-04')
        self.assertTrue(check()['passed'])
        q['result']['rows'][0]['goals']=11;self.assertFalse(check()['passed'])
        q=self.query();q['result']['total']=2;self.assertTrue(check()['passed']);self.assertTrue(check()['partial'])
        q=self.query();q['result']['snapshot_date']='2036-04-01';self.assertFalse(check()['passed'])
        q=self.query();q['arguments']['season']='2034/35';self.assertFalse(check()['passed'])
        q=self.query(None);self.assertTrue(validate_answer(self.doc(None),[q],'2036-03-04')['passed'])
    def test_missing_both_players_and_title_evidence(self):
        self.assertTrue(validate_answer(self.doc(),[self.query()],'2036-03-04',"Compare two goalkeepers")['partial'])
        self.assertFalse(validate_answer(self.doc(),[self.query()],'2036-03-04',"Is the championship secure")['passed'])
    def test_missing_rate_and_nonfinite_are_not_facts(self):
        for value in (float('nan'),float('inf')):
            self.assertFalse(validate_answer(self.doc(value),[self.query(value)],'2036-03-04')['passed'])
    def test_title_text_is_program_rendered_not_model_claim(self):
        q=dict(name='title_race_status',arguments={'season':'2035/36'},result=dict(snapshot_date='2036-03-04',as_of='2036-03-04',mathematically_clinched=False,points=60))
        doc=json.dumps(dict(season='2035/36',comparison_player_ids=[],facts=[dict(query=0,path=['points'],value=60)],analysis="Already champions! 97%!"))
        r=validate_answer(doc,[q],'2036-03-04',"Is the championship secure now")
        self.assertTrue(r['passed']);self.assertNotIn('97%',r['text']);self.assertNotIn("Already champions!",r['text'])
        q['result']['as_of']='2036-02-11'
        self.assertFalse(validate_answer(doc,[q],'2036-03-04',"Is the championship secure now")['passed'])
    def test_partial_pagination_preserves_data_without_model_analysis(self):
        q=self.query();q['result']['total']=2
        r=validate_answer(self.doc(),[q],'2036-03-04')
        self.assertTrue(r['partial']);self.assertIn('1/2',r['text'])
        self.assertIn("Qualitative explanation",r['text'])
        self.assertTrue(r['passed'])
        self.assertIn("Missing information and conclusion boundaries",r['text'])

    def test_numeric_markdown_preserved_and_evidence_separate(self):
        doc=json.loads(self.doc())
        doc['analysis']="Start with output.\n\n|Metric|Value|\n|---|---:|\n|Goals|10|"
        r=validate_answer(json.dumps(doc),[self.query()],'2036-03-04')
        self.assertTrue(r['passed'])
        self.assertEqual(r['text'],doc['analysis'])
        self.assertIn('goals',r['verified_facts'][0])
        doc['facts'][0]['value']=11
        self.assertFalse(validate_answer(json.dumps(doc),[self.query()],'2036-03-04')['passed'])

    def test_empty_queries_allow_honest_limitations_without_facts(self):
        doc=json.loads(self.doc());doc['facts']=[];doc['analysis']="No injury records were retrieved this round; the reason for absence cannot be established."
        q=self.query();q['result'].update(rows=[],total=0)
        result=validate_answer(json.dumps(doc),[q],'2036-03-04')
        self.assertTrue(result['passed']);self.assertTrue(result['partial'])
        self.assertFalse(validate_answer(json.dumps(doc),[self.query()],'2036-03-04')['passed'])

    def test_long_report_and_code_fence_and_diagnostics(self):
        doc=json.loads(self.doc());doc['facts']=doc['facts']*100
        self.assertTrue(validate_answer('```json\n'+json.dumps(doc)+'\n```',[self.query()],'2036-03-04')['passed'])
        bad=validate_answer('{broken',[],'2036-03-04')
        self.assertIn("valid JSON",bad['errors'][0])
        bad=validate_answer(self.doc(11),[self.query()],'2036-03-04')
        self.assertIn("Reference 1",bad['errors'][0])

    def test_null_is_verified_absence_not_zero(self):
        q=self.query(None)
        self.assertTrue(validate_answer(self.doc(None),[q],'2036-03-04')['passed'])
        self.assertFalse(validate_answer(self.doc(0),[q],'2036-03-04')['passed'])
        q=self.query();q['result']['next_offset']=None
        doc=json.loads(self.doc());doc['facts'].append(dict(query=0,path=['next_offset'],value=None))
        self.assertTrue(validate_answer(json.dumps(doc),[q],'2036-03-04')['passed'])

    def test_every_mismatch_is_reported_with_location_hint(self):
        q=self.query();q['result']['rows']=[{'row_index':i,'goals':g} for i,g in enumerate((4,31,9))]
        doc=json.loads(self.doc());doc['facts']=[dict(query=0,path=['rows',2,'goals'],value=31),dict(query=0,path=['rows',0,'goals'],value=4),dict(query=0,path=['rows',3,'goals'],value=9)]
        r=validate_answer(json.dumps(doc),[q],'2036-03-04')
        self.assertFalse(r['passed']);self.assertTrue(r['repairable'])
        self.assertEqual(len(r['errors']),2)
        self.assertIn('Reference 1',r['errors'][0]);self.assertIn('cites 31, but the tool returned 9',r['errors'][0]);self.assertIn('["rows", 1, "goals"]',r['errors'][0])
        self.assertIn('Reference 3',r['errors'][1]);self.assertIn('["rows", 2, "goals"]',r['errors'][1])
    def test_errors_needing_new_queries_are_not_repairable(self):
        q=self.query();q['result']['snapshot_date']='2036-04-01'
        self.assertFalse(validate_answer(self.doc(),[q],'2036-03-04')['repairable'])
        self.assertTrue(validate_answer('{broken',[],'2036-03-04')['repairable'])
    def test_empty_list_can_be_cited_but_records_cannot(self):
        q=self.query();q['result']['latest_return_estimates']=[];q['result']['rows'][0]['history']=[{'date':'2036-01-01'}]
        doc=json.loads(self.doc());doc['facts'].append(dict(query=0,path=['latest_return_estimates'],value=[]))
        self.assertTrue(validate_answer(json.dumps(doc),[q],'2036-03-04')['passed'])
        doc['facts'][-1]=dict(query=0,path=['rows',0,'history'],value=[{'date':'2036-01-01'}])
        self.assertFalse(validate_answer(json.dumps(doc),[q],'2036-03-04')['passed'])
    def test_fixes_replace_only_failed_references(self):
        from src.evidence_gate import apply_fixes,failed_references
        draft=json.dumps(dict(season='2035/36',comparison_player_ids=[],facts=[dict(query=0,path=['a'],value=1),dict(query=0,path=['b'],value=2)],analysis="Unchanged prose"))
        self.assertEqual(failed_references(["Reference 2: query 0 ...","Reference 2: other"]),[2])
        self.assertIsNone(failed_references(["Reference 2: x","Query cutoff date mismatch"]))
        raw,removed=apply_fixes(draft,'```json\n{"fixes":[{"reference":2,"fact":null}]}\n```',[2])
        self.assertEqual(removed,1);self.assertEqual(json.loads(raw)['facts'],[dict(query=0,path=['a'],value=1)]);self.assertEqual(json.loads(raw)['analysis'],"Unchanged prose")
        for bad in ('{"fixes":[]}','{"fixes":[{"reference":1,"fact":null}]}','{"fixes":[{"reference":2,"fact":5}]}','[]'):
            with self.assertRaises(ValueError):apply_fixes(draft,bad,[2])
    def test_invalid_draft_never_published(self):
        r=validate_answer("Already champions!",[],'2036-03-04',"Is the championship secure")
        self.assertFalse(r['passed']);self.assertNotIn("Already champions!",r['text'])
if __name__=='__main__':unittest.main()
