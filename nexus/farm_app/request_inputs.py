"""Strict, bounded input at the combined local server boundary."""
import json
from urllib.parse import urlparse

class RequestError(ValueError):
    def __init__(self,message,status=400):super().__init__(message);self.status=status


def parse_object(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise RequestError('Duplicate JSON field: '+key[:80])
            result[key]=value
        return result
    def constant(value):raise RequestError('JSON numbers must be finite')
    try:
        result=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=constant)
    except UnicodeDecodeError:raise RequestError('Request must contain UTF-8 JSON') from None
    except (json.JSONDecodeError,RecursionError):raise RequestError('Invalid or excessively nested JSON object') from None
    if not isinstance(result,dict):raise RequestError('Expected a JSON object')
    # JSON may accept a finite-looking exponent which overflows float.
    import math
    pending=[(result,0)]
    while pending:
        value,depth=pending.pop()
        if depth>64:raise RequestError('JSON nesting is limited to 64 levels')
        if isinstance(value,float) and not math.isfinite(value):raise RequestError('JSON numbers must be finite')
        if isinstance(value,dict):pending.extend((v,depth+1) for v in value.values())
        elif isinstance(value,list):pending.extend((v,depth+1) for v in value)
    return result


def read_request(handler):
    headers=handler.headers;path=urlparse(handler.path).path
    if headers.get_all('Transfer-Encoding'):raise RequestError('Transfer-Encoding is not supported; send one Content-Length')
    if headers.get('Content-Encoding','identity').strip().lower() not in ('','identity'):raise RequestError('Compressed request bodies are not supported',415)
    lengths=headers.get_all('Content-Length',[])
    if len(lengths)!=1 or not lengths[0].isascii() or not lengths[0].isdigit():raise RequestError('Send exactly one positive Content-Length')
    size=int(lengths[0]);limit=2000000 if path=='/api/voice-drafts' else 3000000 if path=='/api/photos' else 262144 if path.startswith('/api/studio/') else 65536
    if not 0<size<=limit:raise RequestError('Request exceeds the route limit or is empty',413)
    types=headers.get_all('Content-Type',[])
    if len(types)!=1:raise RequestError('Send one Content-Type header',415)
    media=headers.get_content_type().lower()
    if path=='/api/voice-drafts':
        if media!='audio/wav':raise RequestError('This route accepts audio/wav',415)
    elif media!='application/json' or (headers.get_content_charset() or 'utf-8').lower() not in ('utf-8','utf8'):
        raise RequestError('Use application/json with UTF-8 encoding',415)
    previous=handler.connection.gettimeout()
    try:
        handler.connection.settimeout(10)
        raw=handler.rfile.read(size)
    except TimeoutError:raise RequestError('Request body timed out; check saved records before retrying',408) from None
    finally:handler.connection.settimeout(previous)
    if len(raw)!=size:raise RequestError('Incomplete request body')
    if path!='/api/voice-drafts':parse_object(raw)
    return raw
