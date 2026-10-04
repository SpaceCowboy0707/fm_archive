import tempfile,unittest,json
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch,MagicMock
from src import web_chat as web,chat_store as store

class WebJobTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'chat.sqlite3';self.stack=ExitStack();self.addCleanup(self.stack.close)
        original_connect=store.connect
        self.stack.enter_context(patch.object(store,'connect',side_effect=lambda *a,**kw:original_connect(self.db)))
        for name in ('chats','messages','save_queries','save_workflow','remember_model','collected_lore'):
            original=getattr(store,name)
            self.stack.enter_context(patch.object(store,name,side_effect=lambda *a,_f=original,**kw:_f(*a,**{**kw,'db':self.db})))
        self.room=store.create_chat('test',self.db,mode='analysis');web.init()
        self.stack.enter_context(patch.object(web,'snapshots',return_value=[dict(id=1,game_date='2036-04-03',club_uid=673)]))
        self.stack.enter_context(patch.object(web.auth,'account_options',return_value=({'account':'test'},'account')))
        self.stack.enter_context(patch.object(web,'catalog',return_value=[dict(slug='test')]))
        self.thread=self.stack.enter_context(patch.object(web.threading,'Thread'))
        self.args=dict(request_id='request-test-00000001',chat_id=self.room,question="Analyze the squad",snapshot_id=1,season='2035/36',account='account',model='test',people=[])
    def test_idempotent_submit_and_restart(self):
        a=web.submit(self.args);b=web.submit(self.args)
        self.assertEqual(a['id'],b['id']);self.assertEqual(len(store.messages(self.room)),2)
        self.assertEqual(self.thread.call_count,1)
        with self.assertRaises(ValueError):web.submit({**self.args,'request_id':'another-request-00001'})
        web.init();self.assertEqual(web.jobs(self.room)[0]['state'],'interrupted')
        self.assertIn("service restarted",store.messages(self.room)[-1]['text'])
    def test_worker_persists_tool_result_and_answer(self):
        r=web.submit(self.args)
        tool=MagicMock();tool._data.return_value=[]
        self.stack.enter_context(patch.object(web,'ArchiveTools',return_value=tool))
        self.stack.enter_context(patch.object(web,'squad',return_value=[]));self.stack.enter_context(patch.object(web,'load_lore',return_value=[]))
        def stream(*args,**kw):
            kw['on_tool'](dict(name='season_statistics',arguments={'season':'2035/36'},result=dict(snapshot_date='2036-04-03',rows=[{'goals':10}],total=1,offset=0,next_offset=None)))
            yield json.dumps(dict(season='2035/36',comparison_player_ids=[],facts=[dict(query=0,path=['rows',0,'goals'],value=10)],analysis="Analysis of available data"))
        self.stack.enter_context(patch.object(web.auth,'stream_reply',side_effect=stream))
        with store.connect() as c:cfg=json.loads(c.execute('select config from web_jobs').fetchone()[0])
        web.run(r['id'],self.room,r['assistant_id'],cfg)
        m=store.messages(self.room)[-1]
        self.assertEqual(m['status'],'complete');self.assertIn("Analysis of available data",m['text']);self.assertEqual(len(m['queries']),1)
        self.assertEqual(web.jobs(self.room)[0]['state'],'complete')
    def test_failed_references_get_one_tool_free_repair(self):
        r=web.submit(self.args)
        tool=MagicMock();tool._data.return_value=[]
        self.stack.enter_context(patch.object(web,'ArchiveTools',return_value=tool))
        self.stack.enter_context(patch.object(web,'squad',return_value=[]));self.stack.enter_context(patch.object(web,'load_lore',return_value=[]))
        answer=lambda row:json.dumps(dict(season='2035/36',comparison_player_ids=[],facts=[dict(query=0,path=['rows',row,'goals'],value=31)],analysis="Camarda scored 31"))
        calls=[]
        def stream(*args,**kw):
            calls.append(kw)
            if len(calls)==1:
                kw['on_tool'](dict(name='season_statistics',arguments={'season':'2035/36'},result=dict(query_index=0,snapshot_date='2036-04-03',total=2,offset=0,next_offset=None,rows=[dict(row_index=0,goals=4),dict(row_index=1,goals=31)])))
                yield answer(0)
            else:
                self.assertIsNone(kw.get('tools'))
                self.assertIn("cites 31, but the tool returned 4",args[2][-1]['content'])
                yield answer(1)
        self.stack.enter_context(patch.object(web.auth,'stream_reply',side_effect=stream))
        with store.connect() as c:cfg=json.loads(c.execute('select config from web_jobs').fetchone()[0])
        web.run(r['id'],self.room,r['assistant_id'],cfg)
        self.assertEqual(len(calls),2)
        m=store.messages(self.room)[-1]
        self.assertEqual(m['status'],'complete');self.assertIn("Camarda scored 31",m['text'])
        kinds=[e['kind'] for e in m['workflow']]
        self.assertLess(kinds.index('evidence_check'),kinds.index('evidence_repair'));self.assertIn('evidence_recheck',kinds)
    def test_failure_keeps_question_and_logs(self):
        r=web.submit(self.args)
        self.stack.enter_context(patch.object(web,'ArchiveTools',side_effect=RuntimeError('synthetic')))
        with store.connect() as c:cfg=json.loads(c.execute('select config from web_jobs').fetchone()[0])
        web.run(r['id'],self.room,r['assistant_id'],cfg)
        self.assertEqual(store.messages(self.room)[-1]['status'],'incomplete')
        self.assertEqual(web.jobs(self.room)[0]['state'],'failed')
        self.assertEqual(store.messages(self.room)[0]['text'],"Analyze the squad")
