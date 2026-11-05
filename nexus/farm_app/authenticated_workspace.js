'use strict';
const $=id=>document.getElementById(id);
let csrf='',activeFarm='',busy=false,dirtyForms=new Set();
const writes=['field-form','observation-form','approve-form','action-form','followup-form'];
async function api(path,data){
 const r=await fetch(path,{method:data?'POST':'GET',cache:'no-store',headers:data?{'Content-Type':'application/json','X-Nexus-CSRF':csrf}:{},body:data?JSON.stringify(data):undefined});
 const value=await r.json();
 if(!r.ok){if(r.status===401)location.assign('/');throw Error(value.error||'Request failed');}
 return value;
}
function rows(id,data,label){$(id).replaceChildren(...data.map(x=>{const li=document.createElement('li');li.textContent=label(x);return li;}));}
function options(id,data,label){const previous=$(id).value;$(id).replaceChildren(new Option('Select…',''),...data.map(x=>new Option(label(x),String(x.id))));$(id).value=data.some(x=>String(x.id)===previous)?previous:'';}
function clearRecords(){for(const id of ['fields','observations','tasks','actions','followups'])$(id).replaceChildren();writes.forEach(id=>$(id).hidden=true);}
async function load(){
 clearRecords();
 const selected=$('farm').value;
 const r=await api('/api/workspace'+(selected?'?farm_id='+encodeURIComponent(selected):''));
 csrf=r.csrf;options('farm',r.farms,f=>f.name+' · '+f.role);activeFarm=$('farm').value;
 $('identity').textContent='Signed in as '+r.username;$('limits').textContent=r.limits;
 $('farm-creation').hidden=!r.can_create_farm;$('admin').hidden=!r.can_create_farm;
 rows('fields',r.fields,f=>'#'+f.id+' · '+f.name+' · '+f.crop);
 rows('observations',r.observations,o=>'#'+o.id+' · '+o.category+' · '+o.note+' · '+o.observed_at);
 rows('tasks',r.tasks,t=>'#'+t.id+' · observation #'+t.observation_id+' · '+t.status+' · '+t.priority+' · '+t.recommendation+' '+(t.explanation||''));
 rows('actions',r.actions,a=>'Task #'+a.task_id+' · '+a.action_type+' · '+a.description+' · '+a.performed_at);
 rows('followups',r.followups,f=>'Task #'+f.task_id+' · reported '+f.result+' · '+f.evidence+' · '+f.observed_at);
 options('field-id',r.fields,f=>f.name+' · '+f.crop);
 for(const [id,status] of [['pending-task','pending'],['approved-task','approved'],['completed-task','completed']])options(id,r.tasks.filter(t=>t.status===status),t=>'Task #'+t.id+' · observation #'+t.observation_id);
 writes.forEach(id=>$(id).hidden=!r.can_write);
 $('message').textContent=!r.farms.length?'No farm assigned. Ask your operator.':!selected?'Select a farm to load its records.':'Records refreshed. Sources and results are user-reported.';
}
async function run(work){if(busy)return;busy=true;const controls=[...document.querySelectorAll('input,select,textarea,button')];const previous=controls.map(c=>c.disabled);controls.forEach(c=>c.disabled=true);try{await work();}catch(e){$('message').textContent=e.message;}finally{controls.forEach((c,i)=>c.disabled=previous[i]);busy=false;}}
function time(id){return $(id).value?new Date($(id).value).toISOString():null;}
function save(id,build){$(id).onsubmit=e=>{e.preventDefault();run(async()=>{await api('/api/workspace',{...build(),farm_id:Number($('farm').value)});$(id).reset();dirtyForms.delete(id);await load();$('message').textContent='Saved. Refreshed records are displayed.';});};}
save('field-form',()=>({operation:'field',name:$('field-name').value,crop:$('field-crop').value}));
save('observation-form',()=>({operation:'observation',field_id:Number($('field-id').value),note:$('note').value,category:$('category').value,source:$('source').value,condition:$('condition').value,observed_at:time('observed-at'),soil_moisture_pct:$('moisture').value===''?null:Number($('moisture').value),moisture_method:$('method').value||null}));
save('approve-form',()=>({operation:'approve',task_id:Number($('pending-task').value),review_confirmed:$('review-confirmed').checked}));
save('action-form',()=>({operation:'action',task_id:Number($('approved-task').value),action_type:$('action-type').value,description:$('description').value,performed_at:time('performed-at')}));
save('followup-form',()=>({operation:'followup',task_id:Number($('completed-task').value),result:$('result').value,evidence:$('evidence').value,observed_at:time('followup-at')}));
save('farm-form',()=>({operation:'farm',name:$('farm-name').value,location:$('farm-location').value}));
document.querySelectorAll('form').forEach(f=>f.addEventListener('input',()=>dirtyForms.add(f.id)));
$('farm').onchange=()=>{if(dirtyForms.size&&!confirm('Discard unsaved form entries and switch farm?')){$('farm').value=activeFarm;return;}document.querySelectorAll('form').forEach(f=>f.reset());dirtyForms.clear();run(load);};
$('refresh').onclick=()=>run(load);
$('logout').onclick=()=>run(async()=>{if(dirtyForms.size&&!confirm('Sign out and discard unsaved entries?'))return;await api('/api/logout',{});dirtyForms.clear();location.assign('/');});
window.addEventListener('beforeunload',e=>{if(dirtyForms.size){e.preventDefault();e.returnValue='';}});
run(load);
