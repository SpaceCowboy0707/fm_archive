"""Documented ChatGPT plan OAuth. Credentials are Windows DPAPI encrypted.

No Codex credentials, cookies, API keys, or private ChatGPT endpoints are used.
"""
import base64,ctypes,hashlib,json,os,re,secrets,threading,time,uuid
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler,HTTPServer
from urllib.parse import urlencode,urlparse,parse_qs
import requests
import jwt
from src.safe_export import ROOT

AUTH='https://auth.openai.com'
RESOURCE='https://api.openai.com/v1'
SCOPES='openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'
PRIVATE=ROOT/'.private'
LOCK=threading.RLock()

class ConnectionFailure(Exception):
    def __init__(self,message,code=None):
        super().__init__(message)
        self.code=code

class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]

def protect(data,decrypt=False):
    if os.name!='nt':raise ConnectionFailure("Credential protection in this version requires Windows.")
    buf=ctypes.create_string_buffer(data)
    source=Blob(len(data),ctypes.cast(buf,ctypes.POINTER(ctypes.c_ubyte)));out=Blob()
    lib=ctypes.WinDLL('crypt32',use_last_error=True)
    fun=lib.CryptUnprotectData if decrypt else lib.CryptProtectData
    fun.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    fun.restype=wintypes.BOOL
    if not fun(ctypes.byref(source),None,None,None,None,1,ctypes.byref(out)):
        raise ConnectionFailure("Windows could not protect or unlock these credentials. Use the original Windows account.")
    try:return ctypes.string_at(out.data,out.size)
    finally:
        kernel=ctypes.WinDLL('kernel32');kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
        kernel.LocalFree(out.data)

def vault():
    path=PRIVATE/'accounts.bin'
    return json.loads(protect(path.read_bytes(),True)) if path.exists() else {'accounts':{},'active':None}

def save_vault(data):
    PRIVATE.mkdir(exist_ok=True)
    tmp=PRIVATE/('accounts-'+uuid.uuid4().hex+'.tmp')
    tmp.write_bytes(protect(json.dumps(data).encode()))
    os.replace(tmp,PRIVATE/'accounts.bin')

def host_id():
    with LOCK:
        PRIVATE.mkdir(exist_ok=True);path=PRIVATE/'host-id'
        if not path.exists():path.write_text('urn:uuid:'+str(uuid.uuid4()),encoding='ascii')
        return path.read_text(encoding='ascii')

def request_json(method,url,**kwargs):
    try:
        response=requests.request(method,url,timeout=30,allow_redirects=False,**kwargs)
        if response.status_code>=300:raise ConnectionFailure(f'OpenAI connection failed (HTTP {response.status_code}). Retry sign-in or check account permissions.')
        return response.json()
    except (requests.RequestException,ValueError):raise ConnectionFailure("Cannot connect to OpenAI. Check your connection and retry.") from None

def validate_tokens(tokens,client_id,nonce,subject=None):
    discovery=request_json('GET',AUTH+'/.well-known/openid-configuration')
    if discovery.get('issuer')!=AUTH or not discovery.get('jwks_uri','').startswith(AUTH+'/'):
        raise ConnectionFailure("Login service identity verification failed.")
    keys=request_json('GET',discovery['jwks_uri'])
    try:
        header=jwt.get_unverified_header(tokens['id_token'])
        key=next(k for k in keys['keys'] if k['kid']==header['kid'])
        claims=jwt.decode(tokens['id_token'],jwt.PyJWK.from_dict(key).key,algorithms=['RS256'],audience=client_id,issuer=AUTH,options={'require':['exp','iss','aud','sub','nonce']})
        if not secrets.compare_digest(str(claims['nonce']),nonce):raise ValueError()
        if subject and claims['sub']!=subject:raise ValueError()
        if not tokens.get('access_token') or tokens.get('token_type','').lower()!='bearer':raise ValueError()
    except Exception:raise ConnectionFailure("Login identity or signature verification failed. Credentials were not saved.") from None
    if 'chatgpt.tokens.use.direct' not in tokens.get('scope','').split():
        raise ConnectionFailure("This account has not granted ChatGPT plan access. Authorize again.")
    return claims

class LoginAttempt:
    def __init__(self,client_id=None):
        self.status='waiting';self.message="Waiting for you to finish signing in on OpenAI.";self.created=time.time()
        self.state=secrets.token_urlsafe(32);self.nonce=secrets.token_urlsafe(32);self.verifier=secrets.token_urlsafe(64)
        self.existing=client_id
        with LOCK:self.account=vault()['accounts'].get(client_id,{})
        attempt=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                query=parse_qs(urlparse(self.path).query)
                state=query.get('state',[''])[0]
                if urlparse(self.path).path!='/auth/callback' or not secrets.compare_digest(state,attempt.state):
                    self.send_error(400,'Invalid authorization response');return
                with LOCK:
                    if attempt.status!='waiting':self.send_error(409);return
                    attempt.status='processing'
                try:
                    attempt.complete(query)
                    attempt.status='success';attempt.message="Signed in. Return to the archive and refresh the account status."
                except ConnectionFailure as exc:attempt.status='failed';attempt.message=str(exc)
                except Exception:attempt.status='failed';attempt.message="Sign-in did not complete. Start again in the archive."
                body=('<meta charset="utf-8"><h2>'+attempt.message+"</h2><a href=\"http://127.0.0.1:8502/\">Return to the archive</a>").encode()
                self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer');self.end_headers();self.wfile.write(body)
        self.server=HTTPServer(('127.0.0.1',0),Handler)
        self.redirect=f'http://127.0.0.1:{self.server.server_port}/auth/callback'
        args=dict(client_id=client_id or 'dynamic_agent_client',ext_agent_host_id=host_id(),response_type='code',redirect_uri=self.redirect,scope=SCOPES,resource=RESOURCE,state=self.state,nonce=self.nonce,code_challenge_method='S256',code_challenge=base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).decode().rstrip('='))
        if not client_id:args['agent_name_hint']='Leicester Dynasty Archive'
        # Do not include retained ID tokens in a link rendered by the website.
        self.url=AUTH+'/api/accounts/authorize?'+urlencode(args)
        threading.Thread(target=self.run,daemon=True).start()

    def run(self):
        self.server.timeout=1
        try:
            while self.status=='waiting' and time.time()-self.created<600:self.server.handle_request()
            if self.status=='waiting':self.status='expired';self.message="The sign-in link expired. Start again."
        finally:self.server.server_close()

    def complete(self,query):
        if query.get('error'):raise ConnectionFailure("Sign-in or plan authorization did not complete. You can try again.")
        cid=query.get('client_id',[self.existing])[0]
        if not cid or cid=='dynamic_agent_client' or (self.existing and cid!=self.existing):raise ConnectionFailure("Application registration did not complete. No login information was saved.")
        code=query.get('code',[''])[0]
        if not code:raise ConnectionFailure("The login callback is missing an authorization code.")
        tokens=request_json('POST',AUTH+'/api/accounts/oauth/token',data=dict(grant_type='authorization_code',client_id=cid,code=code,code_verifier=self.verifier,redirect_uri=self.redirect,resource=RESOURCE))
        claims=validate_tokens(tokens,cid,self.nonce,self.account.get('subject'))
        record={**tokens,'client_id':cid,'subject':claims['sub'],'email':claims.get('email',"ChatGPT account"),'expires_at':time.time()+tokens.get('expires_in',3600)}
        with LOCK:
            data=vault();data['accounts'][cid]=record;data['active']=cid;save_vault(data)

def account_options():
    with LOCK:
        data=vault()
        return {cid:f"{a['email']} · {cid[-6:]}" for cid,a in data['accounts'].items()},data['active']

def access_token(cid):
    with LOCK:
        data=vault();a=data['accounts'].get(cid)
        if not a or not a.get('access_token'):raise ConnectionFailure("Sign in with ChatGPT first.")
        if a['expires_at']<time.time()+90:
            token=request_json('POST',AUTH+'/api/accounts/oauth/token',data=dict(grant_type='refresh_token',client_id=cid,refresh_token=a['refresh_token'],resource=RESOURCE))
            if not token.get('access_token'):raise ConnectionFailure("Your login expired. Sign in again.")
            if 'scope' in token and 'chatgpt.tokens.use.direct' not in token['scope'].split():raise ConnectionFailure("Plan access is no longer valid. Authorize again.")
            a.update(token);a['expires_at']=time.time()+token.get('expires_in',3600);save_vault(data)
        return a['access_token']

def models(cid):
    result=request_json('GET',RESOURCE+'/models',headers={'Authorization':'Bearer '+access_token(cid)})
    return [m for m in result.get('models',[]) if m.get('visibility')=='list' and m.get('slug')]

def sign_out(cid):
    with LOCK:
        data=vault();a=data['accounts'][cid];confirmed=False
        try:
            discovery=request_json('GET',AUTH+'/.well-known/openid-configuration')
            endpoint=discovery['revocation_endpoint']
            if not endpoint.startswith(AUTH+'/'):raise ConnectionFailure("The revocation endpoint failed validation.")
            r=requests.post(endpoint,data={'token':a.get('refresh_token',''),'token_type_hint':'refresh_token','client_id':cid},timeout=20,allow_redirects=False)
            confirmed=r.status_code==200
        except (ConnectionFailure,requests.RequestException,KeyError):pass
        data['accounts'][cid]={k:a[k] for k in ('client_id','subject','email')};data['active']=None;save_vault(data)
        return confirmed

def response_failure(event,status=None):
    """Expose diagnostic codes, never credentials, prompts, or full response payloads."""
    response=event.get('response') or {}
    error=response.get('error') or event.get('error') or event
    if not isinstance(error,dict):error={}
    reason=(response.get('incomplete_details') or {}).get('reason')
    details={k:v for k,v in dict(event=event.get('type'),code=error.get('code'),
             error_type=error.get('type'),param=error.get('param'),reason=reason).items()
             if isinstance(v,str) and re.fullmatch(r'[A-Za-z0-9_.\[\]-]{1,100}',v)}
    code=details.get('code','')
    explanation={'subscription_sharing_usage_limit_exceeded':"This application reached a ChatGPT subscription usage limit. Check overall and app limits in ChatGPT Settings → Usage. This does not necessarily mean your entire plan is exhausted; no reset time was reported.",
                 'subscription_sharing_usage_unavailable':"Subscription availability could not be checked. Try later; signing in again is not required.",
                 'subscription_sharing_user_not_eligible':"This account or workspace does not support subscription access for this app. Check account and workspace policies.",
                 'subscription_sharing_unsupported_capability':"The request uses a feature unsupported by this subscription connection. Check the diagnostic parameters.",
                 'insufficient_quota':"Available account quota is insufficient. Check ChatGPT Usage.",
                 'rate_limit_exceeded':"A rate or usage limit was reached. Try again later.",
                 'context_length_exceeded':"This conversation and its background exceed the model context limit. Reduce the scope.",
                 'server_error':"OpenAI could not complete this request. You can retry.",
                 'invalid_api_key':"Invalid login credentials. Sign in again."}.get(code,"OpenAI could not complete this response.")
    detail='; '.join(f'{k}={v}' for k,v in details.items()) or "No error code provided"
    if status is not None:detail=f'HTTP {status}; '+detail
    return ConnectionFailure(explanation+" Diagnostics: "+detail+". Your message is saved; the app will not automatically switch to paid API access.",code=code)

def stream_reply(cid,model,messages,instructions,tools=None,execute_tool=None,on_tool=None,on_event=None,require_lookup=False,final_text_only=False):
    """Replay completed Responses items and tool outputs in bounded stateless rounds."""
    def emit(kind,title,**details):
        if on_event:on_event({'kind':kind,'title':title,'details':details})
    inputs=list(messages)
    started=time.monotonic()
    calls_used=0
    tool_index=0
    evidence_ready=False
    allowed={t['name'] for t in tools or []}
    for round_index in range(7):
        final_only=round_index==6 or calls_used>=8
        body={'model':model,'input':list(inputs),'instructions':instructions,'store':False,'stream':True}
        choice='none' if final_only else 'required' if require_lookup and not evidence_ready else 'auto'
        if tools:
            body.update(tools=tools,tool_choice=choice,parallel_tool_calls=False)
        if final_only and require_lookup and not evidence_ready:
            body['instructions']+="\nThe query budget is exhausted without concrete evidence. Describe attempted queries and gaps only; do not assert unverified performance conclusions."
            emit('evidence_missing',"Query budget exhausted without concrete evidence",note="Only gaps can be reported; verification has not succeeded.")
        completed=False
        received_text=False
        buffered_text=[]
        output=[]
        done_items={}
        emit('model_request',"Sending a model request",round=round_index+1,model=model,
             tool_results=[i['call_id'] for i in inputs if i.get('type')=='function_call_output'],
             tool_choice=choice,
             note="A tool call is required in this round; a final answer is not permitted yet." if choice=='required' else "Sending the question, concise context and previous results. The model can query again or answer.")
        try:
            with requests.post(RESOURCE+'/responses',headers={'Authorization':'Bearer '+access_token(cid)},
                               json=body,stream=True,timeout=(20,120),allow_redirects=False) as response:
                if response.status_code!=200:
                    try:failure=response.json()
                    except ValueError:failure={}
                    raise response_failure(failure,response.status_code)
                emit('model_accepted',"The model service accepted this request",round=round_index+1)
                response.encoding='utf-8'
                for line in response.iter_lines(decode_unicode=True):
                    if time.monotonic()-started>600:
                        raise ConnectionFailure("Analysis exceeded ten minutes and was stopped. Your message is saved; narrow the scope before retrying.")
                    if not line.startswith('data:'):continue
                    raw=line[5:].strip()
                    if raw=='[DONE]':continue
                    event=json.loads(raw);kind=event.get('type')
                    if kind=='response.output_text.delta':
                        if not received_text:emit('text_started',"The model started producing response text",round=round_index+1,note="Text is being generated; this round may still contain tool requests.")
                        received_text=received_text or bool(event.get('delta','').strip())
                        buffered_text.append(event.get('delta',''))
                        if not final_text_only:yield event.get('delta','')
                    elif kind=='response.output_item.done':
                        done_items[event['output_index']]=event['item']
                    elif kind=='response.completed':
                        from src.chat_trace import usage_details
                        emit('usage',"Model usage for this round",round=round_index+1,**usage_details((event.get('response') or {}).get('usage')))
                        completed=True
                        output=(event.get('response') or {}).get('output') or [done_items[k] for k in sorted(done_items)]
                        break
                    elif kind in ('response.failed','response.incomplete','error'):
                        from src.chat_trace import usage_details
                        emit('usage',"Usage reported for the interrupted request",round=round_index+1,**usage_details((event.get('response') or {}).get('usage')))
                        raise response_failure(event)
            if not completed:raise ConnectionFailure("The connection ended without confirmation that the response completed. Please retry.")
        except (requests.RequestException,ValueError):
            raise ConnectionFailure("The chat connection was interrupted. Please retry.") from None
        calls=[item for item in output if item.get('type')=='function_call']
        emit('model_decision',"Model decided to call tools" if calls else "Model decided to answer",round=round_index+1,
             decision='tool_calls' if calls else 'answer',tools=[c.get('name','') for c in calls],
             output_items=[item.get('type') for item in output],text_characters=len(''.join(buffered_text)))
        if not calls:
            if tools and choice=='required':raise ConnectionFailure("A lookup was required, but the model returned no tool request. This response was not marked verified. Please retry.")
            if not received_text:
                text=''.join(part.get('text','') for item in output if item.get('type')=='message'
                             for part in item.get('content',[]) if part.get('type')=='output_text')
                if not text.strip():raise ConnectionFailure("The model request ended without displayable text. No empty successful reply was saved. Retry manually.")
                yield text
            if received_text and final_text_only:yield ''.join(buffered_text)
            emit('completed',"Response completed",rounds=round_index+1,tool_calls=calls_used,note="Without a tool call, a response may use supplied context; this is not a new database query.")
            return
        if final_only:raise ConnectionFailure("The model requested more tools after the query limit. No complete conclusion was obtained; queries are preserved.")
        # Keep reasoning (including encrypted_content), messages and calls in their original order.
        inputs.extend(output)
        for call in calls:
            if not call.get('call_id'):raise ConnectionFailure("The model tool request is missing its call identifier.")
            name=call.get('name','')
            arguments=call.get('arguments','')
            # query_index is the zero-based position evidence references use for this call.
            query_index=tool_index;tool_index+=1
            emit('tool_requested',"The model requested a query tool",call_id=call['call_id'],name=name,arguments=arguments,round=round_index+1,query_index=query_index,budget_used=calls_used,budget_limit=8)
            tool_started=time.monotonic()
            if calls_used>=8:
                result=dict(error="Query budget reached. Answer from available evidence and describe the gaps.",error_type='budget_exhausted',retryable=False)
            elif name not in allowed or execute_tool is None:
                result=dict(error="This tool is not available. Use one of the listed read-only archive tools.",error_type='invalid_arguments',field='name',received=name,expected=sorted(allowed),retryable=True)
                calls_used+=1
            else:
                calls_used+=1
                result=execute_tool(name,arguments)
            serialized=json.dumps(result,ensure_ascii=False,separators=(',',':'))
            if len(serialized)>40000:
                result=dict(error=f"The result is too large ({len(serialized)} characters, limit 40000). Narrow the scope or request another page.",error_type='result_too_large',retryable=True)
                serialized=json.dumps(result,ensure_ascii=False)
            if name in ('story_memory','squad_attack_comparison','season_statistics','player_timeline','injury_history','transfer_history','league_team_data','player_profile','title_race_status') and not result.get('error'):
                evidence_ready=True
            if on_tool:on_tool({'name':name,'arguments':arguments,'result':result})
            emit('tool_result',"Query result ready to return to the model",call_id=call['call_id'],name=name,result=result,round=round_index+1,query_index=query_index,
                 status='error' if result.get('error') else 'ok',duration_ms=round((time.monotonic()-tool_started)*1000,1),output_characters=len(serialized),note="This is the actual function_call_output. The model can use it after the next request is sent.")
            inputs.append({'type':'function_call_output','call_id':call['call_id'],'output':serialized})
        if len(json.dumps(inputs,ensure_ascii=False))>350000:
            raise ConnectionFailure("This round accumulated too much query data. Reduce the date or player scope and retry.")
        if received_text and not final_text_only:yield '\n\n'
