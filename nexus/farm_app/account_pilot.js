'use strict';
const $=id=>document.getElementById(id);
let csrf='', generation=0, activeFarm='';
async function request(path,data){
  const response=await fetch(path,{method:data?'POST':'GET',headers:data?{'Content-Type':'application/json','X-Nexus-CSRF':csrf}:{},body:data?JSON.stringify(data):undefined,cache:'no-store'});
  const result=await response.json();
  if(!response.ok){if(response.status===401){$('workspace').hidden=true;$('sign-in').hidden=false;csrf='';}throw Error(result.error||'Request failed');}
  return result;
}
function list(id,items,label){$(id).replaceChildren(...items.map(item=>{const li=document.createElement('li');li.textContent=label(item);return li;}));}
async function load(){
  const mine=++generation, previous=$('farm').value;
  const data=await request('/api/session'+(previous?'?farm_id='+encodeURIComponent(previous):''));
  if(mine!==generation)return;
  csrf=data.csrf;$('sign-in').hidden=true;$('workspace').hidden=false;$('identity').textContent='Signed in as '+data.username;
  $('farm').replaceChildren(new Option('Select a farm',''),...data.farms.map(f=>new Option(f.name+' · '+f.role,String(f.id))));
  $('farm').value=data.farms.some(f=>String(f.id)===previous)?previous:'';activeFarm=$('farm').value;
  list('fields',data.fields,f=>f.name+' · '+f.crop);
  list('observations',data.observations,o=>'#'+o.id+' · '+o.note);
  list('notes',data.notes,n=>'#'+n.id+' · '+n.note+' · '+n.created_at);
  const farm=data.farms.find(f=>String(f.id)===$('farm').value);
  $('note-form').hidden=!farm||farm.role==='viewer';
  $('message').textContent='Records refreshed. Notes are separate from observations and tasks.';
}
async function action(button,work){const controls=[...document.querySelectorAll('button,input,select,textarea')];const states=controls.map(c=>c.disabled);controls.forEach(c=>c.disabled=true);try{await work();}catch(error){$('message').textContent=error.message;}finally{controls.forEach((c,i)=>c.disabled=states[i]);}}
$('login').onsubmit=e=>{e.preventDefault();action(e.submitter,async()=>{try{const result=await request('/api/login',{username:$('username').value,password:$('password').value});csrf=result.csrf;}finally{$('password').value='';}await load();});};
$('farm').onchange=()=>{if($('note').value&&!confirm('Discard this unsaved note?')){$('farm').value=activeFarm;return;}$('note').value='';$('note-form').hidden=true;action($('refresh'),load);};
$('refresh').onclick=e=>action(e.target,load);
$('logout').onclick=e=>action(e.target,async()=>{if($('note').value&&!confirm('Sign out and discard the unsaved note?'))return;++generation;await request('/api/logout',{});csrf='';$('note').value='';$('workspace').hidden=true;$('sign-in').hidden=false;$('message').textContent='Signed out.';});
$('note-form').onsubmit=e=>{e.preventDefault();const farm_id=Number($('farm').value);action(e.submitter,async()=>{await request('/api/note',{farm_id,note:$('note').value});$('note').value='';await load();});};
window.addEventListener('beforeunload',e=>{if($('note').value){e.preventDefault();e.returnValue='';}});
load().catch(e=>$('message').textContent=e.message);
