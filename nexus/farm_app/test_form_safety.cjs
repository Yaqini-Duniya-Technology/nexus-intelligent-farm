'use strict';
const assert=require('node:assert/strict');const api=require('./form_safety.js');
assert.equal(api.preserveChoice('4',[1,4,8]),'4');
assert.equal(api.preserveChoice('4',[1,8]),'');
assert.equal(api.preserveChoice('',[]),'');
const enabled={disabled:false},alreadyDisabled={disabled:true};const unlock=api.lockControls([enabled,alreadyDisabled]);
assert.equal(enabled.disabled,true);assert.equal(alreadyDisabled.disabled,true);unlock();assert.equal(enabled.disabled,false);assert.equal(alreadyDisabled.disabled,true);unlock();assert.equal(enabled.disabled,false);
const gate=api.latestGate(),first=gate.next(),second=gate.next();assert.equal(gate.current(first),false);assert.equal(gate.current(second),true);
console.log('Form safety helpers passed: choice preservation, idempotent lock restoration and stale-response gate.');
