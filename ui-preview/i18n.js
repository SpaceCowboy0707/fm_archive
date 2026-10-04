/* English source messages; Chinese is a separate display catalog. */
(() => {
  const saved=localStorage.getItem('dynasty.language');
  window.uiLanguage=saved==='zh-CN'?'zh-CN':'en';
  let catalog={},patterns=[];
  const source=new WeakMap(),attrs=new WeakMap();
  const protectedSelector='.no-tr,.archive-value,.answer-text,.turn-title,#title,pre,#livePeople,input,textarea,script,style';
  const escapeRegex=s=>s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  window.tr=function(text){
    if(window.uiLanguage!=='zh-CN'||typeof text!=='string')return text;
    const trimmed=text.trim();
    if(catalog[trimmed])return text.replace(trimmed,catalog[trimmed]);
    for(const [regex,target] of patterns){const match=text.match(regex);if(match)return target.replace(/\{(\d+)\}/g,(_,n)=>match[Number(n)+1]??'');}
    // Product-only composite labels. User content and evidence payloads are excluded below.
    let value=text;
    for(const key of Object.keys(catalog).filter(k=>k.length>3&&!k.includes('{')).sort((a,b)=>b.length-a.length)){
      if(value.includes(key))value=value.replace(new RegExp('(?<![A-Za-z])'+escapeRegex(key)+'(?![A-Za-z])','g'),()=>catalog[key]);
    }
    return value;
  };
  function skip(el){return !el||el.closest(protectedSelector)||el.id==='languageSwitch'||el.closest('#languageSwitch')||(el.classList.contains('chat-name'));}
  function render(){
    observer.disconnect();document.documentElement.lang=window.uiLanguage;
    const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
    let node;while(node=walker.nextNode()){
      if(skip(node.parentElement)||!node.textContent.trim())continue;
      const prev=source.get(node);const english=prev&&node.textContent===prev.shown?prev.english:node.textContent;
      const shown=tr(english);source.set(node,{english,shown});if(node.textContent!==shown)node.textContent=shown;
    }
    document.querySelectorAll('[placeholder],[aria-label],[title]').forEach(el=>{
      if(el.closest('.archive-value,.answer-text,pre,#livePeople'))return;
      const record=attrs.get(el)||{};
      for(const name of ['placeholder','aria-label','title']){if(!el.hasAttribute(name))continue;const val=el.getAttribute(name),old=record[name];const english=old&&old.shown===val?old.english:val;const shown=tr(english);record[name]={english,shown};if(val!==shown)el.setAttribute(name,shown)}attrs.set(el,record);
    });
    // Native archive routes share the current interface language.
    observer.observe(document.body,{childList:true,subtree:true,characterData:true});
  }
  const observer=new MutationObserver(()=>render());
  const control=document.getElementById('languageSwitch');control.value=window.uiLanguage;
  control.onchange=()=>{window.uiLanguage=control.value;localStorage.setItem('dynasty.language',uiLanguage);render();window.dispatchEvent(new Event('languagechange'))};
  window.localizationReady=fetch('/locales/zh-CN.json').then(r=>{if(!r.ok)throw Error('Translation catalog unavailable');return r.json()}).then(data=>{catalog=data;patterns=Object.entries(data).filter(([key])=>/\{\d+\}/.test(key)).map(([key,value])=>[new RegExp('^'+key.split(/(\{\d+\})/).map(s=>/^\{\d+\}$/.test(s)?'(.*?)':escapeRegex(s)).join('')+'$','s'),value]);render()}).catch(()=>{window.uiLanguage='en';control.value='en';control.disabled=true;control.title='Translation catalog unavailable; English remains available';render()});
})();
