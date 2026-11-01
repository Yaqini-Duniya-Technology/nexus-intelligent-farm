"""High-contrast project attribution, with no tracking or record identifiers."""
from urllib.parse import urlparse
COMPANY_URL='https://yd.ydtech.workers.dev'
FOOTER='''<aside data-nexus-brand="1" data-nxh-ui="1" aria-label="Project developer" style="display:block;clear:both;background:#12372b;color:#ffffff;padding:20px 24px;margin-top:28px;font:16px/1.6 system-ui;border-top:4px solid #d5b85a"><strong>Built by <a href="https://yd.ydtech.workers.dev" target="_blank" rel="noopener noreferrer" style="color:#ffe49a;text-decoration:underline;text-underline-offset:4px;font-weight:750">Yaqini &amp; Duniya Technology</a></strong><p style="margin:6px 0 0">Practical technology for reliable field records. <a href="/resources" style="color:#ffffff;text-decoration:underline">Resource workspace</a> · <a href="/market" style="color:#ffffff;text-decoration:underline">Produce &amp; Market</a> · <a href="/help-centre" style="color:#ffffff;text-decoration:underline">Help Centre</a></p><small>Company website opens in a new tab. No farm record is added to the link.</small></aside>'''

def inject(raw,path):
    if not isinstance(raw,bytes) or urlparse(path).path.startswith(('/api/','/ops-assets/')):return raw
    try:html=raw.decode('utf-8')
    except UnicodeDecodeError:return raw
    if 'data-nexus-brand="1"' in html:return raw
    end=html.lower().rfind('</body>')
    return (html[:end]+FOOTER+html[end:] if end>=0 else html+FOOTER).encode('utf-8')
