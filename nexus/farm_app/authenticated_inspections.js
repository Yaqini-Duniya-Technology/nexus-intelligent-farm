'use strict';
const el=id=>document.getElementById(id);
const fields={reporter:['Reporter / role',200,'Your name and actual role; identity is user-reported.'],area:['Area inspected',500,'Describe the part inspected, for example south side.'],sampling_method:['How were plants selected?',1000,'Describe the selection method; state unknown if not recorded.'],observation_definition:['What counted as an affected plant?',1000,'State the visible criterion used, not an assumed diagnosis.'],findings:['Findings and limitations',3000,'Describe what you found and what remains uncertain.'],reason:['Entry / correction reason',1000,'Explain this new inspection or the specific correction.']};
const counts={plants_checked:'Plants checked',plants_affected:'Affected plants',cobs_checked:'Cobs checked',newly_forming_cobs:'Newly forming cobs',mature_small_cobs:'Mature cobs that remain small',uncertain_cobs:'Cobs of uncertain maturity'};
let csrf='', username='', activeFarm='', records={observations:[],history:[]};
let selected=null, draft=null, pending=null, dirty=false, busy=false, verified=false, rejected=false;
const form=el('inspection-form');
for(const [key,[label,limit,help]] of Object.entries(fields)){const l=document.createElement('label');l.textContent=label;const i=document.createElement(key==='reporter'||key==='area'?'input':'textarea');i.id=key;i.required=true;i.maxLength=limit;const small=document.createElement('small');small.textContent=help;l.append(i,small);el('text-fields').append(l);}
for(const [key,label] of Object.entries(counts)){const l=document.createElement('label');l.textContent=label;const i=document.createElement('input');Object.assign(i,{id:key,type:'number',min:'0',max:'1000000',step:'1'});l.append(i);el(key.startsWith('plants_')?'plant-fields':'cob-fields').append(l);}

async function api(path, data) {
  const response = await fetch(path, {
    method: data ? 'POST' : 'GET', cache: 'no-store',
    headers: data ? {'Content-Type':'application/json','X-Nexus-CSRF':csrf} : {},
    body: data ? JSON.stringify(data) : undefined,
  });
  const value = await response.json();
  if (!response.ok) {
    const message = response.status === 401
      ? 'Session expired. Sign in through Account and notes in another tab, then refresh records here.'
      : (value.error || 'Request failed');
    throw Object.assign(new Error(message), {status:response.status});
  }
  return value;
}

function options(id, items, label, blank, wanted) {
  const input=el(id);
  input.replaceChildren(new Option(blank,''), ...items.map(x=>new Option(label(x),String(x.id))));
  if (items.some(x=>String(x.id)===wanted)) input.value=wanted;
}

function currentRows() { return records.history.filter(r=>r.observation_id===selected?.id); }
function targets() {
  const rows=currentRows();
  const superseded=new Set(rows.map(row=>row.supersedes_id));
  return rows.filter(row=>!superseded.has(row.id));
}
function capture(targetId) {
  if (!verified || !records.can_write || !selected) return null;
  const target=targetId===null ? null : targets().find(row=>row.id===targetId);
  if (targetId!==null && !target) return null;
  return {
    username, farm_id:Number(activeFarm), observation_id:selected.id,
    observation_hash:selected.selection_hash, base_id:currentRows()[0]?.id ?? null,
    intent:target ? 'correct' : 'new', supersedes_id:target?.id ?? null,
    target_revision:target?.content_sha256 ?? null,
  };
}
function sameScope() {
  return draft && username===draft.username && Number(activeFarm)===draft.farm_id
    && selected?.id===draft.observation_id;
}
function conflict() {
  if (!draft) return false;
  const now=capture(draft.supersedes_id);
  return rejected || !now || Object.keys(draft).some(key=>draft[key]!==now[key]);
}

function render() {
  const permitted=verified && records.can_write && selected && (!draft || sameScope());
  form.hidden=!permitted;
  el('permission').textContent=permitted ? 'Owner/editor: may save actual inspections.'
    : 'Read only, or no permitted observation selected.';
  el('draft-held').hidden=!(draft && (dirty || pending) && !permitted);
  el('note').textContent=selected ? 'Field: '+selected.field_name+' · '+selected.note
    : 'Select a saved observation to open its history.';

  const target=draft?.supersedes_id;
  options('correction',targets(),r=>'Correct inspection #'+r.id,'New inspection',String(target));
  if (target!=null && !targets().some(row=>row.id===target)) {
    const unavailable=new Option('Correction #'+target+' — no longer available',String(target));
    unavailable.disabled=true;
    el('correction').add(unavailable);
    el('correction').value=String(target);
  }
  const blocked=Boolean(permitted && conflict());
  el('conflict').hidden=!blocked;
  el('conflict').textContent=draft?.intent==='correct'
    ? 'The inspection you were correcting has changed or is no longer available. Your draft is preserved. Review the latest inspection below before saving.'
    : 'The observation or its history has changed. Your draft is preserved. Review the latest records before saving.';
  el('review').hidden=!(blocked && !pending && !rejected && capture(target));
  el('retry').hidden=!(permitted && pending);
  el('pending-save').hidden=!(permitted && pending);
  el('save').disabled=busy || !permitted || blocked || Boolean(pending);
  el('correction').disabled=busy || rejected || Boolean(pending);
  for (const key of ['performed_at',...Object.keys(fields),...Object.keys(counts)]) {
    el(key).disabled=busy || Boolean(pending);
  }
  for (const id of ['refresh','review','retry','farm','observation']) el(id).disabled=busy;
  el('history').replaceChildren();
  const rows=currentRows();
  const corrected=new Set(rows.map(r=>r.supersedes_id));
  if (!rows.length) {
    const p=document.createElement('p');
    p.textContent='No inspections for this observation.';
    el('history').append(p);
  }
  for (const row of rows) {
    const section=document.createElement('section'), h=document.createElement('h3'), p=document.createElement('pre');
    h.textContent='Inspection #'+row.id+(corrected.has(row.id)?' — earlier corrected entry':'');
    p.textContent='Recorded: '+new Date(row.recorded_at).toLocaleString()+'\n'
      +Object.entries(row.payload).filter(([k])=>k!=='observation_at_capture')
        .map(([k,v])=>k.replaceAll('_',' ')+': '+(v??'Unknown')).join('\n');
    section.append(h,p);
    el('history').append(section);
  }
}

function clearAccess() {
  verified=false;
  csrf='';
  records={observations:[],history:[]};
  selected=null;
  el('identity').textContent='';
  options('observation',[],'','Select an observation','');
}
async function load() {
  const farm=draft ? String(draft.farm_id) : el('farm').value;
  const observation=draft ? String(draft.observation_id) : el('observation').value;
  clearAccess();
  const identity=await api('/api/workspace');
  username=identity.username;
  el('identity').textContent='Signed in as '+username;
  options('farm',identity.farms,f=>f.name+' · '+f.role,'Select a farm',farm);
  activeFarm=el('farm').value;
  if (draft && (username!==draft.username || activeFarm!==farm)) {
    throw Error('The draft’s original account or farm is unavailable. It is hidden and cannot be saved.');
  }
  if (activeFarm) {
    const loaded=await api('/api/field-inspections?farm_id='+encodeURIComponent(activeFarm));
    if (loaded.username!==username || String(loaded.farm_id)!==activeFarm) {
      throw Error('The account or farm changed while loading. Refresh records before continuing.');
    }
    records=loaded;
  }
  csrf=records.csrf||identity.csrf;
  options('observation',records.observations,o=>'#'+o.id+' · '+o.field_name,'Select an observation',observation);
  selected=records.observations.find(o=>String(o.id)===el('observation').value)||null;
  verified=true;
  rejected=false;
  el('message').textContent=identity.farms.length
    ? 'Records refreshed. Counts describe the inspected sample only.' : 'No farm assigned. Contact your operator.';
}
async function run(work) {
  if (busy) return;
  busy=true;
  render();
  try { await work(); }
  catch (error) { el('message').textContent=error.message; }
  finally { busy=false; render(); }
}
function discard() {
  if ((dirty || pending) && !confirm(pending
    ? 'The previous save may already exist. Discard this tab’s retry and change selection? Check the original history before entering it again.'
    : 'Discard the unsaved inspection and change selection?')) return false;
  dirty=false;
  pending=null;
  draft=null;
  rejected=false;
  form.reset();
  return true;
}
form.addEventListener('input',event=>{
  if (event.target===el('correction')) return;
  if (!draft) draft=capture(null);
  dirty=true;
});
el('farm').onchange=()=>{
  const farm=el('farm').value;
  if (!discard()) { el('farm').value=activeFarm; return; }
  clearAccess();
  el('farm').value=farm;
  run(load);
};
el('observation').onchange=()=>{
  const id=el('observation').value;
  if (!discard()) { el('observation').value=selected ? String(selected.id) : ''; return; }
  selected=records.observations.find(o=>String(o.id)===id)||null;
  render();
};
el('correction').onchange=()=>{
  const target=el('correction').value ? Number(el('correction').value) : null;
  const next=capture(target);
  if (!next || pending) { render(); return; }
  if (draft && (dirty || conflict()) && !confirm(target===null
    ? 'Keep this text and explicitly start a separate new inspection? Use this only for an actual separate visit.'
    : 'Use this draft to correct inspection #'+target+'? Confirm you have reviewed that entry below.')) {
    render(); return;
  }
  draft=next;
  rejected=false;
  render();
};
el('review').onclick=()=>{
  const next=capture(draft?.supersedes_id ?? null);
  if (next && !pending && !rejected && confirm('I have reviewed the refreshed observation and inspection history. Keep my draft for this action?')) {
    draft=next;
    rejected=false;
    render();
  }
};
el('refresh').onclick=()=>run(load);

async function sendPending(retry=false) {
  if (!verified || !records.can_write || !sameScope() || !pending) {
    throw Error('Refresh records with the original account and farm before saving.');
  }
  let saved;
  try {
    saved=await api('/api/field-inspections',pending);
    if (!Number.isInteger(saved?.id) || saved.id<1) throw Error('Unexpected save response');
  } catch (error) {
    if (error.status===409) rejected=true;
    if (error.status===401 || error.status===403) clearAccess();
    if (error.status===409 || (!retry && error.status>=400 && error.status<500)) {
      pending=null;
      throw error;
    }
    throw Error((error.status===401 || error.status===403 ? error.message+' ' : '')
      +'Save result not confirmed. Your original request is held in this tab. Retry the same save before editing.');
  }
  pending=null;
  draft=null;
  dirty=false;
  rejected=false;
  form.reset();
  try { await load(); }
  catch { el('message').textContent='Inspection #'+saved.id+' saved. Refresh to see the history.'; return; }
  el('message').textContent='Inspection #'+saved.id+(saved.reused?' already saved.':' saved.')
    +' Task and decision actions unchanged.';
}
el('retry').onclick=()=>run(()=>sendPending(true));
form.onsubmit=event=>{
  event.preventDefault();
  run(async()=>{
    if (pending) throw Error('Retry the previous save first.');
    if (!draft) draft=capture(null);
    if (!draft || conflict()) throw Error('Refresh and review the inspection history before saving.');
    const {username: _account, ...data}=draft;
    data.submission_id=crypto.randomUUID();
    data.performed_at=new Date(el('performed_at').value).toISOString();
    for (const key of Object.keys(fields)) data[key]=el(key).value;
    for (const key of Object.keys(counts)) data[key]=el(key).value==='' ? null : Number(el(key).value);
    pending=data;
    await sendPending();
  });
};
window.addEventListener('beforeunload',e=>{
  if (dirty || pending) { e.preventDefault(); e.returnValue=''; }
});
run(load);
