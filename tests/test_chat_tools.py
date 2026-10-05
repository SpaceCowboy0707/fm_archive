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
        self.assertEqual(self.tools.execute('find_players',dict(query="' OR 1=1 --",offset=0))['field'],'query')
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

    def test_club_names_match_across_languages_and_short_forms(self):
        from src.chat_tools import match_clubs
        clubs=[(673,'莱斯特城足球俱乐部'),(679,'曼彻斯特城足球俱乐部'),(680,'曼联足球俱乐部'),(728,'托特纳姆热刺足球俱乐部')]
        uids=lambda q:[u for u,_ in match_clubs(q,clubs)]
        for query in ('Leicester','leicester city f.c.','Leicester City FC','莱斯特','莱斯特城足球俱乐部','狐狸城','673'):
            self.assertEqual(uids(query),[673],query)
        self.assertEqual(uids('Man City'),[679]);self.assertEqual(uids('曼城'),[679])
        self.assertEqual(uids('Man Utd'),[680]);self.assertEqual(uids('Spurs'),[728]);self.assertEqual(uids('热刺'),[728])
        self.assertEqual(uids('Manchester'),[679,680])
        self.assertEqual(uids('Chelsea'),[]);self.assertEqual(uids('FC'),[])

    def test_player_search_hints_transliteration_and_spelling(self):
        cjk=self.tools.execute('find_players',dict(query='卡马尔达',offset=0))
        self.assertEqual(cjk['field'],'query');self.assertIn('Latin script',cjk['error'])
        typo=self.tools.execute('find_players',dict(query='Paje',offset=0))
        self.assertEqual(typo['expected'],['Louis Page'])
        self.assertIn('Latin script',self.tools.execute('transfer_history',dict(player_name='佩奇',start_date='2035-07-01',end_date='2036-02-11',offset=0))['error'])

    def test_transfer_history_merges_screenshots_without_leaking_fields(self):
        con=sqlite3.connect(self.db)
        event=dict(player_name='Louis Page',direction='out',kind='loan',date='2035-08-01',other_club='Loan club',fee_display='Loan',fee_eur_displayed=None,note='',secret='DO_NOT_SEND')
        con.execute('INSERT INTO transfer_events VALUES(?,?,?)',(1,'2035-08-01',json.dumps(event)));con.commit();con.close()
        r=self.tools.execute('transfer_history',dict(player_name='page',start_date='2035-07-01',end_date='2036-02-11',offset=0))
        self.assertEqual(r['total'],1);row=r['rows'][0]
        self.assertEqual((row['movement'],row['source'],row['club'],row['date']),('loaned_out','screenshot','Loan club','2035-08-01'))
        self.assertNotIn('DO_NOT_SEND',json.dumps(r))
        self.assertEqual(self.tools.execute('transfer_history',dict(player_name=None,start_date='2035-09-01',end_date='2036-02-11',offset=0))['total'],0)

    def test_club_squad_reads_the_latest_club_snapshot(self):
        con=sqlite3.connect(self.db)
        data=json.loads(con.execute("SELECT payload_json FROM analytics_snapshots WHERE sha256='2'").fetchone()[0])
        from src.analytics import FINANCE_FIELDS, PLAYER_FIELDS
        from src.safe_export import ATTRIBUTES
        def record(name,slot,status,membership='registered',on_loan=False,club='Leicester'):
            player={**dict.fromkeys(PLAYER_FIELDS),**dict(identity_key=name,name=name,age=24,natural_positions=['DC'],squad_status=status,team_slot=slot,contract_end='2039-06-30',
                    on_loan=on_loan,loan_parent_club_name='Parent' if on_loan else None,club_name=club,attributes={**dict.fromkeys(ATTRIBUTES,10),'tackling':15})}
            return {**dict.fromkeys(FINANCE_FIELDS),**dict(player=player,membership=membership,loan_end='2037-01-04' if membership=='loan_out' else None,wage_weekly=1)}
        data['players']=[record('Rotation',0,'squad_player'),record('Star',0,'star_player'),record('Loanee',0,'regular_starter',on_loan=True),
                         record('Kid',1,'youngster'),record('Away',0,'impact_sub','loan_out',club='Loan club')]
        con.execute("UPDATE analytics_snapshots SET payload_json=? WHERE sha256='2'",(json.dumps(data),));con.commit();con.close()
        first=self.tools.execute('club_squad',dict(group='first_team',detail='summary',offset=0))
        self.assertEqual([r['name'] for r in first['rows']],['Star','Loanee','Rotation'])
        self.assertEqual((first['as_of'],first['counts']),('2036-02-11',dict(first_team=3,youth=1,loaned_out=1)))
        self.assertEqual(first['rows'][1]['loan_in_from'],'Parent');self.assertNotIn('attributes',first['rows'][0])
        away=self.tools.execute('club_squad',dict(group='loaned_out',detail='attributes',offset=0))['rows'][0]
        self.assertEqual((away['loaned_to'],away['loan_end'],away['attributes']['tackling']),('Loan club','2037-01-04',15))
        self.assertNotIn('wage_weekly',json.dumps(away))
        self.assertEqual(self.tools.execute('club_squad',dict(group='all',detail='summary',offset=0))['total'],5)

    def test_rows_carry_their_position_for_evidence_paths(self):
        rows=self.tools.execute('find_players',dict(query='Page',offset=0))['rows']
        self.assertEqual([r['row_index'] for r in rows],list(range(len(rows))))
        self.assertEqual(list(rows[0])[0],'row_index')

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

    def test_independent_calls_share_one_round(self):
        calls=[dict(type='function_call',call_id=str(i),name=name,arguments=args) for i,(name,args) in enumerate(
            [('find_players','{"query":"Page","offset":0}'),('archive_coverage','{}'),('find_players','{"query":"Shaw","offset":0}')])]
        bodies=[];traces=[]
        replies=iter([Stream(calls),Stream(text='Answer')])
        def post(*args,**kwargs):bodies.append(kwargs['json']);return next(replies)
        with patch.object(auth,'access_token',return_value='synthetic'),patch.object(auth.requests,'post',side_effect=post):
            text=''.join(auth.stream_reply('cid','model',[dict(role='user',content='Question')],'',TOOLS,lambda n,a:{'rows':[]},traces.append))
        self.assertEqual(text,'Answer');self.assertEqual(len(bodies),2)
        self.assertTrue(bodies[0]['parallel_tool_calls'])
        self.assertEqual([t['result']['query_index'] for t in traces],[0,1,2])
        self.assertEqual([i['call_id'] for i in bodies[1]['input'] if i.get('type')=='function_call_output'],['0','1','2'])

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

    def test_text_in_a_required_round_retries_once_without_forcing_tools(self):
        class Stopped(Stream):
            def iter_lines(self,**kwargs):
                yield 'data: '+json.dumps(dict(type='response.output_text.delta',delta='No data yet'))
                yield 'data: '+json.dumps(dict(type='response.incomplete',response=dict(incomplete_details=dict(reason='max_messages'))))
        coverage=dict(type='function_call',call_id='0',name='archive_coverage',arguments='{}')
        bodies=[];events=[]
        replies=iter([Stream([coverage]),Stopped(),Stream(text='The archive has no 2036/37 data yet')])
        def post(*args,**kwargs):bodies.append(kwargs['json']);return next(replies)
        with patch.object(auth,'access_token',return_value='synthetic'),patch.object(auth.requests,'post',side_effect=post):
            text=''.join(auth.stream_reply('cid','model',[],'',TOOLS,lambda *a:{'rows':[]},on_event=events.append,require_lookup=True,final_text_only=True))
        self.assertEqual(text,'The archive has no 2036/37 data yet')
        self.assertEqual([b['tool_choice'] for b in bodies],['required','required','auto'])
        self.assertIn('No archive data query has succeeded yet',bodies[2]['instructions'])
        self.assertIn('tool_choice_relaxed',[e['kind'] for e in events])
        replies=iter([Stopped(),Stopped()])
        with patch.object(auth,'access_token',return_value='synthetic'),patch.object(auth.requests,'post',side_effect=post):
            with self.assertRaisesRegex(auth.ConnectionFailure,'max_messages'):
                list(auth.stream_reply('cid','model',[],'',TOOLS,lambda *a:{'rows':[]},require_lookup=True,final_text_only=True))

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
