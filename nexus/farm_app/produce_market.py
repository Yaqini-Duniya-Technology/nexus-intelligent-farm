"""A separate market ledger: user-reported quantities and money, never payment execution."""
import json
from datetime import datetime,timezone
from decimal import Decimal,ROUND_HALF_UP
from nexus.farm_app.market_catalog import SPECS
from nexus.farm_app.operations_common import instant,day,LAGOS,text,digest

D=Decimal

def money(value):return format(value.quantize(D('.01'),rounding=ROUND_HALF_UP),'f')
def normalize(kind,v,check_time=True):
    if kind not in SPECS:return v
    if 'quantity_kg' in v:
        qty=D(v['quantity_kg'])
        if kind=='produce_adjustment':
            if qty==0:raise ValueError('Record a nonzero signed quantity change')
        elif qty<=0:raise ValueError('Record a positive kilogram quantity')
    if kind=='customer_payment' and D(v['amount_ngn'])<=0:raise ValueError('Payment amount must be positive')
    if kind=='sales_order':
        today=datetime.now(timezone.utc).astimezone(LAGOS).date().isoformat()
        if check_time and v['order_date']>today:raise ValueError('Actual agreement date cannot be in the future')
        if v['due_date']<v['order_date']:raise ValueError('Delivery due date cannot predate the agreement')
    return v


def freeze(db,current,kind,fid,source,v):
    if kind!='produce_lot' or v.get('harvest_id') is None:return {}
    from nexus.farm_app.resource_logistics import external
    if source!='actual':raise ValueError('Only Actual produce lots can link an existing harvest; leave the optional harvest link blank for tests')
    record=external(db,'harvest',v['harvest_id'])
    if record['field_id']!=fid:raise ValueError('Harvest must belong to the selected field')
    return {'harvest':{'record':record,'sha256':digest(record)}}


def check_captures(row):
    p=row['payload'];v=p['values']
    if row['kind']=='produce_lot' and v.get('harvest_id') is not None:
        cap=p.get('captures',{}).get('harvest',{});record=cap.get('record',{})
        if p['source']!='actual' or record.get('id')!=v['harvest_id'] or record.get('field_id')!=row['field_id'] or digest(record)!=cap.get('sha256'):raise ValueError('Invalid frozen harvest association')


def guard(current,kind,v,old):
    """Checks which apply to new work, rather than rejecting older truthful history."""
    if kind not in SPECS:return
    def lot_ready(rid):
        if rid not in current:raise ValueError('Produce lot not found')
        if current[rid]['payload']['values']['status']!='available':raise ValueError('Lot is on hold or closed; review its availability before confirming or recording a new delivery')
    if kind=='sales_order' and not old and v['status']=='confirmed':raise ValueError('Create a draft order, add lines, then confirm')
    if kind=='sales_order' and v['status']=='confirmed' and (not old or old['payload']['values']['status']!='confirmed'):
        for e in current.values():
            x=e['payload']['values']
            if e['kind']=='sales_line' and x['order_id']==old['record_id'] and x['status']=='active':lot_ready(x['lot_id'])
    if kind=='sales_line':
        order=current.get(v['order_id'])
        if order and order['payload']['values']['status']=='confirmed' and v['status']=='active':lot_ready(v['lot_id'])
        if old:
            prior=old['payload']['values'];rid=old['record_id']
            has_delivery=any(e['kind']=='order_delivery' and e['payload']['values']['line_id']==rid for e in current.values())
            has_payment=any(e['kind']=='customer_payment' and e['payload']['values']['order_id']==prior['order_id'] for e in current.values())
            if (has_delivery or has_payment) and any(v[k]!=prior[k] for k in ('order_id','lot_id','unit_ngn')):raise ValueError('Order, lot and unit price are frozen after delivery/payment evidence; record a separate line/order for new terms')
    if kind=='order_delivery':
        line=current.get(v['line_id'])
        if line:
            x=line['payload']['values'];order=current[x['order_id']]['payload']['values']
            if x['status']!='active':raise ValueError('Choose an active order line')
            if not old and order['status']!='confirmed':raise ValueError('New deliveries require a confirmed order')
            if not old or D(v['quantity_kg'])>D(old['payload']['values']['quantity_kg']):lot_ready(x['lot_id'])
    if kind=='customer_payment':
        order=current.get(v['order_id'])
        if order and order['payload']['values']['status'] not in ('confirmed','closed'):raise ValueError('Record receipts/refunds against a confirmed or closed order')


def calculate(current):
    lots={};orders={};lines={};deliveries={};returns={};harvests={}
    for rid,e in current.items():
        k=e['kind'];v=e['payload']['values']
        if k=='produce_lot':
            lots[rid]={'record_id':rid,'name':v['name'],'crop':v['crop'],'field_id':e['field_id'],'source':e['payload']['source'],'status':v['status'],'balance_kg':D(v['quantity_kg']),'reserved_kg':D(0),'quarantined_returns_kg':D(0),'discarded_returns_kg':D(0)}
            if v['harvest_id'] is not None:
                cap=e['payload']['captures']['harvest']['record'];key=v['harvest_id'];qty,limit=harvests.get(key,(D(0),D(str(cap['quantity_kg']))));harvests[key]=(qty+D(v['quantity_kg']),min(limit,D(str(cap['quantity_kg']))))
        if k=='sales_order':orders[rid]={'record_id':rid,'name':v['name'],'field_id':e['field_id'],'source':e['payload']['source'],'status':v['status'],'due_date':v['due_date'],'order_date':v['order_date'],'total_ngn':D(0),'net_receipts_ngn':D(0),'ordered_kg':D(0),'net_delivered_kg':D(0),'active_lines':0}
        if k=='sales_line':lines[rid]={'values':v,'delivered':D(0),'returned':D(0),'gross_delivery':D(0)}
        if k=='order_delivery':deliveries[rid]=v;returns[rid]=D(0)
    if any(qty>limit for qty,limit in harvests.values()):raise ValueError('Initial produce-lot quantities exceed the frozen linked harvest quantity; do not duplicate harvest assignments')
    for e in current.values():
        k=e['kind'];v=e['payload']['values']
        if k=='produce_adjustment':lots[v['lot_id']]['balance_kg']+=D(v['quantity_kg'])
        if k=='order_delivery':
            line=lines[v['line_id']];order=orders[line['values']['order_id']]
            if instant(v['occurred_at']).astimezone(LAGOS).date()<day(order['order_date']):raise ValueError('Delivery cannot predate the actual agreement date')
            qty=D(v['quantity_kg']);line['delivered']+=qty;line['gross_delivery']+=qty;lots[line['values']['lot_id']]['balance_kg']-=qty
        if k=='customer_return':
            delivery=deliveries[v['delivery_id']];qty=D(v['quantity_kg'])
            if instant(v['occurred_at'])<instant(delivery['occurred_at']):raise ValueError('Return cannot predate its delivery')
            returns[v['delivery_id']]+=qty;line=lines[delivery['line_id']];line['returned']+=qty;lot=lots[line['values']['lot_id']]
            if v['disposition']=='restocked':lot['balance_kg']+=qty
            else:lot['quarantined_returns_kg' if v['disposition']=='quarantined' else 'discarded_returns_kg']+=qty
        if k=='customer_payment':
            order=orders[v['order_id']]
            if instant(v['occurred_at']).astimezone(LAGOS).date()<day(order['order_date']):raise ValueError('Receipt/refund cannot predate agreement')
            order['net_receipts_ngn']+=D(v['amount_ngn'])*(-1 if v['direction']=='refund' else 1)
    for rid,qty in returns.items():
        if qty>D(deliveries[rid]['quantity_kg']):raise ValueError('Returns exceed the original delivered quantity')
    for line in lines.values():
        v=line['values'];qty=D(v['quantity_kg']);order=orders[v['order_id']];net=line['delivered']-line['returned']
        if net>qty:raise ValueError('Net deliveries exceed the ordered line quantity')
        if v['status']=='cancelled':
            if line['gross_delivery']>0:raise ValueError('Lines with delivery evidence cannot be cancelled; retain history and close remaining order tracking if needed')
            continue
        order['active_lines']+=1;order['total_ngn']+=D(money(qty*D(v['unit_ngn'])));order['ordered_kg']+=qty;order['net_delivered_kg']+=net
        if order['status']=='confirmed':lots[v['lot_id']]['reserved_kg']+=qty-net
    for lot in lots.values():
        difference=lot['balance_kg']-lot['reserved_kg']
        lot['available_kg']=max(difference,D(0));lot['commitment_shortfall_kg']=max(-difference,D(0))
        if lot['balance_kg']<0:raise ValueError('Market quantity cannot be negative; review deliveries, returns and weighing corrections')
    running={rid:D(0) for rid in orders}
    payments=sorted((e for e in current.values() if e['kind']=='customer_payment'),key=lambda e:(instant(e['payload']['values']['occurred_at']),e['id']))
    for e in payments:
        v=e['payload']['values'];running[v['order_id']]+=D(v['amount_ngn'])*(-1 if v['direction']=='refund' else 1)
        if running[v['order_id']]<0:raise ValueError('A refund cannot predate or exceed recorded receipts for this order')
    for order in orders.values():
        if order['status']=='confirmed' and not order['active_lines']:raise ValueError('Add an active order line before confirming')
        if order['status'] in ('draft','cancelled') and (order['net_delivered_kg']>0 or order['net_receipts_ngn']!=0):raise ValueError('An order with deliveries or net receipts cannot be draft/cancelled; retain evidence and close tracking instead')
        if order['net_receipts_ngn']<0 or order['net_receipts_ngn']>order['total_ngn']:raise ValueError('Net recorded receipts must stay between zero and current order value; record supported refunds/corrections separately')
        order['unreceived_ngn']=order['total_ngn']-order['net_receipts_ngn'];order['undelivered_kg']=order['ordered_kg']-order['net_delivered_kg']
        order['delivery_state']='none_recorded' if order['net_delivered_kg']==0 else 'all_current_quantity_recorded' if order['undelivered_kg']==0 else 'part_recorded'
    def formatted(rows):return [{k:format(v,'f') if isinstance(v,D) else v for k,v in row.items()} for row in rows]
    return {'produce_lots':formatted(lots.values()),'sales_orders':formatted(orders.values())}


def commitment_guard(current,kind,v,old):
    targets=set()
    if kind=='sales_order' and v['status']=='confirmed' and (old is None or old['payload']['values']['status']!='confirmed'):
        rid=next(r for r,e in current.items() if e['kind']==kind and e['payload']['values']==v) if old is None else old['record_id']
        targets={e['payload']['values']['lot_id'] for e in current.values() if e['kind']=='sales_line' and e['payload']['values']['order_id']==rid and e['payload']['values']['status']=='active'}
    if kind=='sales_line' and v['status']=='active' and current[v['order_id']]['payload']['values']['status']=='confirmed':
        prior=old['payload']['values'] if old else None
        if prior is None or prior['status']!='active' or prior['lot_id']!=v['lot_id'] or D(v['quantity_kg'])>D(prior['quantity_kg']):targets.add(v['lot_id'])
    if targets and any(D(row['commitment_shortfall_kg'])>0 for row in calculate(current)['produce_lots'] if row['record_id'] in targets):raise ValueError('This confirmation/line would overbook the market lot; revise the quantity or use supported additional produce')


def report(db,current):
    result=calculate(current);today=datetime.now(timezone.utc).astimezone(LAGOS).date().isoformat();result['offer_drafts']=[];result['enquiries']=[];result['harvest_links']=[]
    for rid,e in current.items():
        kind=e['kind'];v=e['payload']['values'];base={'record_id':rid,'field_id':e['field_id'],'source':e['payload']['source']}
        if kind=='market_offer':result['offer_drafts'].append(base|dict(name=v['name'],status=v['status'],lot_id=v['lot_id'],unit_ngn=v['unit_ngn'],validity='unknown' if v['valid_until'] is None else 'past_reported_validity' if v['valid_until']<today else 'within_reported_validity'))
        if kind=='buyer_enquiry':result['enquiries'].append(base|dict(contact_id=v['contact_id'],quantity_kg=v['quantity_kg'],status=v['status'],due_date=v['due_date']))
        if kind=='produce_lot' and v['harvest_id'] is not None:
            from nexus.farm_app.resource_logistics import external
            cap=e['payload']['captures']['harvest']
            try:status='matches_frozen_copy' if digest(external(db,'harvest',v['harvest_id']))==cap['sha256'] else 'changed_since_link'
            except ValueError:status='current_record_missing'
            result['harvest_links'].append(base|dict(harvest_id=v['harvest_id'],status=status))
    return result


def statement(store,order_id,format='html'):
    from nexus.farm_app.farm_resources import load,validate_links
    from nexus.farm_app.operations_common import readonly,positive
    positive(order_id,'order ID')
    with readonly(store.path) as db:
        _,current=load(db);validate_links(current);row=current.get(order_id)
        if row is None or row['kind']!='sales_order':raise ValueError('Sales order not found')
        summary=next(r for r in calculate(current)['sales_orders'] if r['record_id']==order_id)
        line_ids={rid for rid,e in current.items() if e['kind']=='sales_line' and e['payload']['values']['order_id']==order_id}
        deliveries={rid for rid,e in current.items() if e['kind']=='order_delivery' and e['payload']['values']['line_id'] in line_ids}
        relevant=[e for rid,e in current.items() if rid==order_id or rid in line_ids or rid in deliveries or (e['kind']=='customer_payment' and e['payload']['values']['order_id']==order_id) or (e['kind']=='customer_return' and e['payload']['values']['delivery_id'] in deliveries)]
        # Preserve only the buyer's display name, not phone/email details, in this report.
        buyer=current[row['payload']['values']['contact_id']]['payload']['values']['name']
    data={'statement_version':'market-order-statement-v1','generated_at':datetime.now(timezone.utc).isoformat(),'source':row['payload']['source'],'buyer_name_as_reported':buyer,'summary':summary,'entries':relevant,'limits':['Current saved user reports, not a frozen database snapshot or authenticated invoice.','Not a tax invoice, payment instruction or proof of delivery/payment.','Core stock and Finance records remain separate. Contact details are not copied into this statement.']}
    if format=='json':return json.dumps(data,ensure_ascii=False,indent=2).encode(),'application/json; charset=utf-8','nexus-order-statement.json'
    if format!='html':raise ValueError('Choose html or json statement')
    html='<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NEXUS order statement</title><style>body{font:16px/1.6 system-ui;max-width:950px;margin:auto;padding:24px;color:#183c2c}pre{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #ccd8ce;padding:16px 0}@media print{button{display:none}}</style></head><body><h1>NEXUS order statement</h1><p>'+text(data['source'].upper())+' · Buyer as reported: '+text(buyer)+'</p><p>Generated '+text(data['generated_at'])+'</p><h2>Current summary</h2><pre>'+text(json.dumps(summary,indent=2,ensure_ascii=False))+'</pre>'
    for e in relevant:html+='<article><h2>'+text(e['kind'])+' #'+str(e['record_id'])+' · entry #'+str(e['id'])+'</h2><pre>'+text(json.dumps(e['payload']['values'],indent=2,ensure_ascii=False))+'</pre><p>SHA-256 '+text(e['content_sha256'])+'</p></article>'
    html+='<p>NEXUS software · Built by <a href="https://yd.ydtech.workers.dev" target="_blank" rel="noopener noreferrer">Yaqini &amp; Duniya Technology</a></p><h2>Limits</h2><ul>'+''.join('<li>'+text(s)+'</li>' for s in data['limits'])+'</ul></body></html>'
    return html.encode(),'text/html; charset=utf-8','nexus-order-statement.html'


def offer_sheet(store,offer_id,format='html'):
    from nexus.farm_app.farm_resources import load,validate_links
    from nexus.farm_app.operations_common import readonly,positive
    positive(offer_id,'offer ID')
    with readonly(store.path) as db:
        _,current=load(db);validate_links(current);offer=current.get(offer_id)
        if offer is None or offer['kind']!='market_offer':raise ValueError('Offer draft not found')
        v=offer['payload']['values'];lot=current[v['lot_id']]['payload']['values'];qty=next(r for r in calculate(current)['produce_lots'] if r['record_id']==v['lot_id'])
    data={'sheet_version':'local-offer-sheet-v1','source':offer['payload']['source'],'generated_at':datetime.now(timezone.utc).isoformat(),'title':v['name'],'crop_as_reported':lot['crop'],'lot_name':lot['name'],'price_ngn_per_kg':v['unit_ngn'],'offer_status':v['status'],'lot_status':lot['status'],'reported_valid_until':v['valid_until'],'recorded_unreserved_kg':qty['available_kg'],'description':v['description'],'limits':['Local offer draft; nothing is published or sent automatically.','User-entered quality and quantity are not certified. Confirm actual availability and terms before agreement.','This dated copy is not a live reservation, payment request or guaranteed stock listing. Review free text before sharing.']}
    if format=='json':return json.dumps(data,indent=2,ensure_ascii=False).encode(),'application/json; charset=utf-8','nexus-offer-draft.json'
    if format!='html':raise ValueError('Choose html or json offer sheet')
    raw='<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NEXUS local offer draft</title><style>body{font:18px/1.6 system-ui;color:#173e2d;max-width:850px;margin:auto;padding:30px}header{background:#173e2d;color:white;padding:24px}dt{font-weight:bold;margin-top:16px}dd{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}</style></head><body><header><small>LOCAL OFFER DRAFT — '+text(data['source'].upper())+'</small><h1>'+text(v['name'])+'</h1></header><dl>'
    for k,value in data.items():
        if k in ('sheet_version','limits'):continue
        raw+='<dt>'+text(k.replace('_',' '))+'</dt><dd>'+text(value)+'</dd>'
    raw+='</dl><p>NEXUS software · Built by <a href="https://yd.ydtech.workers.dev" target="_blank" rel="noopener noreferrer">Yaqini &amp; Duniya Technology</a></p><ul>'+''.join('<li>'+text(x)+'</li>' for x in data['limits'])+'</ul></body></html>'
    return raw.encode(),'text/html; charset=utf-8','nexus-offer-draft.html'
