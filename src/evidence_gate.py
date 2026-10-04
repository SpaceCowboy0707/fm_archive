"""Deterministic evidence checks; free-form interpretation is not certified."""
import json
import math
import re
from src.i18n import INPUT_ALIASES

INSTRUCTIONS="Evidence validation is enabled. After querying, the final answer must be one JSON object without code fences: {\"season\":\"2035/36\",\"comparison_player_ids\":[],\"facts\":[{\"query\":0,\"path\":[\"rows\",0,\"goals\"],\"value\":10}],\"analysis\":\"Complete user-facing Markdown answer and limitations\"}. query is the zero-based call index, path locates a scalar field in the result, and value must match exactly in value and type. At most 600 fact references. analysis should answer the original question naturally with useful numerical tables, comparisons and conditional recommendations, not just a qualitative summary. Reference important raw numbers in facts; explain derived calculations. Do not invent numbers or claim that all interpretation is program-verified. Start with a concise judgment, select relevant metrics, explain their meaning, then describe actual limitations. Similar minutes do not equal similar opponents, competitions or roles; more defensive events do not alone imply greater ability. For player comparisons, include both real identities and query each player_profile and season player_timeline(matches), completing relevant pages. season is the season being analyzed. Title-race questions must call title_race_status; the program publishes the mathematical condition, so analysis must not independently announce a clinch. Missing data still requires this structure. If all relevant queries fail or are empty, facts may be empty; explain attempted scope, actual errors, absent fields and unavailable conclusions. An unread unrelated page does not invalidate all available evidence. Analyze complete data without asserting totals for incomplete scopes. Missing profiles or opponents permit descriptions, not definitive replacement recommendations. Follow the requested response language for analysis; JSON keys and reference paths remain unchanged."


def championship(rows,club_uid):
    if len(rows)!=20 or len({r.get('club_uid') for r in rows})!=20:
        return {'error':"Standings must contain 20 unique clubs."}
    for r in rows:
        if any(type(r.get(k)) is not int for k in ('played','points','won','drawn','lost')):
            return {'error':"Standings fields are missing."}
        if not 0<=r['played']<=38 or r['played']!=r['won']+r['drawn']+r['lost'] or r['points']!=3*r['won']+r['drawn']:
            return {'error':"Points or match counts are inconsistent. Check deductions or special rules."}
    team=next((r for r in rows if r['club_uid']==club_uid),None)
    if team is None:return {'error':"The target club is not in the Premier League table."}
    ceiling=max(r['points']+3*(38-r['played']) for r in rows if r['club_uid']!=club_uid)
    return dict(club_uid=club_uid,club_name=team['club_name'],points=team['points'],games_remaining=38-team['played'],rival_max_possible_points=ceiling,
        mathematically_clinched=team['points']>ceiling,
        note="Assumes three points per win and 38 games, with no future sanctions or rule changes. A strict lead over all rivals' maximum points confirms a sufficient condition. Otherwise only this condition is unproven; tie-breaks are not modeled.")


def at_path(value,path):
    if not isinstance(path,list) or not 1<=len(path)<=8:raise ValueError("Invalid field path")
    for key in path:
        if isinstance(value,dict) and isinstance(key,str):value=value[key]
        elif isinstance(value,list) and type(key) is int and 0<=key<len(value):value=value[key]
        else:raise ValueError("Field path does not exist")
    if value is not None and type(value) not in (str,int,float,bool):raise ValueError("Only scalar references are allowed")
    if isinstance(value,float) and not math.isfinite(value):raise ValueError("Non-finite number")
    return value


def validate_answer(raw,queries,cutoff,question=""):
    errors=[];facts=[];warnings=[]
    try:
        cleaned=raw.strip()
        if cleaned.startswith('```') and cleaned.endswith('```'):
            cleaned=re.sub(r'^```(?:json)?\s*','',cleaned,flags=re.IGNORECASE)[:-3].strip()
        doc=json.loads(cleaned)
        if not isinstance(doc,dict) or set(doc)!={'season','comparison_player_ids','facts','analysis'}:raise ValueError("Answer structure does not match the validation schema")
        if not isinstance(doc['season'],str) or not isinstance(doc['analysis'],str) or not isinstance(doc['facts'],list) or len(doc['facts'])>600:raise ValueError("Invalid answer fields")
        if not re.fullmatch(r'\d{4}/\d{2}',doc['season']):raise ValueError("Invalid season format")
        ids=doc['comparison_player_ids']
        if not isinstance(ids,list) or any(not isinstance(x,str) for x in ids):raise ValueError("Invalid comparison identities")
        comparison=any(w in question.lower() for w in INPUT_ALIASES['comparison'])
        title_question=any(w in question.lower() for w in INPUT_ALIASES['title'])
        if comparison and len(set(ids))<2:warnings.append("Selection comparisons need both identities and evidence. Only describe available data; do not make definitive superiority or starter-replacement recommendations")
        if ids and len(set(ids))<2:warnings.append("Both comparison identities were not provided. Only describe available data; do not make definitive superiority or starter-replacement recommendations")
        successful=[];groups={}
        for i,q in enumerate(queries):
            r=q['result'];a=q['arguments'];a=json.loads(a) if isinstance(a,str) else a
            if r.get('error') or q['name']=='story_memory':continue
            if title_question and any(w in question.lower() for w in INPUT_ALIASES['current']) and q['name']=='title_race_status' and r.get('as_of')!=cutoff:errors.append("Current title-race judgment lacks standings for the selected date")
            if r.get('snapshot_date')!=cutoff:errors.append("Query cutoff date mismatch")
            if a.get('season') and a['season']!=doc['season']:errors.append("Query season mismatch")
            if q['name']=='player_timeline' and ids:
                year=int(doc['season'][:4])
                if a['start_date']!=f'{year}-07-01' or a['end_date']!=min(cutoff,f'{year+1}-06-30'):warnings.append("Match dates do not cover the discussion season. Only describe available data; do not make definitive superiority or starter-replacement recommendations")
            if 'total' in r and 'offset' in r:
                key=(q['name'],json.dumps({k:v for k,v in a.items() if k!='offset'},sort_keys=True))
                groups.setdefault(key,[]).append(r)
            successful.append((i,q,a))
        if title_question and not any(q['name']=='title_race_status' for _,q,_ in successful):errors.append("Title-race question lacks the programmatic points calculation")
        for (tool_name,filters),pages in groups.items():
            total=pages[0]['total'];covered=set()
            for p in pages:
                if p['total']!=total:errors.append("Pagination totals are inconsistent")
                covered.update(range(p['offset'],p['offset']+len(p.get('rows',[]))))
            if covered!=set(range(total)):
                a=json.loads(filters)
                scope=' / '.join(str(a[k]) for k in ('club_name','player_id','season','section','kind','start_date','end_date') if a.get(k) is not None)
                warnings.append(f'{tool_name} ({scope}): retrieved {len(covered.intersection(range(total)))}/{total} records. Unread records remain unknown; do not claim complete totals, rankings or comparisons for this scope.')
        for pid in set(ids):
            if not any(q['name']=='player_profile' and a.get('player_id')==pid and q['result'].get('season_statistics') for _,q,a in successful):warnings.append("A comparison player's attributes and competition splits are missing. Only describe available data; do not make definitive superiority or starter-replacement recommendations")
            if not any(q['name']=='player_timeline' and a.get('player_id')==pid and a.get('section')=='matches' and any(r.get('appearance_status')=='confirmed_minutes' for r in q['result'].get('rows',[])) for _,q,a in successful):warnings.append("A comparison player's confirmed match evidence is missing. Only describe available data; do not make definitive superiority or starter-replacement recommendations")
        for fact_index,f in enumerate(doc['facts']):
            if not isinstance(f,dict) or set(f)!={'query','path','value'} or type(f['query']) is not int or not 0<=f['query']<len(queries):raise ValueError("Invalid fact reference")
            q=queries[f['query']]
            if q['name']=='story_memory' and (len(f['path'])!=3 or f['path'][0]!='rows' or f['path'][2] not in ('text','user_prompt','role','message_id')):
                raise ValueError('Conversation memory references must identify original text or its speaker, not verified game statistics')
            if q['result'].get('error'):raise ValueError("Reference points to a failed query")
            actual=at_path(q['result'],f['path'])
            if actual is None:
                if f['value'] is not None:raise ValueError(f'Reference {fact_index+1} replaces a null with a concrete value')
                facts.append(f"Tool {q['name']} · {json.dumps(f['path'],ensure_ascii=False)} = null (field is empty, not zero; null next_offset means no next page)")
                continue
            if type(actual)!=type(f['value']) or actual!=f['value']:raise ValueError(f'Reference {fact_index+1} has a value or type mismatch with the tool result')
            prefix='Original conversation only; not verified game facts · ' if q['name']=='story_memory' else ''
            facts.append(prefix+f"Tool {q['name']} · {json.dumps(f['path'],ensure_ascii=False)} = {json.dumps(actual,ensure_ascii=False)}")
        if not facts:
            unavailable=bool(queries) and all(q['result'].get('error') or ('rows' in q['result'] and not q['result']['rows']) for q in queries)
            if unavailable:
                warnings.append("Relevant queries failed or returned no records. No data fact can be established; an empty result does not prove an event never happened.")
            else:errors.append("No verifiable fact references")
    except json.JSONDecodeError as exc:
        errors.append(f'Answer is not valid JSON: line {exc.lineno}, column {exc.colno} ({exc.msg})');doc={}
    except (ValueError,KeyError,TypeError,IndexError) as exc:
        detail=str(exc) if isinstance(exc,ValueError) else "Invalid reference path or field type"
        errors.append("Structured answer validation failed: "+detail);doc={}
    errors=list(dict.fromkeys(errors))
    if errors:return {'passed':False,'errors':errors,'text':"This response failed evidence checks; the unverified analysis is not displayed.\n\n"+ '\n'.join('- '+e for e in errors)}
    conclusions=[]
    for _,q,_ in successful:
        if q['name']=='title_race_status':
            conclusions.append(str(q['result'].get('club_name',"Target club"))+' · '+str(q['result'].get('as_of',''))+': '+("The strict maximum-points condition is satisfied: mathematically clinched." if q['result']['mathematically_clinched'] else "The strict maximum-points condition does not establish a clinch. This does not prove that the title is still undecided under every tie-break scenario."))
    text=''
    if conclusions:text+="\n\n**Programmatic conclusion**\n\n"+'\n'.join(conclusions)
    if not title_question:
        text+='\n\n'+doc['analysis']
    else:text+="\n\nOnly the program-verifiable points condition is published here, not title probabilities or unverified title claims."
    warnings=list(dict.fromkeys(warnings))
    if warnings:text+="\n\n**Missing information and conclusion boundaries**\n\n"+'\n'.join('- '+w for w in warnings)
    return dict(passed=True,partial=bool(warnings),errors=[],warnings=warnings,verified_facts=facts,text=text.strip())


def partial_report(queries):
    """Local deterministic fallback; never release an unvalidated model draft."""
    groups={}
    for q in queries:
        r=q.get('result',{})
        if r.get('error'):continue
        a=q.get('arguments',{})
        if isinstance(a,str):
            try:a=json.loads(a)
            except ValueError:continue
        key=(q['name'],json.dumps({k:v for k,v in a.items() if k!='offset'},sort_keys=True))
        g=groups.setdefault(key,dict(a=a,total=r.get('total'),rows={},date=r.get('snapshot_date')))
        for i,row in enumerate(r.get('rows',[])):g['rows'][r.get('offset',0)+i]=row
    lines=["**Retrieved data is preserved. The following summary is produced directly by the program without another model call.**"]
    for (name,_),g in groups.items():
        count=len(g['rows']);total=g['total']
        if total is None:continue
        label={'league_team_data':"Team data",'injury_history':"Injury records",'season_statistics':"Season statistics"}.get(name,name)
        lines.append(f"- {label}: retrieved {count}/{total} records; through {g['date']}.")
        if name=='league_team_data' and g['a'].get('section')=='stats' and count==total:
            rows=sorted(g['rows'].values(),key=lambda x:x.get('minutes') or 0,reverse=True)[:6]
            lines.append("\nFully retrieved "+g['a'].get('season','')+" season / "+g['a'].get('kind','')+" statistics; the six players with the most minutes follow:\n")
            lines.append("| Player | Minutes | Goals | Assists |\n|---|---:|---:|---:|")
            for r in rows:
                vals=[r.get(k) for k in ('player_name','minutes','goals','assists')]
                lines.append('| '+' | '.join("Unknown" if v is None else str(v).replace('|','/') for v in vals)+' |')
    lines.append("\n**Incomplete coverage**: some pages remain unread, so complete injury totals or comparisons are unavailable. The model's free-form analysis was not released; retrieved records remain available in query evidence.")
    return '\n'.join(lines)
