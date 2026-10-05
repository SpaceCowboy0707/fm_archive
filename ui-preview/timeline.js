/* Step-by-step execution timeline for the evidence panel. Renders saved events only, never hidden reasoning. */
(() => {
  const opened=new Set();
  const PREP=new Set(['input','request_routing','memory_context','context_window']);
  const MINOR=new Set(['model_accepted','text_started']);
  const ICONS={input:'✎',request_routing:'⇢',memory_context:'❖',context_window:'✂',model_request:'↑',model_accepted:'✓',text_started:'…',model_decision:'◆',
    tool_requested:'⚙',sqlite_read:'⛁',data_processed:'⚖',tool_result:'↩',usage:'Σ',evidence_missing:'!',evidence_repair:'↺',tool_choice_relaxed:'↺',writing_progress:'✎',evidence_check:'✔',evidence_recheck:'✔',completed:'■',error:'✖',interrupted:'✖'};
  const num=v=>typeof v==='number'?v.toLocaleString():esc(v??'—');
  const clip=(s,n)=>{s=String(s??'');return s.length>n?s.slice(0,n)+'…':s};
  const json=v=>{const s=typeof v==='string'?v:(JSON.stringify(v,null,2)??'');return s.length>20000?s.slice(0,20000)+'\n… truncated in display ('+s.length.toLocaleString()+' characters saved)':s};
  const parse=v=>{if(typeof v!=='string')return v;try{return JSON.parse(v)}catch{return v}};
  const kv=obj=>{const o=parse(obj);if(!o||typeof o!=='object')return `<pre>${esc(json(o))}</pre>`;const rows=Object.entries(o);return rows.length?`<table class="tl-kv no-tr">${rows.map(([k,v])=>`<tr><th>${esc(k)}</th><td>${esc(v===null?'null':typeof v==='object'?JSON.stringify(v):v)}</td></tr>`).join('')}</table>`:'<p class="tl-note">No arguments</p>'};
  const list=(title,items)=>items?.length?`<h4>${esc(title)}</h4><ul class="tl-list no-tr">${items.map(i=>`<li>${esc(i)}</li>`).join('')}</ul>`:'';
  const toolName=d=>`<span class="tl-tool no-tr">#${esc(d.query_index??'?')} ${esc(d.name||'')}</span>`;

  function describe(e){
    const d=e.details||{},r=d.result||{};
    switch(e.kind){
      case 'input':return {meta:clip(d.question,90),body:kv({snapshot_date:d.snapshot_date,season:d.discussion_season,model:d.model,require_lookup:d.require_lookup})};
      case 'memory_context':return {meta:`${(d.excerpts||[]).length} excerpts`,body:''};
      case 'context_window':return {meta:`${d.omitted_messages} older messages omitted`,body:''};
      case 'model_request':return {meta:`tool_choice=${d.tool_choice||'—'} · tool results sent: ${(d.tool_results||[]).length}`,body:kv({model:d.model,tool_choice:d.tool_choice,tool_results_sent:d.tool_results})};
      case 'model_decision':return {status:d.decision==='answer'?'ok':'',meta:d.decision==='answer'?`answer · ${num(d.text_characters)} characters`:'→ '+(d.tools||[]).join(', '),body:kv({decision:d.decision,tools:d.tools,output_items:d.output_items})};
      case 'tool_requested':return {head:toolName(d)+(d.label?`<span class="tl-label">${esc(d.label)}</span>`:''),meta:d.budget_used!=null?`budget ${d.budget_used}/${d.budget_limit}`:'',body:'<h4>Arguments</h4>'+kv(d.arguments)};
      case 'sqlite_read':return {meta:`${num(d.database_rows)} rows · ${num(d.elapsed_ms)} ms`,body:`<h4>SQL</h4><pre>${esc(d.sql)}</pre><h4>Parameters</h4><pre>${esc(json(d.parameters))}</pre>`};
      case 'data_processed':return {status:d.status==='error'?'error':'',meta:`matched ${num(d.matched_records)} · returned ${num(d.returned_records)}`+(d.next_offset!=null?` · next_offset ${d.next_offset}`:''),body:`<p class="tl-note">${esc(d.rules)}</p>`};
      case 'tool_result':{
        const failed=d.status==='error'||!!r.error;
        const meta=failed?clip(r.error,110):['total' in r?`total ${num(r.total)}`:'',r.rows?`returned ${r.rows.length}`:'',r.next_offset!=null?`next_offset ${r.next_offset}`:'',d.output_characters!=null?`${num(d.output_characters)} chars`:'',d.duration_ms!=null?`${num(d.duration_ms)} ms`:''].filter(Boolean).join(' · ');
        const error=failed?`<div class="tl-error"><b>${esc(r.error)}</b>${kv(Object.fromEntries(Object.entries(r).filter(([k])=>['error_type','field','received','expected','retryable','detail'].includes(k))))}</div>`:'';
        return {status:failed?'error':'ok',head:toolName(d)+(d.label?`<span class="tl-label">${esc(d.label)}</span>`:''),meta,body:error+'<h4>Result returned to the model</h4><pre>'+esc(json(r))+'</pre>'};}
      case 'usage':return {meta:d.reported?`in ${num(d.input_tokens)} · out ${num(d.output_tokens)} · cached ${num(d.cached_tokens)}`:'not reported',body:''};
      case 'evidence_repair':return {status:'warn',meta:(d.mode==='patch'?((d.references||[]).length?`fix references ${d.references.join(', ')} only · `:'')+((d.seasons||[]).length?`declare ${d.seasons.join(', ')} · `:''):d.mode==='rewrite'?'full rewrite · ':'')+`${(d.errors||[]).length} errors sent back`+(d.evidence_characters!=null?` · ${num(d.evidence_characters)} chars of evidence`:''),body:list('Errors',d.errors)+(d.previous_draft?`<h4>Previous draft</h4><pre>${esc(json(d.previous_draft))}</pre>`:'')};
      case 'evidence_check':case 'evidence_recheck':return {status:d.passed?'ok':'error',meta:d.passed?(d.partial?`passed with ${(d.warnings||[]).length} warnings`:'passed'):`failed · ${(d.errors||[]).length} errors`,body:list('Errors',d.errors)+list('Warnings',d.warnings)+list('Verified facts',d.verified_facts)};
      case 'error':case 'interrupted':return {status:'error',meta:clip(d.message||d.error_type,110),body:''};
      case 'writing_progress':return {meta:`${num(d.characters)} characters so far`,body:''};
      case 'tool_choice_relaxed':return {status:'warn',meta:'service stopped text in a tool-only round · next round may query or answer',body:''};
      case 'request_routing':return {meta:clip(d.reason,90),body:''};
      default:return {meta:clip(d.name||d.reason||d.note||'',90),body:''};
    }
  }

  function item(e,i){
    const x=describe(e),d=e.details||{};
    const raw=Object.keys(d).length?`<details class="tl-raw"><summary>Raw event</summary><pre>${esc(json(d))}</pre></details>`:'';
    const body=(x.body||'')+(d.note?`<p class="tl-note">${esc(d.note)}</p>`:'')+raw;
    return `<details class="tl-event kind-${esc(e.kind)} ${x.status?'st-'+x.status:''} ${MINOR.has(e.kind)?'minor':''}" data-i="${i}" ${opened.has(i)?'open':''}><summary><span class="tl-time no-tr">${e.elapsed_seconds!=null?Number(e.elapsed_seconds).toFixed(1)+'s':''}</span><span class="tl-icon">${ICONS[e.kind]||'•'}</span><span class="tl-main"><span class="tl-title">${esc(e.title)}</span>${x.head||''}${x.meta?`<span class="tl-meta no-tr">${esc(x.meta)}</span>`:''}</span></summary><div class="tl-body">${body}</div></details>`;
  }

  window.renderTimeline=function(root,w,q){
    const results=w.filter(e=>e.kind==='tool_result'),failed=results.filter(e=>e.details?.status==='error'||e.details?.result?.error).length;
    const usage=w.filter(e=>e.kind==='usage'&&e.details?.reported).reduce((n,e)=>n+(e.details.total_tokens||0),0);
    const rounds=w.filter(e=>e.kind==='model_request').length;
    const stats=[[rounds,'Model rounds'],[results.length||q.length,'Tool calls'],[failed,'Failed calls'],[w.filter(e=>e.kind==='sqlite_read').length,'SQL reads'],[usage?usage.toLocaleString():'—','Tokens'],[w.length?Number(w.at(-1).elapsed_seconds||0).toFixed(1)+'s':'—','Elapsed']];
    let html=`<div class="tl-stats">${stats.map(([v,l])=>`<div><b class="no-tr">${v}</b><span>${l}</span></div>`).join('')}</div>`;
    html+=`<div class="tl-tools"><label><input type="checkbox" id="tlMinor" ${root.dataset.minor==='1'?'checked':''}> <span>Show minor events</span></label><button id="tlExpand" class="outline">Expand all</button><button id="tlCollapse" class="outline">Collapse all</button></div>`;
    if(!w.length){root.innerHTML=html+'<p class="empty">No execution records were saved for this historical reply.</p>';return}
    let group=null,out='';
    w.forEach((e,i)=>{
      // Progress repeats every few seconds; only the latest of a run is shown.
      if(e.kind==='writing_progress'&&w[i+1]?.kind==='writing_progress')return;
      const g=e.kind==='model_request'?'r'+(e.details?.round??''):PREP.has(e.kind)&&group===null?'prep':['evidence_check','evidence_recheck','completed','error','interrupted'].includes(e.kind)?'end':group;
      if(g!==group){
        if(group!==null)out+='</section>';
        const title=g==='prep'?'<span>Preparation</span>':g==='end'?'<span>Result</span>':`<span>${e.details?.phase==='repair'?'Repair round':'Round'} ${esc(e.details?.round??'')}</span>`;
        out+=`<section class="tl-group"><h3>${title}</h3>`;group=g;
      }
      out+=item(e,i);
    });
    root.innerHTML=html+`<div class="tl ${root.dataset.minor==='1'?'show-minor':''}">${out}</section></div>`;
    root.querySelectorAll('.tl-event').forEach(el=>el.addEventListener('toggle',()=>{const i=+el.dataset.i;el.open?opened.add(i):opened.delete(i)}));
    root.querySelector('#tlMinor').onchange=ev=>{root.dataset.minor=ev.target.checked?'1':'';root.querySelector('.tl').classList.toggle('show-minor',ev.target.checked)};
    root.querySelector('#tlExpand').onclick=()=>root.querySelectorAll('.tl-event').forEach(el=>el.open=true);
    root.querySelector('#tlCollapse').onclick=()=>root.querySelectorAll('.tl-event').forEach(el=>el.open=false);
  };
  // A different reply starts with collapsed steps.
  window.resetTimeline=()=>opened.clear();
  document.getElementById('widenEvidence').onclick=()=>document.body.classList.toggle('evidence-wide');
})();
