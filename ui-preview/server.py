"""Local web workspace, sharing the existing archive and chat databases."""
import json,sqlite3,sys,secrets
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from src import chat_store as store,chat_auth as auth,web_chat
from src.archive import snapshots,squad
from src.league_archive import current_season
from src import web_archive, sql_console
TOKEN=secrets.token_urlsafe(32)
LOGIN=None

def read(db,sql,args=()):
    with sqlite3.connect((ROOT/'db'/db).as_uri()+'?mode=ro',uri=True) as c:
        c.row_factory=sqlite3.Row
        return [dict(r) for r in c.execute(sql,args)]

class Handler(BaseHTTPRequestHandler):
    def allowed(self):return self.headers.get('Host') in ('127.0.0.1:8502','localhost:8502')
    def reply(self,data,status=200):
        body=json.dumps(data,ensure_ascii=False).encode();self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if not self.allowed():self.send_error(403);return
        u=urlparse(self.path);a=parse_qs(u.query)
        try:
            if u.path=='/api/config':
                options,active=auth.account_options()
                data=dict(csrf=TOKEN,accounts=[dict(id=k,label=v) for k,v in options.items()],active=active,snapshots=[{k:s[k] for k in ('id','game_date','club_uid')} for s in snapshots()],login=dict(status=LOGIN.status,message=LOGIN.message,url=LOGIN.url if LOGIN.status=='waiting' else None) if LOGIN else None)
            elif u.path=='/api/chats':
                data=read('chats.sqlite3',"SELECT c.id,c.title,COALESCE(p.mode,'story') mode,p.model,(SELECT COUNT(*) FROM messages m WHERE m.chat_id=c.id AND m.role='user') count FROM chats c LEFT JOIN chat_preferences p ON p.chat_id=c.id ORDER BY c.created DESC")
            elif u.path=='/api/messages':
                data=read('chats.sqlite3','SELECT id,role,text,status,model,created FROM messages WHERE chat_id=? ORDER BY created,rowid',(a.get('chat',[''])[0],))
            elif u.path=='/api/jobs':data=web_chat.jobs(a.get('chat',[''])[0])
            elif u.path=='/api/people':
                sid=int(a.get('snapshot',['0'])[0]);data=[dict(id=p['identity_key'],name=p['name']) for p in squad(sid)]
            elif u.path=='/api/evidence':
                mid=a.get('message',[''])[0];data={}
                for key,table in [('workflow','workflow_traces'),('queries','query_traces')]:
                    rows=read('chats.sqlite3',f'SELECT payload FROM {table} WHERE message_id=?',(mid,))
                    data[key]=json.loads(rows[0]['payload']) if rows else []
            elif u.path=='/api/draft':
                # The answer text written so far, polled while a job runs.
                rows=read('chats.sqlite3',"SELECT text,status FROM messages WHERE id=? AND role='assistant'",(a.get('message',[''])[0],))
                data=rows[0] if rows else {}
            elif u.path=='/api/overview':
                day=a.get('date',['9999-12-31'])[0]
                rows=read('archive.sqlite3',"SELECT t.standing_json,s.game_date,s.season FROM league_team_snapshots t JOIN league_snapshots s ON s.sha256=t.sha256 WHERE t.club_uid=673 AND s.game_date<=? ORDER BY s.game_date DESC LIMIT 1",(day,))
                data=rows[0] if rows else {};data['standing']=json.loads(data.pop('standing_json','{}') or '{}')
                # Between seasons FM has no league table; the latest table stays the season shown, with the gap noted.
                if read('archive.sqlite3',"SELECT 1 FROM sqlite_master WHERE name='league_offseason_skips'"):
                    gap=read('archive.sqlite3','SELECT game_date,next_season,next_start FROM league_offseason_skips WHERE game_date<=? AND game_date>? ORDER BY game_date DESC LIMIT 1',(day,data.get('game_date') or ''))
                    data['offseason']=gap[0] if gap else None
            elif u.path=='/api/archive':
                data=web_archive.overview(a.get('page',['squad'])[0],a.get('snapshot',[None])[0],a.get('period',[None])[0],a.get('identity',[None])[0])
            elif u.path=='/api/archive/schema':
                data=dict(tables=sql_console.schema(),examples=sql_console.EXAMPLES)
            elif u.path=='/api/archive/sync':data=web_archive.sync_status()
            elif u.path=='/api/archive/image':
                path=web_archive.evidence_image(a.get('id',[''])[0]);body=path.read_bytes()
                self.send_response(200);self.send_header('Content-Type','image/png' if path.suffix.lower()=='.png' else 'image/jpeg');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body);return
            elif u.path=='/crest.png':
                # Optional local image, Git-ignored; the page falls back to the text crest when absent.
                path=ROOT/'ui-preview'/'crest.png'
                if not path.is_file():self.send_error(404);return
                body=path.read_bytes();self.send_response(200);self.send_header('Content-Type','image/png');self.send_header('Cache-Control','max-age=86400');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body);return
            elif u.path=='/locales/zh-CN.json':
                data=json.loads((ROOT/'locales/zh-CN.json').read_text(encoding='utf-8'))
            elif u.path in ('/','/index.html','/style.css','/app.js','/live.js','/i18n.js','/archive.js','/archive.css','/timeline.js','/charts.js'):
                path=ROOT/'ui-preview'/('index.html' if u.path=='/' else u.path[1:]);body=path.read_bytes()
                self.send_response(200);self.send_header('Content-Type',{'html':'text/html','css':'text/css','js':'application/javascript'}[path.suffix[1:]]+'; charset=utf-8');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            else:self.send_error(404);return
            self.reply(data)
        except (ValueError,auth.ConnectionFailure) as exc:self.reply(dict(error=str(exc)),400)
        except Exception:self.reply(dict(error='Local data is unavailable. Check service logs.'),500)
    def do_POST(self):
        global LOGIN
        if not self.allowed() or self.headers.get('Origin') not in ('http://127.0.0.1:8502','http://localhost:8502'):
            self.reply(dict(error='Request blocked: it did not come from the local workspace page.'),403);return
        # A restart issues a new token; the page refetches it and retries once (nothing was processed).
        if not secrets.compare_digest(self.headers.get('X-Workspace-Token',''),TOKEN):
            self.reply(dict(error='The workspace service restarted. Refresh the page and try again.',code='stale_token'),403);return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=100000:raise ValueError('Invalid request length.')
            a=json.loads(self.rfile.read(length))
            if not isinstance(a,dict):raise ValueError('Invalid request format.')
            if self.path=='/api/send':data=web_chat.submit(a)
            elif self.path=='/api/archive/query':
                sql=a.get('sql','')
                if not isinstance(sql,str) or len(sql)>20000:raise ValueError('SQL exceeds the editor limit.')
                data=sql_console.query(sql)
            elif self.path=='/api/archive/sync':data=web_archive.start_sync()
            elif self.path in ('/api/delete-chat','/api/delete-turn'):
                chat=str(a.get('chat_id',''))
                if any(j['state']=='running' for j in web_chat.jobs(chat)):raise ValueError('Wait for the running answer in this conversation to finish before deleting.')
                if self.path=='/api/delete-chat':store.delete_chat(chat);data=dict(deleted=True)
                else:data=dict(deleted=store.delete_turn(chat,str(a.get('message_id',''))))
            elif self.path=='/api/create':
                if a.get('mode') not in ('analysis','story'):raise ValueError('Invalid chat space.')
                data=dict(id=store.create_chat(str(a.get('title',''))[:120],mode=a['mode']))
            elif self.path=='/api/models':
                options,_=auth.account_options()
                if a.get('account') not in options:raise ValueError('Select a signed-in account.')
                data=[dict(slug=m['slug'],label=m.get('display_name',m['slug'])) for m in web_chat.catalog(a['account'],True)]
            elif self.path=='/api/login':
                if LOGIN and LOGIN.status=='waiting':data=dict(url=LOGIN.url)
                else:LOGIN=auth.LoginAttempt(a.get('account') or None);data=dict(url=LOGIN.url)
            elif self.path=='/api/logout':
                if any(j['state']=='running' for c in store.chats() for j in web_chat.jobs(c['id'])):raise ValueError('Wait for the running response before signing out.')
                options,_=auth.account_options()
                if a.get('account') not in options:raise ValueError('Account not found.')
                data=dict(revoked=auth.sign_out(a['account']))
            elif self.path=='/api/collect':
                sid=int(a.get('snapshot_id',0));ids=a.get('people',[])
                # A blank season follows the save, as it does for questions.
                day=next((s['game_date'] for s in snapshots() if s['id']==sid),None)
                season=(a.get('season') or '').strip() or (day and current_season(day)) or ''
                data=dict(id=store.collect(a.get('message_id',''),a.get('title',''),season,[p for p in squad(sid) if p['identity_key'] in ids]))
            else:self.reply(dict(error='Unknown workspace action.'),404);return
            self.reply(data)
        except (ValueError,sqlite3.Error,auth.ConnectionFailure) as exc:self.reply(dict(error=str(exc)),400)
        except Exception:self.reply(dict(error='Local processing failed. No automatic retry occurred; check execution records.'),500)
    def log_message(self,*args):pass
if __name__=='__main__':
    server=ThreadingHTTPServer(('127.0.0.1',8502),Handler)
    web_chat.init()
    server.serve_forever()
