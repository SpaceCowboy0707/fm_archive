import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import chat_auth as auth, chat_store as store
from src.chat_tools import ArchiveTools, TOOLS
from src.analytics import COUNTS, INJURY_FIELDS


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'archive.sqlite3'
        con=sqlite3.connect(self.db)
        con.executescript('''CREATE TABLE snapshots(id,game_date);
            CREATE TABLE player_snapshots(snapshot_id,identity_key,visible_json);
            CREATE TABLE analytics_snapshots(sha256,game_date,payload_json);
            CREATE TABLE transfer_events(id,date,payload_json);''')
        for n,day,goals in [(1,'2035-12-01',3),(2,'2036-02-11',5),(3,'2036-05-01',99)]:
            con.execute('INSERT INTO snapshots VALUES(?,?)',(n,day))
            con.execute('INSERT INTO player_snapshots VALUES(?,?,?)',(n,'p',json.dumps(dict(name='Louis Page',birth_date='2008-07-10',hidden_test='DO_NOT_SEND'))))
            stats=dict.fromkeys(COUNTS,0)
            stats.update(player_uid=1,player_name='Louis Page',identity_key='p',period='2035/36',kind='overall',
                         team_id=1,club_uid=1,club_name='Leicester',team_slot=0,goals=goals,minutes=90,starts=1,rated_appearances=1,average_rating=7.)
            injury={**dict.fromkeys(INJURY_FIELDS),**dict(identity_key='p',player_uid=1,player_name='Louis Page',kind='history',date='2035-11-07',team_id=1,type_id=None,type_name=None,severity='major')}
            data=dict(schema_version=1,snapshot=dict(date=day,sha256=str(n),club_uid=1,source_file='test.fm'),players=[],checks=[],season_stats=[stats],injuries=[injury],matches=[],fixtures=[],contracts=[],competitions=[])
            if n==1:data['injuries'].append({**injury,'kind':'typed','date':'2036-01-01'})
            con.execute('INSERT INTO analytics_snapshots VALUES(?,?,?)',(str(n),day,json.dumps(data)))
        con.commit();con.close()
        self.tools=ArchiveTools(dict(game_date='2036-02-11',club_uid=1),self.db)

    def test_profile_attributes_cutoff_and_match_appearance_status(self):
        from src.analytics import MATCH_FIELDS
        con=sqlite3.connect(self.db)
        person=dict(name='Louis Page',attributes={'reflexes':15,'potential_ability':200})
        con.execute('UPDATE player_snapshots SET visible_json=? WHERE snapshot_id=2',(json.dumps(person),))
        data=json.loads(con.execute("SELECT payload_json FROM analytics_snapshots WHERE sha256='2'").fetchone()[0])
        for n,(minutes,valid) in enumerate([(90,True),(0,True),(90,False)]):
            row=dict.fromkeys(MATCH_FIELDS)
            row.update(identity_key='p',player_uid=1,player_name='Louis Page',date='2036-02-01',competition_id=1,opponent_team_id=n,has_stats=valid,stats_in_range=valid,minutes=minutes,competition_key='db:1',own_club_uid=1,own_club_name='Club',own_team_slot=0,attribution='matched_fixture',period='2035/36')
            data['matches'].append(row)
        con.execute("UPDATE analytics_snapshots SET payload_json=? WHERE sha256='2'",(json.dumps(data),))
        con.commit();con.close()
        r=self.tools.execute('player_profile',dict(player_id='p',season='2035/36'))
        self.assertEqual(r['rows'][0]['attributes']['reflexes'],15)
        self.assertNotIn('potential_ability',json.dumps(r))
        self.assertEqual(r['rows'][0]['attributes_as_of'],'2036-02-11')
        self.assertNotIn(99,[x['goals'] for x in r['season_statistics']])
        r=self.tools.execute('player_timeline',dict(player_id='p',start_date='2036-02-01',end_date='2036-02-11',section='matches',offset=0))
        self.assertEqual([x['appearance_status'] for x in r['rows']],['confirmed_minutes','zero_minutes_record','unverified'])

    def test_gated_stream_does_not_publish_tool_round_draft(self):
        call=dict(type='function_call',call_id='one',name='archive_coverage',arguments='{}')
        with patch.object(auth,'access_token',return_value='synthetic'),patch.object(auth.requests,'post',side_effect=[Stream([call],text="Unverified draft"),Stream(text="Final structure")]):
            text=''.join(auth.stream_reply('test','model',[],'',tools=TOOLS,execute_tool=self.tools.execute,final_text_only=True))
        self.assertEqual(text,"Final structure")

    def test_readonly_validation_and_safe_search(self):
        before=self.db.read_bytes()
        self.assertEqual(self.tools.execute('find_players',dict(query='Page',offset=0))['total'],1)
        self.assertNotIn('DO_NOT_SEND',json.dumps(self.tools.execute('find_players',dict(query='Page',offset=0))))
        self.assertIn('error',self.tools.execute('run_sql',dict(query='DROP TABLE snapshots')))
        self.assertIn('error',self.tools.execute('find_players',dict(query='Page',offset=-1)))
        self.assertEqual(self.tools.execute('find_players',dict(query="' OR 1=1 --",offset=0))['total'],0)
        con=self.tools._connect()
        with self.assertRaises(sqlite3.OperationalError):con.execute('DELETE FROM snapshots')
        con.close()
        self.assertEqual(before,self.db.read_bytes())

    def test_cutoff_dedup_missing_injuries_and_cumulative_timeline(self):
        args=dict(season='2035/36',player_id='p',kind='overall',scope='all',offset=0)
        result=self.tools.execute('season_statistics',args)
        self.assertEqual(result['rows'][0]['goals'],5)
        self.assertEqual(result['total'],1)
        args=dict(player_id='p',start_date='2035-10-01',end_date='2036-02-11',offset=0)
        injuries=self.tools.execute('injury_history',args)
        self.assertEqual(injuries['total'],1)
        self.assertIsNone(injuries['rows'][0]['type_name'])
        self.assertEqual(injuries['latest_return_estimates'],[])
        rows=self.tools.execute('player_timeline',{**args,'section':'snapshots'})['rows']
        self.assertEqual([r['goals'] for r in rows],[3,5])
        self.assertIn('error',self.tools.execute('injury_history',{**args,'end_date':'2036-05-01'}))
        self.assertIn('error',self.tools.execute('injury_history',{**args,'player_id':'invented'}))

    def test_argument_errors_name_the_field_for_self_correction(self):
        args=dict(player_id='p',start_date='2035-10-01',end_date='2036-02-11',offset=0)
        late=self.tools.execute('injury_history',{**args,'end_date':'2036-05-01'})
        self.assertEqual((late['error_type'],late['field'],late['received'],late['retryable']),('invalid_arguments','end_date','2036-05-01',True))
        self.assertIn('2036-02-11',late['error'])
        self.assertEqual(self.tools.execute('injury_history',{**args,'start_date':'2035-02-30'})['field'],'start_date')
        self.assertEqual(self.tools.execute('injury_history',{**args,'player_id':'invented'})['field'],'player_id')
        season=self.tools.execute('season_statistics',dict(season='2035-36',player_id=None,kind='overall',scope='all',offset=0))
        self.assertEqual((season['field'],season['received']),('season','2035-36'))
        kind=self.tools.execute('season_statistics',dict(season='2035/36',player_id=None,kind='league_cup',scope='all',offset=0))
        self.assertEqual(kind['field'],'kind');self.assertIn('continental',kind['expected'])
        missing=self.tools.execute('find_players',dict(query='Page'))
        self.assertEqual(missing['field'],'offset');self.assertIn('offset',missing['error'])
        self.assertEqual(self.tools.execute('find_players','{not json')['field'],'arguments')
        unknown=self.tools.execute('run_sql',dict(query='x'))
        self.assertEqual(unknown['field'],'name');self.assertIn('find_players',unknown['expected'])

    def test_pagination_and_trace_persistence(self):
        first=self.tools._page([{'n':i} for i in range(50)],0)
        second=self.tools._page([{'n':i} for i in range(50)],first['next_offset'])
        self.assertEqual(len(first['rows'])+len(second['rows']),50)
        self.assertIsNone(second['next_offset'])
        db=Path(self.tmp.name)/'chat.sqlite3'
        room=store.create_chat('test',db)
        mid=store.save_message(room,'assistant','reply',db=db)
        store.save_queries(mid,[{'name':'find_players','result':first}],db)
        self.assertEqual(store.messages(room,db)[0]['queries'][0]['result']['total'],50)

    def test_stopped_generation_retains_query_and_interruption(self):
        from streamlit.testing.v1 import AppTest
        from streamlit.runtime.scriptrunner_utils.exceptions import StopException
        from contextlib import ExitStack
        from src import chat_ui
        db=Path(self.tmp.name)/'stopped-chat.sqlite3'
        room=store.create_chat('test',db)
        store.remember_model(room,'story','test-model',db)
        original={name:getattr(store,name) for name in ('chats','messages','save_message','save_queries','save_workflow')}
        def interrupted(*args,**kwargs):
            kwargs['on_tool']({'name':'archive_coverage','arguments':{},'result':{'snapshot_date':'2036-02-11'}})
            raise StopException()
            yield ''
        with ExitStack() as stack:
            for name in original:
                stack.enter_context(patch.object(store,name,side_effect=lambda *args,_name=name,**kwargs:original[_name](*args,**{**kwargs,'db':db})))
            stack.enter_context(patch.object(auth,'account_options',return_value=({'cid':'Test'},'cid')))
            stack.enter_context(patch.object(auth,'models',return_value=[dict(slug='test-model')]))
            stack.enter_context(patch.object(auth,'stream_reply',side_effect=interrupted))
            stack.enter_context(patch.object(chat_ui,'read_transfers',return_value=([],[])))
            app=AppTest.from_string("from src.chat_ui import render\nrender([],[],{'game_date':'2036-02-11','club_uid':1},[])").run(timeout=30)
            next(x for x in app.text_input if x.label=="Message").set_value("Query")
            next(x for x in app.button if x.label=="Send").click().run(timeout=30)
        saved=original['messages'](room,db)
        self.assertEqual(saved[-1]['status'],'incomplete')
        self.assertEqual(saved[-1]['queries'][0]['name'],'archive_coverage')
        self.assertEqual(saved[-1]['workflow'][-1]['kind'],'interrupted')

    def test_chat_ui_executes_tools_and_retains_trace_after_rerun(self):
        from streamlit.testing.v1 import AppTest
        from contextlib import ExitStack
        from src import chat_ui
        db=Path(self.tmp.name)/'ui-chat.sqlite3'
        room=store.create_chat('test',db)
        store.remember_model(room,'story','test-model',db)
        original={name:getattr(store,name) for name in ('chats','messages','save_message','save_queries','save_workflow')}
        def bound(name):
            return lambda *args,**kwargs:original[name](*args,**{**kwargs,'db':db})
        call=dict(type='function_call',call_id='one',name='archive_coverage',arguments='{}')
        with ExitStack() as stack:
            for name in original:stack.enter_context(patch.object(store,name,side_effect=bound(name)))
            stack.enter_context(patch.object(auth,'account_options',return_value=({'cid':'Test'},'cid')))
            stack.enter_context(patch.object(auth,'models',return_value=[dict(slug='test-model')]))
            stack.enter_context(patch.object(auth,'access_token',return_value='synthetic'))
            stack.enter_context(patch.object(auth.requests,'post',side_effect=[Stream([call]),Stream([dict(type='function_call',call_id='two',name='season_statistics',arguments=json.dumps(dict(season='2035/36',player_id=None,kind='overall',scope='all',offset=0)))]),Stream(text=json.dumps(dict(season='2035/36',comparison_player_ids=[],facts=[dict(query=1,path=['rows',0,'goals'],value=5)],analysis="The archive date was retrieved.")))]))
            stack.enter_context(patch.object(chat_ui,'read_transfers',return_value=([],[])))
            stack.enter_context(patch.object(chat_ui,'ArchiveTools',return_value=self.tools))
            app=AppTest.from_string("from src.chat_ui import render\nrender([],[],{'game_date':'2036-02-11','club_uid':1},[])").run(timeout=30)
            self.assertFalse(app.exception)
            next(x for x in app.text_input if x.label=="Message").set_value("Check archive coverage")
            next(x for x in app.button if x.label=="Send").click().run(timeout=30)
            self.assertFalse(app.exception)
            saved=original['messages'](room,db)
            app.session_state['turn_'+saved[0]['id']]=True
            app.run(timeout=30)
            self.assertTrue(any("Tool calls and SQL" in x.label for x in app.expander))
        history=original['messages'](room,db)
        self.assertIn("The archive date was retrieved.",history[-1]['text'])
        self.assertNotIn("Verified fields",history[-1]['text'])
        evidence=next(e['details'] for e in history[-1]['workflow'] if e['kind']=='evidence_check')
        self.assertTrue(evidence['verified_facts'])
        self.assertIn('goals',str(evidence['verified_facts']))
        self.assertEqual(history[-1]['status'],'complete')
        self.assertEqual(history[-1]['queries'][0]['name'],'archive_coverage')
        events=history[-1]['workflow']
        kinds=[e['kind'] for e in events]
        for kind in ('input','model_request','model_accepted','tool_requested','sqlite_read','tool_result','completed'):
            self.assertIn(kind,kinds)
        self.assertLess(kinds.index('tool_requested'),kinds.index('sqlite_read'))
        self.assertLess(kinds.index('sqlite_read'),kinds.index('tool_result'))
        sql=next(e['details'] for e in events if e['kind']=='sqlite_read')
        self.assertIn('SELECT',sql['sql'])
        self.assertEqual(sql['parameters'],['2036-02-11'])
        self.assertEqual(sql['database_rows'],2)
        self.assertNotIn('synthetic',json.dumps(events))
        self.assertNotIn('DO_NOT_SEND',json.dumps(events))


class Stream:
    status_code=200
    def __init__(self,output=None,text='',complete=True):self.output=output or [];self.text=text;self.complete=complete
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def iter_lines(self,**kwargs):
        if self.text:yield 'data: '+json.dumps(dict(type='response.output_text.delta',delta=self.text))
        if self.complete:yield 'data: '+json.dumps(dict(type='response.completed',response=dict(output=self.output)))


class AgentLoopTests(unittest.TestCase):
    def test_model_can_read_then_choose_followup_and_answer(self):
        reasoning=dict(type='reasoning',id='r',summary=[],encrypted_content='opaque')
        search=dict(type='function_call',call_id='one',name='find_players',arguments='{"query":"Page","offset":0}')
        followup=dict(type='function_call',call_id='two',name='archive_coverage',arguments='{}')
        bodies=[];traces=[];executed=[]
        replies=iter([Stream([reasoning,search]),Stream([followup]),Stream(text='Evidence-based reply')])
        def post(*args,**kwargs):bodies.append(kwargs['json']);return next(replies)
        def execute(name,args):executed.append(name);return {'rows':[{'identity_key':'p'}]}
        with patch.object(auth,'access_token',return_value='synthetic'),patch.object(auth.requests,'post',side_effect=post):
            text=''.join(auth.stream_reply('cid','model',[dict(role='user',content='Question')],'',TOOLS,execute,traces.append))
        self.assertEqual(text,'Evidence-based reply')
        self.assertEqual(executed,['find_players','archive_coverage'])
        self.assertEqual(len(traces),2)
        self.assertIn(reasoning,bodies[1]['input'])
        self.assertEqual(bodies[1]['input'][-1]['call_id'],'one')
        self.assertIn('identity_key',bodies[1]['input'][-1]['output'])
        self.assertEqual(bodies[2]['input'][-1]['call_id'],'two')
        self.assertTrue(all(b['store'] is False for b in bodies))

    def test_required_lookup_rejects_no_tool_answer(self):
        with patch.object(auth,'access_token',return_value='synthetic'),patch.object(auth.requests,'post',return_value=Stream(text='Unchecked answer')):
            with self.assertRaisesRegex(auth.ConnectionFailure,"returned no tool request"):
                list(auth.stream_reply('cid','model',[],'',TOOLS,lambda *a:{},require_lookup=True))

    def test_required_until_data_not_just_directory(self):
        calls=[dict(type='function_call',call_id=str(n),name=name,arguments='{}') for n,name in enumerate(['find_players','archive_coverage','season_statistics'])]
        bodies=[]
        replies=iter([*(Stream([c]) for c in calls),Stream(text='Checked answer')])
        def post(*args,**kwargs):bodies.append(kwargs['json']);return next(replies)
        with patch.object(auth,'access_token',return_value='synthetic'),patch.object(auth.requests,'post',side_effect=post):
            self.assertEqual(''.join(auth.stream_reply('cid','model',[],'',TOOLS,lambda *a:{'rows':[]},require_lookup=True)),'Checked answer')
        self.assertEqual([b['tool_choice'] for b in bodies],['required','required','required','auto'])

    def test_light_background_has_no_bulk_statistics(self):
        data=[dict(snapshot=dict(date='2036-02-11'),season_stats=[dict(period='2035/36',goals=999999)])]
        background=store.lookup_context([],[],data,dict(game_date='2036-02-11'),'2035/36','overall','first_team')
        self.assertNotIn('999999',background)
        self.assertNotIn('screenshot_transfers',background)
        self.assertIn('2035/36',background)

    def test_unfinished_stream_never_executes_query(self):
        execute=[]
        with patch.object(auth,'access_token',return_value='synthetic'),patch.object(auth.requests,'post',return_value=Stream(complete=False)):
            with self.assertRaises(auth.ConnectionFailure):list(auth.stream_reply('cid','model',[],'',TOOLS,lambda *a:execute.append(a)))
        self.assertEqual(execute,[])

    def test_loop_limit_gets_one_final_response_without_tools(self):
        call=dict(type='function_call',call_id='one',name='archive_coverage',arguments='{}')
        bodies=[];executed=[]
        def post(*args,**kwargs):
            body=kwargs['json'];bodies.append(body)
            return Stream(text='Partial findings') if body['tool_choice']=='none' else Stream([call])
        with patch.object(auth,'access_token',return_value='synthetic'),patch.object(auth.requests,'post',side_effect=post):
            result=''.join(auth.stream_reply('cid','model',[],'',TOOLS,lambda *a:executed.append(a) or {}))
        self.assertEqual(result,'Partial findings')
        self.assertEqual(len(executed),6)
        self.assertEqual(len(bodies),7)

    def test_unknown_tool_is_not_executed(self):
        call=dict(type='function_call',call_id='one',name='delete_database',arguments='{}')
        executed=[]
        with patch.object(auth,'access_token',return_value='synthetic'),patch.object(auth.requests,'post',side_effect=[Stream([call]),Stream(text='Unavailable')]):
            self.assertEqual(''.join(auth.stream_reply('cid','model',[],'',TOOLS,lambda *a:executed.append(a))),'Unavailable')
        self.assertEqual(executed,[])
