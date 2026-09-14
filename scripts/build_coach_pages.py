#!/usr/bin/env python3
# coding: utf-8
"""Build public course catalog and explicitly synthetic dashboard demo. No private input."""
import json
import sys
from pathlib import Path
from html import escape
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'interview-coach/scripts'))
from coach_courses import validate, BUNDLED
from coach_report import render
from coach_metrics import DIMENSIONS

DEMO_COURSE = {
    'course_id': 'demo-coding',
    'title': 'Synthetic coding demonstration',
    'version': 'demo-1',
    'updated_at': '2026-09-13',
    'note': 'Explicitly synthetic data for the public dashboard preview.',
    'source_urls': ['https://example.com/knowloop-demo'],
    'weeks': [{
        'week_id': 'w1',
        'label': 'Synthetic Week 1',
        'status': 'available',
        'date_window': None,
        'tasks': [{
            'task_id': 'demo-sliding-window',
            'title': 'Synthetic sliding-window exercise',
            'track': 'Coding',
            'source_url': 'https://example.com/knowloop-demo',
            'minutes': 20,
            'prerequisites': ['Synthetic prerequisite'],
            'outcome': 'Synthetic outcome for the public preview.',
            'acceptance': ['Synthetic acceptance check'],
            'provenance': 'coach_suggestion',
        }],
    }],
}


def outputs():
    raw=BUNDLED.read_text(); data=validate(json.loads(raw))
    template=(ROOT/'interview-coach/assets/dashboard.html').read_text()
    css=template.split('<style>')[1].split('</style>')[0]
    cards=[]
    for c in data['courses']:
        weeks=[]
        for w in c['weeks']:
            tasks=''.join(f'<li><a href="{escape(t["source_url"],quote=True)}" rel="noreferrer">{escape(t["title"])}</a> <span class="pill">{escape(t["track"])}</span><p class="muted">{escape(t["outcome"])}</p></li>' for t in w['tasks'])
            weeks.append(f'<details><summary>{escape(w["label"])} · {len(w["tasks"])} tasks</summary>'+('<ul>'+tasks+'</ul>' if tasks else '<p>尚未取得正式作业。Coach 建议必须另行标注。</p>')+'</details>')
        cards.append(f'<section class="panel" id="{escape(c["course_id"])}"><div class="eyebrow">{escape(c["course_id"])}</div><h2>{escape(c["title"])}</h2><p class="muted">{escape(c["note"])}</p><p><code>coach，从 {escape(c["course_id"])} 第 1 周开始，今天 30 分钟</code></p>'+''.join(weeks)+'</section>')
    delivery = """<section class="panel" id="system-design-delivery"><h2>系统设计，从需求一步步推导到深挖</h2>
<p>Functional Requirements → Non-functional Requirements → Core Entities → Data Flow → API / System Interface → High Level Design → Deep Dives</p>
<p>陪读先讲当前环节再检查理解；练习先自己作答；Mock 由你主导、结束后复盘；复测回到已记录的薄弱环节。保存当前阶段和下一步，下次接着学。</p>
<p class="muted">参考 <a href="https://www.hellointerview.com/learn/system-design/in-a-hurry/delivery" rel="noreferrer">Hello Interview Delivery Framework</a>。原文先 API、后可选 Data Flow；这里默认先梳理数据流，再定义 API。陪读指定文章时跟随原文顺序。</p>
<p><code>$coach 陪我学 News Feed，从 Functional Requirements 开始</code></p></section>"""
    index=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KnowLoop · 学、讲、追问、复习</title><style>{css}</style></head><body><main><header><div class="brand">Know<i>Loop</i></div><a href="#courses">课程目录</a></header><section class="hero"><div><div class="eyebrow">Read → Explain → Probe → Repair → Return</div><h1>学过的东西，<br>下次能自己讲清楚。</h1><p>输入 <code>$coach</code>，从课程或你正在读的一章开始。教练安排今天的任务，依据实际回答追问、纠错，再接着上次练。</p><p><a href="dashboard-demo.html">看看学习看板 →</a></p></div><aside class="panel today"><h2>课程公开，学习记录留在你身边。</h2><p>安装后自带课程快照；计划、回答、错题和评分保存在本地。</p><p class="muted">不会凭空给“掌握度”。看完、提示后答对、独立做到、延迟复测分开记录。</p><p><code>coach，今天学什么？</code></p></aside></section><p class="muted">课程快照 {escape(data['version'])} 随安装包提供。未配置公共端点时，刷新保持离线。</p>{delivery}<div class="grid" id="courses">{''.join(cards)}</div><p class="footer"><a href="courses.json">机器可读课程数据</a> · 看板中的全部记录均为合成示例。</p></main></body></html>'''
    # Every demo row is authored here, never read from a learner root.
    records=[]
    for n,(day,score,hint) in enumerate([(1,1,True),(3,2,False),(7,2,False)]):
        ev=dict(evidence_type='prompted' if hint else 'independent',scope='complete',state='needs_hint' if hint else 'independent_today',dimensions={'mechanism':'Synthetic demonstration only.'},attempt_outcome='not_met' if hint else 'met',rubric_scores={'rubric_version':'knowloop-1','dimensions':{k:{'score':score,'reason':'Synthetic example: '+('needed a hint' if hint else 'explained the invariant independently')} for k in list(DIMENSIONS)[:7]}})
        if n==2:
            ev['retest_of']='demo-1';ev['rubric_scores']['dimensions']['retention']={'score':2,'reason':'Synthetic delayed retest after four days.'}
        records.append(dict(event_id=f'demo-{n}',occurred_at=f'2026-09-{day:02d}T12:00:00Z',track='Coding',competency='Sliding-window invariant',mode='Practice',received={'transcript':'Synthetic learner answer.','original_answer':'Maintain the counts in the current fixed-size window.','hints':'What changes when the left boundary moves?' if hint else ''},context={'course_id':'demo-coding','task_id':'demo-sliding-window','next_action':'Explain what happens when a character leaves the window.'},evaluation=ev))
    demo=dict(demo=True,generated_at='2026-09-13T12:00:00Z',enrollment={'course_id':'demo-coding','week_id':'w1','minutes':30,'timezone':'UTC'},course=DEMO_COURSE,task_states={'demo-sliding-window':{'status':'in_progress','source':'evidence'}},plan={'date':'2026-09-13','minutes':30,'items':[{'title':'Synthetic invariant review','minutes':10,'reason':'Synthetic demo review','slice':False},{'title':'Synthetic sliding-window exercise','minutes':20,'reason':'Synthetic demo task','slice':True}],'unavailable':False},records=records,repairs=[{'target':'Explain the synthetic outgoing-character update','track':'Coding','competency':'Sliding-window invariant','due_at':'2026-09-14T12:00:00Z','event_id':'demo-0'}],dimensions=DIMENSIONS)
    return {'index.html':index+'\n','courses.json':raw,'dashboard-demo.html':render(demo)}


def main():
    expected=outputs()
    if '--check' in sys.argv:
        bad=[name for name,text in expected.items() if not (ROOT/'docs'/name).exists() or (ROOT/'docs'/name).read_text()!=text]
        if bad: raise SystemExit('Public coach pages drifted: '+', '.join(bad))
    else:
        for name,text in expected.items(): (ROOT/'docs'/name).write_text(text)

if __name__=='__main__': main()
