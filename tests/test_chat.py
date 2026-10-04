import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from src import chat_store as store
from src import chat_auth as auth

class ChatTests(unittest.TestCase):
    def test_injuries_have_date_cutoff_provenance_and_no_stale_return_estimates(self):
        import json
        def row(day,kind='history'):
            return dict(identity_key='p',player_uid=1,player_name='Player',kind=kind,date=day,
                        team_id=1,type_id=9,type_name=None,severity='major',cause='in_match',secret='DO_NOT_SEND')
        event=row('2035-11-07')
        data=[dict(snapshot={'date':'2035-12-01'},injuries=[event,row('2036-01-10','typed'),row('2034-09-01')]),
              dict(snapshot={'date':'2036-02-11'},injuries=[event],checks=[dict(reader='injuries',status='partial')]),
              dict(snapshot={'date':'2036-04-01'},injuries=[row('2036-03-01')])]
        medical=store.injury_context(data,{'game_date':'2036-02-11'},'2035/36')
        self.assertEqual(len(medical['historical_events']),1)
        self.assertEqual(medical['historical_events'][0]['as_of'],'2036-02-11')
        self.assertIsNone(medical['historical_events'][0]['type_name'])
        self.assertEqual(medical['latest_return_estimates'],[])
        self.assertEqual(medical['extraction_checks'][0]['status'],'partial')
        payload=store.context_for([],[],[],'2035/36',injuries=medical)
        self.assertNotIn('DO_NOT_SEND',payload)
        self.assertEqual(json.loads(payload)['injury_records']['historical_events'][0]['severity'],'major')
        old=store.injury_context(data,{'game_date':'2035-12-01'},'2035/36')
        self.assertEqual(old['latest_return_estimates'][0]['date'],'2036-01-10')
        self.assertEqual(store.injury_context([],{'game_date':'2036-02-11'},'bad')['historical_events'],[])

    def test_spaces_preserve_independent_history_and_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'chat.db'
            a=store.create_chat('Analysis',db,mode='analysis')
            b=store.create_chat('Story',db,mode='story')
            store.save_message(a,'user','Stats question',db=db)
            store.save_message(b,'user','Story question',db=db)
            store.remember_model(a,'analysis','model-a',db)
            store.remember_model(b,'story','model-b',db)
            rooms={r['id']:r for r in store.chats(db)}
            self.assertEqual(rooms[a]['model'],'model-a')
            self.assertEqual(rooms[b]['mode'],'story')
            self.assertEqual([m['text'] for m in store.messages(a,db)],['Stats question'])
            self.assertIn("Do not proactively invent",store.instructions_for('analysis'))
            self.assertIn("fan fiction",store.instructions_for('story'))

    def test_empty_completion_fails_and_completed_stream_stops_immediately(self):
        import json
        class Response:
            status_code=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def iter_lines(self,**kwargs):
                if self.with_text:yield 'data: '+json.dumps({'type':'response.output_text.delta','delta':'OK'})
                yield 'data: '+json.dumps({'type':'response.completed'})
                raise AssertionError('Must not wait beyond completion')
        for has_text in (True,False):
            response=Response();response.with_text=has_text
            with patch.object(auth,'access_token',return_value='synthetic'),patch.object(auth.requests,'post',return_value=response):
                if has_text:self.assertEqual(''.join(auth.stream_reply('test','model',[],'')),'OK')
                else:
                    with self.assertRaisesRegex(auth.ConnectionFailure,"without displayable text"):list(auth.stream_reply('test','model',[],''))

    def test_transfer_history_is_available_without_player_selection(self):
        import json
        moves=[dict(player_name='Former player',date='2027-06-16',season='2027/28',direction='in',
                    other_club='Former club',fee_display='€18M',fee_eur_displayed=18000000,kind='transfer',note='',secret='DO_NOT_SEND')]
        for chosen in ([],[{'name':'Other player'}]):
            context=store.context_for(chosen,[],moves,'2035/36')
            parsed=json.loads(context)
            self.assertEqual(parsed['screenshot_transfers'][0]['player_name'],'Former player')
            self.assertEqual(parsed['transfer_coverage']['count'],1)
            self.assertNotIn('DO_NOT_SEND',context)

    def test_subscription_failure_has_specific_recovery_without_leaking_payload(self):
        for event in ({'type':'error','code':'subscription_sharing_usage_limit_exceeded','message':'SECRET'},
                      {'type':'response.failed','response':{'error':{'code':'subscription_sharing_usage_limit_exceeded','message':'SECRET'}}}):
            failure=auth.response_failure(event)
            self.assertEqual(failure.code,'subscription_sharing_usage_limit_exceeded')
            self.assertIn("app limits",str(failure))
            self.assertNotIn('SECRET',str(failure))

    pass  # Private integration fixture is intentionally not published.

    def test_sporting_context_matches_archive_and_excludes_future(self):
        from src.analytics import COUNTS
        row=dict.fromkeys(COUNTS,0)
        row.update(identity_key='p',player_name='Camarda',period='2035/36',kind='overall',team_id=1,
                   club_uid=1,club_name='Leicester',team_slot=0,starts=25,substitute_appearances=3,
                   goals=25,assists=3,minutes=2173,rated_appearances=28,average_rating=7.2,
                   hidden_test='DO_NOT_SEND')
        data=[{'snapshot':{'date':day},'season_stats':[{**row,'goals':goals}]} for day,goals in
              [('2035-12-01',20),('2035-12-29',25),('2036-01-01',30)]]
        result=store.sporting_context(data,{'game_date':'2035-12-29','club_uid':1},'2035/36')
        self.assertEqual(len(result['players']),1)
        self.assertEqual(result['players'][0]['goals'],25)
        self.assertEqual(result['players'][0]['appearances'],28)
        self.assertNotIn('DO_NOT_SEND',str(result))
        self.assertEqual(store.sporting_context(data,{'game_date':'2035-12-29','club_uid':1},'2034/35')['players'],[])
        self.assertEqual(store.sporting_context(data,{'game_date':'2035-12-29','club_uid':2},'2035/36')['players'],[])
        context=store.context_for([],[],[],'2035/36',result)
        self.assertIn('Camarda',context)
        import json
        table=json.loads(context)['season_statistics']['player_table']
        decoded=dict(zip(table['columns'],table['rows'][0]))
        self.assertEqual(len(table['columns']),len(table['rows'][0]))
        self.assertEqual(decoded['goals'],25)
        self.assertAlmostEqual(decoded['goals_per_90'],25*90/2173,places=5)
        self.assertIn('clear_cut_chances_created',decoded)
        self.assertIn('saves_tipped',decoded)
        self.assertIsNone(decoded['cross_completion_percent'])
        self.assertTrue(set(COUNTS).issubset(decoded))

    def test_collection_is_explicit_idempotent_and_headcanon(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'chat.db';room=store.create_chat('Test',db)
            user=store.save_message(room,'user','A story',db=db)
            incomplete=store.save_message(room,'assistant','Partial','incomplete',db=db)
            for key in (user,incomplete):
                with self.assertRaises(ValueError):store.collect(key,'Title','2031/32',[],db)
            message=store.save_message(room,'assistant','Complete story',db=db)
            self.assertEqual(store.collected_lore(db),[])
            for _ in range(2):store.collect(message,'Title','2031/32',[],db)
            lore=store.collected_lore(db)
            self.assertEqual(len(lore),1);self.assertEqual(lore[0]['level'],'headcanon')
            self.assertEqual(lore[0]['text'],'Complete story')
            self.assertIn(message,lore[0]['source'])
            self.assertEqual(len(store.messages(room,db)),3)

    def test_context_projects_only_selected_visible_fields(self):
        p={'name':'Test','identity_key':'p','ability':'DO_NOT_SEND','attributes':{'anything':'DO_NOT_SEND'}}
        context=store.context_for([p],[],[],'2031/32')
        self.assertNotIn('DO_NOT_SEND',context)

    def test_nonce_and_plan_scope_must_both_validate(self):
        token={'id_token':'synthetic','access_token':'synthetic','token_type':'Bearer','scope':'openid'}
        responses=[{'issuer':auth.AUTH,'jwks_uri':auth.AUTH+'/keys'},{'keys':[{'kid':'test'}]}]
        with patch.object(auth,'request_json',side_effect=responses*2),patch.object(auth.jwt,'get_unverified_header',return_value={'kid':'test'}),patch.object(auth.jwt.PyJWK,'from_dict'),patch.object(auth.jwt,'decode',return_value={'sub':'test','nonce':'correct'}):
            with self.assertRaises(auth.ConnectionFailure):auth.validate_tokens(token,'cid','wrong')
            with self.assertRaises(auth.ConnectionFailure):auth.validate_tokens(token,'cid','correct')

    def test_stream_requires_completed_event(self):
        class Response:
            status_code=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def iter_lines(self,**kwargs):
                yield 'data: {"type":"response.output_text.delta","delta":"test"}'
        with patch.object(auth,'access_token',return_value='synthetic'),patch.object(auth.requests,'post',return_value=Response()):
            with self.assertRaises(auth.ConnectionFailure):list(auth.stream_reply('cid','model',[],''))

    pass  # Private integration fixture is intentionally not published.
