'use strict';
const el=id=>document.getElementById(id);
const seasonForm=el('season-form'), contextForm=el('context-form');
let state=null, activeFarm='', activeObservation='', editing=null, busy=false, dirty=false;
const controls=[...document.querySelectorAll('input,select,textarea,button')];

function node(tag,text) {
  const e=document.createElement(tag);
  e.textContent=text;
  return e;
}
function options(select, entries, blank) {
  select.replaceChildren(...(blank==null?[]:[new Option(blank,'')]),
    ...entries.map(([id,label])=>new Option(label,String(id))));
}
async function api(path,data) {
  const r=await fetch(path,{cache:'no-store',method:data?'POST':'GET',
    headers:data?{'Content-Type':'application/json','X-Nexus-CSRF':state.csrf}:{},
    body:data?JSON.stringify(data):undefined});
  const b=await r.json();
  if (!r.ok) throw Object.assign(new Error(r.status===401?'Session expired. Sign in again.':(b.error||'Request failed')),{status:r.status});
  return b;
}
function displayTime(raw) {
  const date=new Date(raw);
  return Number.isNaN(date.getTime())?String(raw):date.toLocaleString();
}
function renderContext() {
  const o=state?.observations.find(o=>String(o.id)===activeObservation);
  el('observation-note').textContent=o?o.note:'Select an observation.';
  contextForm.hidden=!o || !state?.can_write;
  const seasons=(state?.seasons??[]).filter(s=>s.field_id===o?.field_id);
  options(contextForm.elements.season,[['unknown','Unknown season'],...seasons.map(s=>[s.id,s.name])],'Choose season or Unknown');
  options(contextForm.elements.growth_stage,(state?.stages??[]).map(s=>[s,s.replaceAll('_',' ')]),null);
  const entries=(state?.history??[]).filter(h=>h.observation_id===o?.id);
  el('history').replaceChildren();
  if (o && !entries.length) el('history').append(node('p','No season context recorded.'));
  for (const h of entries) {
    const a=node('article','');
    const label=h.status==='linked'?h.season.name:h.status==='unknown'?'Unknown season':'Season context unavailable';
    a.append(node('h4',label+' · '+displayTime(h.recorded_at)));
    if (h.status!=='unavailable') {
      if (h.season) a.append(node('p','Captured planting: '+h.season.planting_date+' · Expected harvest: '+h.season.expected_harvest_date));
      a.append(node('p','Reported stage: '+h.growth_stage.replaceAll('_',' ')+' · '+h.reporter),
        node('p','Basis: '+h.basis),node('p','Reason: '+h.reason));
    }
    el('history').append(a);
  }
}
function setEdit(season) {
  editing=season;
  seasonForm.reset();
  el('season-title').textContent=season?'Edit '+season.name:'Add a season';
  if (season) {
    for (const k of ['field_id','name','variety','area_ha','planting_date','expected_harvest_date']) {
      seasonForm.elements[k].value=season[k];
    }
  }
  seasonForm.elements.field_id.disabled=busy || Boolean(editing);
}
function render() {
  el('seasons').replaceChildren();
  seasonForm.hidden=!state?.can_write;
  options(seasonForm.elements.field_id,(state?.fields??[]).map(f=>[f.id,f.name+' · '+f.crop]),'Select a field');
  options(el('observation'),(state?.observations??[]).map(o=>[o.id,'#'+o.id+' · '+o.field_name]),'Select an observation');
  el('observation').value=activeObservation;
  if (state && !state.seasons.length) el('seasons').append(node('p','No crop seasons recorded for this farm.'));
  for (const s of state?.seasons??[]) {
    const field=state.fields.find(f=>f.id===s.field_id);
    const a=node('article','');
    a.append(node('h3',s.name),node('p',field.name+' · '+s.crop+' · '+s.variety+' · '+s.area_ha+' ha'),
      node('p','Planting: '+s.planting_date+' · Expected harvest: '+s.expected_harvest_date));
    const h=state.harvests.find(h=>h.season_id===s.id);
    a.append(node('p',h?'Harvest recorded: '+h.quantity_kg+' kg · '+h.harvested_at:'No harvest recorded.'));
    const revisions=state.revisions.filter(r=>r.season_id===s.id);
    if (revisions.length) {
      const details=node('details','');
      details.append(node('summary','Season change history ('+revisions.length+')'));
      for (const r of revisions) {
        const line=record=>[record.name,record.variety,record.area_ha+' ha',record.planting_date,record.expected_harvest_date].join(' · ');
        details.append(node('p',displayTime(r.recorded_at)+'\n'+(r.before?'Before: '+line(r.before)+'\n':'Created\n')+'Saved: '+line(r.after)));
      }
      a.append(details);
    }
    if (state.can_write) {
      const button=node('button','Edit '+s.name);
      button.type='button';
      button.disabled=busy;
      button.onclick=()=>{if (!busy && discard()) {setEdit(s);seasonForm.elements.name.focus();}};
      a.append(button);
    }
    el('seasons').append(a);
  }
  renderContext();
}
function discard() {
  if (dirty && !confirm('Discard unsaved changes?')) return false;
  dirty=false;
  seasonForm.reset();
  contextForm.reset();
  setEdit(null);
  return true;
}
function clearRecords() {
  state=null;
  activeObservation='';
  editing=null;
  render();
}
async function load(farm, observation='') {
  clearRecords();
  const identity=await api('/api/workspace');
  options(el('farm'),identity.farms.map(f=>[f.id,f.name+' · '+f.role]),'Select an assigned farm');
  el('farm').value=farm;
  activeFarm=el('farm').value;
  if (farm && activeFarm!==farm) throw Error('This farm is no longer assigned to your account.');
  if (activeFarm) {
    const loaded=await api('/api/protected-seasons?farm_id='+encodeURIComponent(activeFarm));
    if (loaded.username!==identity.username || String(loaded.farm_id)!==activeFarm) throw Error('Account changed. Refresh records.');
    state=loaded;
    activeObservation=state.observations.some(o=>String(o.id)===observation)?observation:'';
  }
  render();
  el('message').textContent=state?'Records refreshed.':identity.farms.length?'Select a farm.':'No farms assigned.';
}
async function run(fn) {
  if (busy) return;
  busy=true;
  for (const c of [...controls,...el('seasons').querySelectorAll('button')]) c.disabled=true;
  try {await fn();}
  catch(error) {
    if ([401,403].includes(error.status)) clearRecords();
    el('message').textContent=error.message;
  } finally {
    busy=false;
    for (const c of [...controls,...el('seasons').querySelectorAll('button')]) c.disabled=false;
    seasonForm.elements.field_id.disabled=Boolean(editing);
  }
}
async function submit(data) {
  const saved=await api('/api/protected-seasons',data);
  dirty=false;
  seasonForm.reset();
  contextForm.reset();
  try {await load(activeFarm,activeObservation);}
  catch {el('message').textContent='Entry #'+saved.id+' saved. Refresh to see the records.';return;}
  el('message').textContent='Entry #'+saved.id+(saved.reused?' already saved.':' saved.');
}
el('farm').onchange=()=>{
  const farm=el('farm').value;
  if (discard()) run(()=>load(farm));
  else el('farm').value=activeFarm;
};
el('observation').onchange=()=>{
  if (discard()) {activeObservation=el('observation').value;renderContext();}
  else el('observation').value=activeObservation;
};
el('refresh').onclick=()=>{if(discard()) run(()=>load(activeFarm,activeObservation));};
el('new-season').onclick=()=>{if(discard()) setEdit(null);};
for (const form of [seasonForm,contextForm]) form.addEventListener('input',()=>{dirty=true;});
seasonForm.onsubmit=event=>{
  event.preventDefault();
  if (busy || !state?.can_write) return;
  const data=Object.fromEntries(new FormData(seasonForm));
  data.operation='season';
  data.farm_id=state.farm_id;
  data.field_id=editing?.field_id ?? Number(data.field_id);
  if(editing){data.id=editing.id;data.selection_hash=editing.selection_hash;}
  run(()=>submit(data));
};
contextForm.onsubmit=event=>{
  event.preventDefault();
  if (busy || !state?.can_write) return;
  const o=state.observations.find(o=>String(o.id)===activeObservation);
  if (!o) return;
  const {season,...data}=Object.fromEntries(new FormData(contextForm));
  const selected=state.seasons.find(s=>String(s.id)===season);
  if (season!=='unknown' && !selected) return;
  run(()=>submit({...data,operation:'season_context',farm_id:state.farm_id,
    observation_id:o.id,observation_hash:o.selection_hash,
    base_id:state.history.find(h=>h.observation_id===o.id)?.id??null,
    season_id:selected?.id??null,season_hash:selected?.selection_hash??null}));
};
window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
run(()=>load(''));
