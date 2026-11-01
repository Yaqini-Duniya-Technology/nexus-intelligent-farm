"""Read-only contextual help catalogue and standalone guide rendering."""
import json
from functools import lru_cache
from html import escape
from pathlib import Path
from urllib.parse import urlencode,urlparse,parse_qs

ROOT=Path(__file__).parent


@lru_cache(maxsize=1)
def catalog():
    data=json.loads((ROOT/'help_catalog.json').read_text(encoding='utf-8'))
    if data.get('catalog_version')!='nexus-guides-v1' or len(data.get('topics',[]))<50:raise ValueError('Invalid help catalogue')
    ids=[t['id'] for t in data['topics']]
    if len(set(ids))!=len(ids):raise ValueError('Duplicate help topic')
    for topic in data['topics']:
        if not all(topic.get(k) for k in ('id','title','category','routes','purpose','steps','save_effect','after_save')):raise ValueError('Incomplete help topic')
        for field in topic['fields']:
            if not all(isinstance(field.get(k),str) and field[k].strip() for k in ('selector','label','meaning','example')):raise ValueError('Incomplete field help')
    return data


def topic_by_id(tid):
    topic=next((t for t in catalog()['topics'] if t['id']==tid),None)
    if topic is None:raise ValueError('Help topic not found')
    return topic


def context(path,view=''):
    if not isinstance(path,str) or len(path)>200 or not path.startswith('/'):raise ValueError('Use a local page path')
    parsed=urlparse(path)
    if parsed.scheme or parsed.netloc:raise ValueError('Use a local page path')
    path=parsed.path
    if not view:view={'/workbench':'home','/evidence-studio':'measurements','/resources':'overview','/market':'overview'}.get(path,'')
    return [topic for topic in catalog()['topics'] if any(route['path']==path and ('view' not in route or route['view']==view) for route in topic['routes'])]


def search(q='',category='',path='',view=''):
    if not isinstance(q,str) or len(q)>200:raise ValueError('Help search is limited to 200 characters')
    if not isinstance(category,str) or len(category)>100:raise ValueError('Invalid category')
    topics=context(path,view) if path else catalog()['topics']
    words=q.casefold().split()
    return [t for t in topics if (not category or t['category']==category) and all(w in json.dumps(t,ensure_ascii=False).casefold() for w in words)]


def topic_html(topic):
    t=lambda x:escape(str(x))
    content='<article class="nxh-guide" id="guide-'+t(topic['id'])+'"><h2>'+t(topic['title'])+'</h2><p>'+t(topic['purpose'])+'</p><h3>Before you save</h3><ol>'
    content+=''.join('<li>'+t(step)+'</li>' for step in topic['steps'])+'</ol><h3>What this action does</h3><p>'+t(topic['save_effect'])+'</p><h3>What to enter</h3>'
    if not topic['fields']:content+='<p>This guide is for a reading/checking workflow rather than a data-entry form. No farm values need to be invented to use it.</p>'
    content+='<p class="nxh-example-notice">'+t(topic['example_notice'])+'</p>'
    for field in topic['fields']:
        content+='<section class="nxh-field-guide"><h4>'+t(field['label'])+'</h4><p>'+t(field['meaning'])+'</p><details><summary>Show a fictional example</summary><p class="nxh-example">'+t(field['example'])+'</p></details></section>'
    return content+'<h3>After using this page</h3><p>'+t(topic['after_save'])+'</p></article>'


def centre(query):
    q=query.get('q','');category=query.get('category','');path=query.get('path','');view=query.get('view','');tid=query.get('topic','')
    topics=[topic_by_id(tid)] if tid else search(q,category,path,view)
    t=lambda x:escape(str(x),quote=True)
    html='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NEXUS help centre</title><link rel="stylesheet" href="/ops-assets/page_guides.css"><script defer src="/ops-assets/page_guides.js"></script></head><body data-nxh-centre="1"><header class="nxh-centre-header"><small>LOCAL USER GUIDANCE</small><h1>NEXUS Help Centre</h1><p>Learn what each page does, what to enter and what saving changes.</p><nav><a href="/workbench">Operations</a> · <a href="/evidence-studio">Evidence Studio</a> · <a href="/">Original workspace</a></nav></header><main class="nxh-centre" data-nxh-ui="1"><p>Help is read-only. Examples are fictional and are never inserted into your forms. This remains a local single-user workspace; Help does not authenticate separate users.</p>'''
    html+='<form method="get" action="/help-centre" class="nxh-centre-search"><label>Find guidance<input name="q" maxlength="200" value="'+t(q)+'"></label><label>Category<select name="category"><option value="">All categories</option>'
    for name in sorted({x['category'] for x in catalog()['topics']}):html+='<option'+(' selected' if category==name else '')+'>'+t(name)+'</option>'
    html+='</select></label><button>Search guides</button><a href="/help-centre">Show all guides</a></form>'
    html+='<p>'+str(len(topics))+' guided workflows shown.</p>'
    if not topics:html+='<p>No guide matched. Try a shorter term, remove a category or use Show all guides.</p>'
    if not tid:
        html+='<nav class="nxh-topic-index" aria-label="Guide topics">'
        for topic in topics:html+='<a href="/help-centre?topic='+t(topic['id'])+'">'+t(topic['title'])+'</a>'
        html+='</nav>'
    for topic in topics:
        html+=topic_html(topic)+'<p class="nxh-centre-actions"><a href="/api/help/download?topic='+t(topic['id'])+'">Download standalone HTML guide</a> · <a href="/help-centre?topic='+t(topic['id'])+'">Link to this guide</a></p>'
    html+='<section><h2>Terms used in NEXUS</h2><dl>'
    for term,meaning in catalog()['glossary'].items():html+='<dt>'+t(term)+'</dt><dd>'+t(meaning)+'</dd>'
    html+='</dl></section><section><h2>Privacy and limits</h2><p>'+t(catalog()['privacy'])+'</p><p>'+t(catalog()['limits'])+'</p></section><noscript><p>The guides and search form above work without JavaScript. The in-page help panel needs JavaScript; no form values are changed if it is unavailable.</p></noscript></main></body></html>'
    return html.encode('utf-8')


def standalone(tid):
    topic=topic_by_id(tid)
    style=(ROOT/'page_guides.css').read_text(encoding='utf-8')
    raw='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+escape(topic['title'])+'</title><style>'+style+'</style></head><body><main class="nxh-centre"><h1>NEXUS offline guide</h1><p>Print this page using your browser. This guide explains the interface; it contains no copy of your farm records.</p>'+topic_html(topic)+'<p>'+escape(catalog()['limits'])+'</p></main></body></html>'
    return raw.encode('utf-8')


def inject(raw,request_path):
    """Add an independent help surface; never rewrite forms, exports or frozen payloads."""
    if not isinstance(raw,bytes):return raw
    try:html=raw.decode('utf-8')
    except UnicodeDecodeError:return raw
    if 'data-nxh-boot="1"' in html or 'data-nxh-centre="1"' in html:return raw
    parsed=urlparse(request_path);path=parsed.path
    if path.startswith(('/api/','/ops-assets/')):return raw
    query=parse_qs(parsed.query);view=query.get('view',[''])[0] or (query.get('kind',[''])[0] if path in ('/resources','/market') else '')
    link='/help-centre?'+urlencode({'path':path,'view':view})
    assets='<link rel="stylesheet" href="/ops-assets/page_guides.css" data-nxh-boot="1"><script defer src="/ops-assets/page_guides.js"></script>'
    fallback='<div class="nxh-fallback" data-nxh-ui="1"><a href="'+escape(link,quote=True)+'">Help for this page — field meanings and examples</a></div>'
    pos=html.lower().rfind('</body>')
    injection=assets+fallback
    html=html[:pos]+injection+html[pos:] if pos>=0 else html+injection
    return html.encode('utf-8')
