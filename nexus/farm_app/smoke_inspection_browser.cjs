'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright');
const config = JSON.parse(fs.readFileSync(0, 'utf8'));
const {url, observation, otherObservation}=config;

async function signIn(page, account) {
  await page.goto(url+'/');
  await page.locator('#username').fill(account);
  await page.locator('#password').fill('fixture-'+account+'-password');
  await page.locator('#login button').click();
  await page.getByText('Signed in as '+account,{exact:true}).waitFor();
}
async function open(page, farm='1', id=observation) {
  await page.goto(url+'/field-inspections');
  await page.locator('#farm').selectOption(farm);
  await page.locator('#observation').selectOption(String(id));
}
async function fill(page, reason, affected='2') {
  const time=await page.evaluate(()=>{
    const d=new Date(Date.now()-1800000);
    return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);
  });
  for (const [id,value] of Object.entries({
    performed_at:time, reporter:'DEMO owner', area:'South side',
    sampling_method:'DEMO walk', observation_definition:'Small cob',
    findings:'DEMO sample only', reason, plants_checked:'10',plants_affected:affected,
  })) await page.locator('#'+id).fill(value);
}
async function save(page, expected) {
  await page.locator('#save').click();
  await page.locator('#message').filter({hasText:expected}).waitFor();
}
async function historyCount(page, count) {
  await page.waitForFunction(n=>document.querySelectorAll('#history h3').length===n,count);
}
function mutateFixture(statement) {
  execFileSync(config.python, ['-c',
    'import sqlite3,sys; from contextlib import closing; '+
    'db=sqlite3.connect(sys.argv[1]); db.execute(sys.argv[2],(int(sys.argv[3]),)); db.commit(); db.close()',
    config.database, statement, String(config.owner)]);
}
async function checkDenied(page, path, data) {
  const status=await page.evaluate(async ({path,data})=>{
    const identity=await (await fetch('/api/workspace')).json();
    return (await fetch(path,data?{method:'POST',headers:{'Content-Type':'application/json',
      'X-Nexus-CSRF':identity.csrf},body:JSON.stringify(data)}:{})).status;
  },{path,data});
  assert.equal(status,403);
}
async function run() {
  const executablePath=process.env.NEXUS_CHROMIUM_PATH;
  const browser=await chromium.launch(executablePath
    ? {executablePath,ignoreDefaultArgs:['--no-startup-window']} : {});
  try {
    if (config.restoredHistory) {
      const mobile=await browser.newContext({viewport:{width:320,height:740},isMobile:true,
        hasTouch:true,locale:'en-GB',timezoneId:'Africa/Lagos'});
      const page=await mobile.newPage();
      await signIn(page,'owner');
      await open(page);
      await historyCount(page,2);
      const ids=config.restoredHistory.map(row=>row.id);
      assert.deepEqual(await page.locator('#history h3').allTextContents(),ids.map(id=>'Inspection #'+id));
      const summary=page.locator('#history summary').first();
      await summary.focus();
      await summary.press('Enter');
      const latest=page.locator('.inspection-card').first();
      const original=page.locator('.inspection-card').last();
      await latest.getByText('Demo correction',{exact:true}).waitFor();
      assert.match(await latest.locator('.inspection-date').innerText(),/GMT\+1|WAT/);
      assert.match(await latest.locator('.inspection-sample').innerText(),/10 plants checked · 0 met/);
      assert.match(await latest.locator('dl').last().innerText(),/2 → 0/);
      assert.match(await latest.innerText(),/Cobs checked\s+Unknown/);
      await original.locator('summary').click();
      assert.match(await original.innerText(),/Not applicable \(original entry\)/);
      assert.match(await original.innerText(),/Initial fixture/);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
      const history=await page.evaluate(async oid=>(await (await fetch(
        '/api/field-inspections?farm_id=1&observation_id='+oid)).json()).history,observation);
      assert.deepEqual(history,config.restoredHistory);
      console.log('Restored Chromium history passed at 320px: fresh sign-in, both records, keyboard expansion, local time, zero/unknown, correction comparison, exact data and no horizontal overflow.');
      return;
    }
    const owner=await browser.newContext();
    const a=await owner.newPage();
    await signIn(a,'owner'); await open(a);
    await fill(a,'Original visit');
    await save(a,'Inspection #1 saved.');
    await open(a); await historyCount(a,1);

    const b=await owner.newPage(); await open(b);
    await a.locator('#correction').selectOption('1');
    await fill(a,'Tab A unsaved correction','1');
    await b.locator('#correction').selectOption('1');
    await fill(b,'Tab B saved correction','3');
    await save(b,'Inspection #2 saved.');
    await save(a,'Inspection history changed');
    assert.equal(await a.locator('#reason').inputValue(),'Tab A unsaved correction');
    await a.locator('#refresh').click();
    await a.locator('#conflict').filter({hasText:'no longer available'}).waitFor();
    assert.equal(await a.locator('#correction').inputValue(),'1');
    assert.equal(await a.locator('#save').isDisabled(),true);
    assert.equal(await a.locator('#reason').inputValue(),'Tab A unsaved correction');
    await historyCount(a,2);
    a.once('dialog',d=>d.dismiss());
    await a.locator('#correction').selectOption('');
    assert.equal(await a.locator('#correction').inputValue(),'1');
    a.once('dialog',d=>d.accept());
    await a.locator('#correction').selectOption('2');

    // Commit successfully, but drop the response before the browser receives it.
    let delivered;
    await a.route('**/api/field-inspections',async route=>{
      delivered=route.request().postData();
      assert.equal((await route.fetch()).status(),200);
      await route.abort();
    },{times:1});
    await save(a,'Save result not confirmed');
    await a.locator('#refresh').click();
    await historyCount(a,3);
    let retryBody;
    await a.route('**/api/field-inspections',async route=>{
      retryBody=route.request().postData(); await route.continue();
    },{times:1});
    await a.locator('#retry').click();
    await a.locator('#message').filter({hasText:'Inspection #3 already saved.'}).waitFor();
    assert.equal(delivered,retryBody);
    await open(a); await historyCount(a,3);
    await a.locator('#history summary').last().click();
    assert.match(await a.locator('#history').innerText(),/Original visit/);

    // Drop a request before it reaches the server; the same retry saves it once.
    await fill(a,'Offline visit');
    await a.route('**/api/field-inspections',route=>route.abort(),{times:1});
    await save(a,'Save result not confirmed');
    await historyCount(a,3);
    await a.locator('#retry').click();
    await a.locator('#message').filter({hasText:'Inspection #4 saved.'}).waitFor();
    await historyCount(a,4);

    const viewer=await (await browser.newContext()).newPage();
    await signIn(viewer,'viewer'); await open(viewer); await historyCount(viewer,4);
    assert.equal(await viewer.locator('#save').isVisible(),false);
    await checkDenied(viewer,'/api/field-inspections',JSON.parse(delivered));
    await checkDenied(a,'/api/field-inspections?farm_id=1&observation_id='+otherObservation);
    const outsider=await (await browser.newContext()).newPage();
    await signIn(outsider,'other'); await open(outsider,'2',otherObservation);
    await historyCount(outsider,0);
    await checkDenied(outsider,'/api/field-inspections?farm_id=1');
    await checkDenied(outsider,'/api/field-inspections',JSON.parse(delivered));

    await a.locator('#correction').selectOption('3');
    await fill(a,'Keep this draft through access changes');
    mutateFixture('UPDATE nexus_sessions SET expires_at=0 WHERE account_id=?');
    await save(a,'Session expired');
    assert.equal(await a.locator('#save').isVisible(),false);
    await historyCount(a,0);
    await signIn(b,'owner'); await a.locator('#refresh').click();
    await historyCount(a,4);
    assert.equal(await a.locator('#reason').inputValue(),'Keep this draft through access changes');
    assert.equal(await a.locator('#correction').inputValue(),'3');

    mutateFixture("UPDATE nexus_farm_memberships SET role='viewer' WHERE account_id=?");
    await save(a,'Access denied');
    await a.locator('#refresh').click(); await historyCount(a,4);
    assert.equal(await a.locator('#save').isVisible(),false);
    mutateFixture('DELETE FROM nexus_farm_memberships WHERE account_id=?');
    await a.locator('#refresh').click();
    await a.locator('#message').filter({hasText:'original account or farm is unavailable'}).waitFor();
    await historyCount(a,0);
    mutateFixture("INSERT INTO nexus_farm_memberships(account_id,farm_id,role) VALUES(?,1,'owner')");
    await a.locator('#refresh').click(); await historyCount(a,4);
    assert.equal(await a.locator('#reason').inputValue(),'Keep this draft through access changes');
    assert.equal(await a.locator('#correction').inputValue(),'3');
    console.log('Browser smoke passed: sign-in, save/correct/reload, stale two-tab draft, lost response, offline retry, viewer, cross-farm, expiry, downgrade and revocation.');
  } finally { await browser.close(); }
}
run().catch(error=>{console.error(error);process.exitCode=1;});
