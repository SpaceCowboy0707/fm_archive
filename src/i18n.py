"""English message IDs, explicit Chinese localization, and multilingual input aliases.

Only presentation strings are translated. Archive records, SQL, user messages and
model answer text retain their original content. Locale never changes identifiers.
"""
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
CATALOG=json.loads((ROOT/'locales/zh-CN.json').read_text(encoding='utf-8'))
INPUT_ALIASES=json.loads((ROOT/'locales/input-aliases.json').read_text(encoding='utf-8'))
TEMPLATES=[]
for key,value in CATALOG.items():
    if re.search(r'\{\d+\}',key):
        pieces=re.split(r'(\{\d+\})',key)
        pattern=''.join('(.*?)' if re.fullmatch(r'\{\d+\}',p) else re.escape(p) for p in pieces)
        TEMPLATES.append((re.compile('^'+pattern+'$',re.S),value))

def translate(text,language='en'):
    if language!='zh-CN' or not isinstance(text,str):return text
    # Blank lines are layout, never message IDs.
    if not text.strip():return text
    if text in CATALOG:return CATALOG[text]
    stripped=text.strip()
    if stripped in CATALOG:return text.replace(stripped,CATALOG[stripped],1)
    for pattern,target in TEMPLATES:
        match=pattern.fullmatch(text)
        if match:
            for i,value in enumerate(match.groups()):target=target.replace('{'+str(i)+'}',translate(value,language))
            return target
    # Composite notices are assembled from existing message IDs. No free translation.
    if '\n' in text:return '\n'.join(translate(line,language) for line in text.split('\n'))
    return text

def language():
    import streamlit
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    if get_script_run_ctx(suppress_warning=True) is None:return 'en'
    return streamlit.session_state.get('ui_language','en')

def t(text):return translate(text,language())

class LocalizedStreamlit:
    """Translate display boundaries while preserving widget values and stable keys."""
    _text={'title','header','subheader','caption','text','markdown','info','warning','error','success','toast','write'}
    _widgets={'button','download_button','link_button','checkbox','toggle','text_input','text_area','number_input','date_input','file_uploader','chat_input','slider','select_slider'}
    _choices={'selectbox','multiselect','radio','pills','segmented_control'}
    def __init__(self,target):self.target=target
    def __enter__(self):self.target.__enter__();return self
    def __exit__(self,*args):return self.target.__exit__(*args)
    def __getattr__(self,name):
        attr=getattr(self.target,name)
        if name=='sidebar':return LocalizedStreamlit(attr)
        supported=self._text|self._widgets|self._choices|{'expander','container','empty','columns','tabs','metric','dataframe','table','html','spinner','status'}
        if name not in supported or not callable(attr):return attr
        def call(*args,**kwargs):
            args=list(args)
            if name in (self._widgets|self._choices)-{'link_button'} and 'key' not in kwargs:
                import inspect,hashlib
                frame=inspect.currentframe().f_back
                identity=f"{frame.f_code.co_filename}:{frame.f_lineno}:{name}:{args[0] if args else kwargs.get('label','')}"
                kwargs['key']='localized_'+hashlib.sha256(identity.encode()).hexdigest()[:20]
            if name in self._text|self._widgets|self._choices|{'expander','metric','spinner','status'}:
                if args and isinstance(args[0],str):args[0]=t(args[0])
                for key in ('label','body','help','placeholder'):
                    if isinstance(kwargs.get(key),str):kwargs[key]=t(kwargs[key])
            if name in self._choices:
                formatter=kwargs.get('format_func',str)
                locale=language()
                kwargs['format_func']=lambda value:translate(formatter(value),locale)
            if name=='tabs' and args:args[0]=[t(x) for x in args[0]]
            if name in ('dataframe','table') and args:
                data=args[0]
                if isinstance(data,list):data=[{t(k):v for k,v in row.items()} if isinstance(row,dict) else row for row in data]
                elif hasattr(data,'rename'):data=data.rename(columns=t)
                args[0]=data
            if name=='html' and args:
                from html.parser import HTMLParser
                class LocalHTML(HTMLParser):
                    def __init__(self):super().__init__(convert_charrefs=False);self.parts=[];self.raw=False
                    def handle_starttag(self,tag,attrs):self.parts.append(self.get_starttag_text());self.raw=tag in ('script','style') or self.raw
                    def handle_endtag(self,tag):self.parts.append('</'+tag+'>');self.raw=False if tag in ('script','style') else self.raw
                    def handle_data(self,data):self.parts.append(data if self.raw else t(data))
                    def handle_entityref(self,name):self.parts.append('&'+name+';')
                    def handle_charref(self,name):self.parts.append('&#'+name+';')
                parser=LocalHTML();parser.feed(args[0]);args[0]=''.join(parser.parts)
            result=attr(*args,**kwargs)
            if name in ('columns','tabs'):return [LocalizedStreamlit(x) for x in result]
            if name in ('container','empty','expander','status'):return LocalizedStreamlit(result)
            return result
        return call

# Lazily expose Streamlit only to UI modules; backend workers do not import it.
def __getattr__(name):
    if name=='st':
        import streamlit
        return LocalizedStreamlit(streamlit)
    raise AttributeError(name)
