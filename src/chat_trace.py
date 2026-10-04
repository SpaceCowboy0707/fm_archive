"""Render observable execution events, never model hidden reasoning."""
import json
from src.i18n import st


def render_trace(events):
    st.caption("Execution evidence · requests, tools, SQL and actual results; no hidden model reasoning.")
    for index,event in enumerate(events,1):
        st.markdown(f"**{index}. {event['title']}** · {event.get('elapsed_seconds',0):.1f}s")
        details=dict(event.get('details',{}))
        if 'sql' in details:
            st.code(details.pop('sql'),language='sql')
        if event['kind']=='tool_requested' and isinstance(details.get('arguments'),str):
            try:details['arguments']=json.loads(details['arguments'])
            except ValueError:pass
        if details:st.json(details,expanded=False)


def usage_details(raw):
    raw=raw if isinstance(raw,dict) else {}
    result={k:v for k,v in raw.items() if k in ('input_tokens','output_tokens','total_tokens') and type(v) is int and v>=0}
    for field,key in [('input_tokens_details','cached_tokens'),('output_tokens_details','reasoning_tokens')]:
        value=(raw.get(field) or {}).get(key) if isinstance(raw.get(field),dict) else None
        if type(value) is int and value>=0:result[key]=value
    return dict(reported=bool(result),**result)


def usage_summary(events):
    rounds={e.get('details',{}).get('round'):e.get('details',{}) for e in events if e.get('kind')=='usage'}
    requests=sum(e.get('kind')=='model_request' for e in events)
    totals={k:sum(d[k] for d in rounds.values() if k in d) for k in ('input_tokens','output_tokens','total_tokens','cached_tokens','reasoning_tokens') if any(k in d for d in rounds.values())}
    return dict(requests=requests,reported_rounds=sum(bool(d.get('reported')) for d in rounds.values()),**totals)


def render_usage(events):
    summary=usage_summary(events)
    if not summary['reported_rounds']:
        st.caption("Token usage was not reported or saved for this older reply. It cannot be reconstructed.")
        return
    label=lambda k:f"{summary[k]:,}" if k in summary else "Not reported"
    st.caption(f"Response · Input {label('input_tokens')} / Output {label('output_tokens')} / Total {label('total_tokens')} tokens")
    with st.expander("Usage details"):
        st.json(summary)
        st.caption("Totals include multiple model rounds in this response. Cached input is part of input; reasoning tokens are part of output. Do not add them twice. Only reported values are counted; interrupted or missing rounds may be absent. Tokens cannot directly establish subscription percentages or prices.")
