# coding: utf-8
"""Evidence-scoped, deterministic statistics. No imputed scores or predictions."""
import json
from datetime import datetime, timezone

DIMENSIONS = {
 'concepts':'概念理解','causality':'因果解释','application':'独立应用','edges':'边界与测试',
 'tradeoffs':'权衡与迁移','structure':'回答结构','expression':'表达清晰度','retention':'延迟保持'}


def validate_scores(p, require):
    e, r = p['evaluation'], p['received']
    extra = e.get('rubric_scores')
    outcome = e.get('attempt_outcome')
    if extra is None and outcome is None and 'retest_of' not in e: return
    require(e['evidence_type'] in {'independent','prompted'} and bool(r.get('original_answer','').strip()), 'scores require an actual answer')
    if outcome == 'not_met':
        require(e['state'] not in {'independent_today','delayed_transfer'}, 'failure conflicts with independent success state')
    if outcome is not None:
        require(e['scope'] == 'complete' and outcome in {'met','not_met'}, 'outcome requires complete attempt')
    if 'retest_of' in e:
        require(isinstance(e['retest_of'], str) and bool(e['retest_of'].strip()), 'retest prior id required')
    if extra is None: return
    require(isinstance(extra, dict) and set(extra) == {'rubric_version','dimensions'}, 'invalid rubric')
    require(extra['rubric_version'] == 'knowloop-1', 'unsupported rubric version')
    dims = extra['dimensions']
    require(isinstance(dims, dict) and 0 < len(dims) <= 8 and set(dims) <= DIMENSIONS.keys(), 'invalid dimensions')
    for name, value in dims.items():
        require(isinstance(value, dict) and set(value) == {'score','reason'}, 'score requires reason')
        require(type(value['score']) is int and 0 <= value['score'] <= 3, 'score must be integer 0–3')
        require(isinstance(value['reason'], str) and bool(value['reason'].strip()), 'score reason required')
        if value['score'] >= 2:
            require(e['scope']=='complete' and e['evidence_type']=='independent' and not r.get('hints','').strip(), 'high score requires independent complete evidence')
        if name == 'retention':
            require('retest_of' in e or e.get('transfer',{}).get('prior_event_id'), 'retention needs linked delayed evidence')


def events(conn):
    result=[]
    for row in conn.execute('''SELECT event_id,occurred_at,mode,track,competency,received,context,body
            FROM events JOIN evaluations USING(event_id) ORDER BY occurred_at,seq'''):
        p=dict(zip(('event_id','occurred_at','mode','track','competency','received','context','evaluation'),row))
        for key in ('received','context','evaluation'): p[key]=json.loads(p[key])
        result.append(p)
    return sorted(result,key=lambda p:datetime.fromisoformat(p['occurred_at'].replace('Z','+00:00')))


def metrics(records, track=None, competency=None, since=None):
    scope=[p for p in records if (not track or p['track']==track) and (not competency or p['competency']==competency) and (not since or datetime.fromisoformat(p['occurred_at'].replace('Z','+00:00'))>=datetime.fromisoformat(since.replace('Z','+00:00')))]
    attempted=[p for p in scope if p['evaluation']['evidence_type'] in {'independent','prompted'}]
    complete=[p for p in attempted if p['evaluation']['scope']=='complete']
    unhinted=[p for p in complete if p['evaluation']['evidence_type']=='independent' and not p['received'].get('hints','').strip()]
    # Legacy events with no explicit outcome are excluded, never inferred as pass/fail.
    assessed=[p for p in unhinted if 'attempt_outcome' in p['evaluation']]
    hints=[p for p in complete if p['evaluation']['evidence_type']=='prompted' or p['received'].get('hints','').strip()]
    lookup={p['event_id']:p for p in records}
    retests=[]
    for p in complete:
        prior_id=p['evaluation'].get('retest_of') or p['evaluation'].get('transfer',{}).get('prior_event_id')
        if prior_id not in lookup or 'attempt_outcome' not in p['evaluation']: continue
        old=lookup[prior_id]
        delta=datetime.fromisoformat(p['occurred_at'].replace('Z','+00:00'))-datetime.fromisoformat(old['occurred_at'].replace('Z','+00:00'))
        retests.append(dict(event_id=p['event_id'],track=p['track'],competency=p['competency'],days=round(delta.total_seconds()/86400,2),met=p['evaluation']['attempt_outcome']=='met' and p in unhinted,helped=p in hints))
    radar={}; trend=[]
    for p in attempted:
        scores=p['evaluation'].get('rubric_scores')
        if not scores: continue
        for name, value in scores['dimensions'].items():
            obs=dict(**value,event_id=p['event_id'],occurred_at=p['occurred_at'],helped=p in hints,dimension=name)
            # Radar is meaningful only for one explicitly selected competency.
            if competency and track: radar[name]={**obs,'count':radar.get(name,{}).get('count',0)+1}
            trend.append(dict(**obs,track=p['track'],competency=p['competency'],rubric_version=scores['rubric_version']))
    return dict(sample_count=len(attempted),incomplete=len(attempted)-len(complete),independent={'met':sum(p['evaluation']['attempt_outcome']=='met' for p in assessed),'total':len(assessed),'unscored':len(unhinted)-len(assessed)},hints={'count':len(hints),'total':len(complete)},retention={'met':sum(r['met'] for r in retests),'total':len(retests)},radar=radar,trend=trend,retests=retests,evidence=scope)
