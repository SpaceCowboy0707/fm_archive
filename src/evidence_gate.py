"""Deterministic evidence checks; free-form interpretation is not certified."""
import json
import math
import re
from src.i18n import INPUT_ALIASES

INSTRUCTIONS="Evidence validation is enabled. After querying, the final answer must be one JSON object without code fences: {\"season\":\"2035/36\",\"comparison_player_ids\":[],\"facts\":[{\"query\":0,\"path\":[\"rows\",0,\"goals\"],\"value\":10}],\"analysis\":\"Complete user-facing Markdown answer and limitations\"}. query is the query_index field printed in that tool result, path locates a scalar field in the result, and value must match exactly in value and type. Every record in a returned list carries its own row_index: use it as the list position in path (for example [\"rows\",<row_index>,\"goals\"]) and never count positions yourself. Copy values exactly as returned, without rounding. To show that no records were returned, a path may end at an empty list or object and cite [] or {}. At most 600 fact references. analysis should answer the original question naturally with useful numerical tables, comparisons and conditional recommendations, not just a qualitative summary. Reference important raw numbers in facts; explain derived calculations. Do not invent numbers or claim that all interpretation is program-verified. Start with a concise judgment, select relevant metrics, explain their meaning, then describe actual limitations. Similar minutes do not equal similar opponents, competitions or roles; more defensive events do not alone imply greater ability. For player comparisons, include both real identities and query each player_profile and season player_timeline(matches), completing relevant pages. season is the season being analyzed. Title-race questions must call title_race_status; the program publishes the mathematical condition, so analysis must not independently announce a clinch. Missing data still requires this structure. If all relevant queries fail or are empty, facts may be empty; explain attempted scope, actual errors, absent fields and unavailable conclusions. An unread unrelated page does not invalidate all available evidence. Analyze complete data without asserting totals for incomplete scopes. Missing profiles or opponents permit descriptions, not definitive replacement recommendations. Follow the requested response language for analysis; JSON keys and reference paths remain unchanged. Optionally add \"charts\", a list of at most 6 chart specs, when a chart shows the answer better than a table or when the user asks for one: {\"type\":\"bar|hbar|line|scatter|pie\",\"title\":\"...\",\"query\":<query_index>,\"records\":[\"rows\"],\"label\":\"player_name\",\"x\":\"expected_goals\",\"y\":[\"goals\"],\"sort\":\"desc|asc|none\",\"limit\":15,\"diagonal\":true}. query may also be a list of query_index values for the pages of one lookup, whose records are joined; records is the path to a list of records in that tool result; label names each bar, slice or point; x is required for scatter (numeric) and line (date, season or number); y is a list of numeric fields, one per series (scatter and pie take exactly one; bar, hbar and line up to three). Fields are names or short paths such as [\"totals\",2], which follows that result's metric_columns. Never write chart values yourself: the program reads every plotted value from the tool result, and a spec that does not resolve is dropped with its reason. Use hbar for long player names, pie only for parts of one whole (at most 8 slices; the rest fold into Other), diagonal for a y=x reference such as goals against xG. Place a chart inside analysis by writing [[chart:N]] on its own line (N counts from 1); charts not placed appear after the analysis."


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
    # An empty list or object may be cited to show that no records were returned.
    if value is not None and type(value) not in (str,int,float,bool) and value not in ([],{}):raise ValueError("Only scalar references or empty lists/objects are allowed")
    if isinstance(value,float) and not math.isfinite(value):raise ValueError("Non-finite number")
    return value


def located(result,path,value):
    """Hint where a mismatched value actually sits: same field, another position in the same list."""
    if not isinstance(path,list) or len(path)<2 or not isinstance(path[0],str) or type(path[1]) is not int:return ''
    records=result.get(path[0]) if isinstance(result,dict) else None
    if not isinstance(records,list):return ''
    found=[]
    for i in range(len(records)):
        if i==path[1]:continue
        try:candidate=at_path(result,[path[0],i,*path[2:]])
        except (ValueError,KeyError):continue
        if candidate is not None and type(candidate)==type(value) and candidate==value:found.append(i)
    if not found:return ''
    return '. The cited value appears at '+', '.join(json.dumps([path[0],i,*path[2:]],ensure_ascii=False) for i in found[:3])+'; use the row_index of the intended record'


# These failures need different queries, so a tool-free answer repair cannot fix them.
NEEDS_NEW_QUERIES={"Current title-race judgment lacks standings for the selected date","Query cutoff date mismatch","Query season mismatch",
                   "Title-race question lacks the programmatic points calculation","Pagination totals are inconsistent"}


def strip_fence(raw):
    cleaned=raw.strip()
    if cleaned.startswith('```') and cleaned.endswith('```'):
        cleaned=re.sub(r'^```(?:json)?\s*','',cleaned,flags=re.IGNORECASE)[:-3].strip()
    return cleaned


REFERENCE_ERROR=re.compile(r'^Reference (\d+): ')


def failed_references(errors):
    """Reference numbers when every error concerns an individual reference; otherwise None (needs a full rewrite)."""
    numbers=[REFERENCE_ERROR.match(e) for e in errors]
    return sorted({int(m.group(1)) for m in numbers}) if errors and all(numbers) else None


def apply_fixes(raw,fixes_raw,failed):
    """Replace or drop only the failed references; the analysis text is kept verbatim. Returns (raw, removed)."""
    doc=json.loads(strip_fence(raw))
    fixes=json.loads(strip_fence(fixes_raw))
    if not isinstance(fixes,dict) or not isinstance(fixes.get('fixes'),list):raise ValueError('Repair must be {"fixes":[...]}')
    replaced={}
    for fix in fixes['fixes']:
        if not isinstance(fix,dict) or set(fix)!={'reference','fact'} or fix['reference'] not in failed:raise ValueError("Each fix must name one failed reference")
        if fix['fact'] is not None and not isinstance(fix['fact'],dict):raise ValueError("A fix must be a fact object or null")
        replaced[fix['reference']]=fix['fact']
    if set(replaced)!=set(failed):raise ValueError("Every failed reference needs exactly one fix")
    doc['facts']=[replaced.get(n,f) for n,f in enumerate(doc['facts'],1)]
    removed=sum(f is None for f in doc['facts'])
    doc['facts']=[f for f in doc['facts'] if f is not None]
    return json.dumps(doc,ensure_ascii=False),removed


def validate_answer(raw,queries,cutoff,question="",notes=()):
    errors=[];facts=[];warnings=list(notes)
    try:
        doc=json.loads(strip_fence(raw))
        required={'season','comparison_player_ids','facts','analysis'}
        if not isinstance(doc,dict) or not required<=set(doc) or not set(doc)<=required|{'charts'}:raise ValueError("Answer structure does not match the validation schema")
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
        # Check every reference and report each problem precisely, so the answer can be repaired in one pass.
        for fact_index,f in enumerate(doc['facts']):
            label=f'Reference {fact_index+1}'
            if not isinstance(f,dict) or set(f)!={'query','path','value'} or type(f['query']) is not int or not 0<=f['query']<len(queries):
                errors.append(f'{label}: invalid structure or query index outside 0–{len(queries)-1}');continue
            q=queries[f['query']]
            where=f"query {f['query']} ({q['name']}) path {json.dumps(f['path'],ensure_ascii=False)}"
            if q['name']=='story_memory' and (not isinstance(f['path'],list) or len(f['path'])!=3 or f['path'][0]!='rows' or f['path'][2] not in ('text','user_prompt','role','message_id')):
                errors.append(f'{label}: conversation memory references must identify original text or its speaker, not verified game statistics');continue
            if q['result'].get('error'):errors.append(f'{label}: {where} points to a failed query');continue
            try:actual=at_path(q['result'],f['path'])
            except (ValueError,KeyError) as exc:
                reason=str(exc) if isinstance(exc,ValueError) else "Field path does not exist"
                errors.append(f'{label}: {where}: {reason}'+located(q['result'],f['path'],f['value']));continue
            if actual is None:
                if f['value'] is not None:errors.append(f'{label}: {where} is null, but the reference cites {json.dumps(f["value"],ensure_ascii=False)}');continue
                facts.append(f"Tool {q['name']} · {json.dumps(f['path'],ensure_ascii=False)} = null (field is empty, not zero; null next_offset means no next page)")
                continue
            if type(actual)!=type(f['value']) or actual!=f['value']:
                errors.append(f'{label}: {where} cites {json.dumps(f["value"],ensure_ascii=False)}, but the tool returned {json.dumps(actual,ensure_ascii=False)}'+located(q['result'],f['path'],f['value']));continue
            prefix='Original conversation only; not verified game facts · ' if q['name']=='story_memory' else ''
            facts.append(prefix+f"Tool {q['name']} · {json.dumps(f['path'],ensure_ascii=False)} = {json.dumps(actual,ensure_ascii=False)}")
        # When references were cited but failed, those errors already explain the gap and remain repairable.
        if not facts and not any(REFERENCE_ERROR.match(e) for e in errors):
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
    if errors:return {'passed':False,'errors':errors,'repairable':not any(e in NEEDS_NEW_QUERIES for e in errors),'text':"This response failed evidence checks; the unverified analysis is not displayed.\n\n"+ '\n'.join('- '+e for e in errors)}
    conclusions=[]
    for _,q,_ in successful:
        if q['name']=='title_race_status':
            conclusions.append(str(q['result'].get('club_name',"Target club"))+' · '+str(q['result'].get('as_of',''))+': '+("The strict maximum-points condition is satisfied: mathematically clinched." if q['result']['mathematically_clinched'] else "The strict maximum-points condition does not establish a clinch. This does not prove that the title is still undecided under every tie-break scenario."))
    text=''
    if conclusions:text+="\n\n**Programmatic conclusion**\n\n"+'\n'.join(conclusions)
    charts,chart_notes=draw_charts(doc.get('charts'),queries)
    if not title_question:
        text+='\n\n'+place_charts(doc['analysis'],charts)
        if chart_notes:text+='\n\n'+'\n'.join('- '+n for n in chart_notes)
    else:text+="\n\nOnly the program-verifiable points condition is published here, not title probabilities or unverified title claims."
    warnings=list(dict.fromkeys(warnings))
    if warnings:text+="\n\n**Missing information and conclusion boundaries**\n\n"+'\n'.join('- '+w for w in warnings)
    return dict(passed=True,partial=bool(warnings),errors=[],warnings=warnings,verified_facts=facts,
                charts=[c['title'] for c in charts.values()],chart_notes=chart_notes,text=text.strip())


def draw_charts(specs,queries):
    """Resolve chart specs against the tool results; a bad spec is dropped with its reason, never blocking the answer."""
    from src.charts import resolve, MAX_CHARTS
    charts,notes={},[]
    if specs is None:return charts,notes
    if not isinstance(specs,list):return charts,["Charts were omitted: charts must be a list."]
    for n,spec in enumerate(specs,1):
        if n>MAX_CHARTS:notes.append(f"Chart {n} was omitted: at most {MAX_CHARTS} charts per answer.");continue
        try:charts[n]=resolve(spec,queries)
        except ValueError as exc:notes.append(f"Chart {n} was omitted: {exc}.")
    return charts,notes


def place_charts(analysis,charts):
    """Put each chart where the analysis writes [[chart:N]]; charts not placed follow the analysis."""
    block=lambda n:'\n\n```chart\n'+json.dumps(charts[n],ensure_ascii=False)+'\n```\n\n'
    placed=set()
    def swap(match):
        n=int(match.group(1))
        if n not in charts or n in placed:return ''
        placed.add(n);return block(n)
    text=re.sub(r'\[\[chart:(\d+)\]\]',swap,analysis)
    return text+''.join(block(n) for n in charts if n not in placed)


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
