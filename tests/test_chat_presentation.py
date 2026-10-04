import json
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from src.chat_ui import conversation_turns
from src.chat_trace import usage_summary
from src import chat_auth as auth

class PresentationTests(unittest.TestCase):
    def test_collapsed_turns_and_nested_trace(self):
        script='''from src.chat_ui import render_history
history=[dict(id='u',role='user',text='How is this season going?',status='complete'),dict(id='a',role='assistant',text='Statistics reply',status='complete',workflow=[dict(kind='sqlite_read',title='Query',details={'sql':'SELECT 1','parameters':[]})],queries=[])]
render_history(history,'analysis','test','2035/36',[])
'''
        app=AppTest.from_string(script).run()
        self.assertFalse(app.exception)
        self.assertIn("How is this season going",app.expander[0].label)
        self.assertFalse(app.expander[0].proto.expanded)
        self.assertEqual(len(app.expander),1)
        app.session_state['turn_u']=True
        app.run()
        self.assertEqual(app.expander[1].label,"Tool calls and SQL")
        self.assertFalse(app.expander[1].proto.expanded)
        self.assertEqual(len(app.chat_message),0)
        self.assertEqual(len(conversation_turns([{'role':'user','text':'1'},{'role':'user','text':'2'}])),2)

    def test_usage_is_service_reported_and_saved_as_event(self):
        class Response:
            status_code=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def iter_lines(self,**kwargs):
                yield 'data: '+json.dumps(dict(type='response.completed',response=dict(output=[dict(type='message',content=[dict(type='output_text',text='OK')])],usage=dict(input_tokens=100,output_tokens=20,total_tokens=120,input_tokens_details={'cached_tokens':40},output_tokens_details={'reasoning_tokens':10},secret='never'))))
        events=[]
        with patch.object(auth,'access_token',return_value='test'),patch.object(auth.requests,'post',return_value=Response()):
            self.assertEqual(''.join(auth.stream_reply('test','model',[],'',on_event=events.append)),'OK')
        summary=usage_summary(events)
        self.assertEqual(summary['total_tokens'],120)
        self.assertEqual(summary['cached_tokens'],40)
        self.assertNotIn('secret',str(events))
        self.assertEqual(usage_summary([])['reported_rounds'],0)
        second={'kind':'usage','details':dict(round=2,reported=True,input_tokens=200,output_tokens=30,total_tokens=230)}
        self.assertEqual(usage_summary(events+[second])['total_tokens'],350)

if __name__=='__main__':unittest.main()
