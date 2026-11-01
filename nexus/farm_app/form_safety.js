/* Pure helpers and a scoped form lock. No persistence, requests or farm writes. */
(function(root){'use strict';
function preserveChoice(previous,ids){return ids.map(String).includes(String(previous))?String(previous):'';}
function lockControls(controls){const states=[...controls].map(control=>[control,control.disabled]);states.forEach(([control])=>control.disabled=true);let restored=false;return function(){if(restored)return;restored=true;states.forEach(([control,disabled])=>control.disabled=disabled);};}
function latestGate(){let generation=0;return {next(){return ++generation;},current(token){return token===generation;}};}
const api=Object.freeze({preserveChoice,lockControls,latestGate});if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.NexusFormSafety=api;
})(typeof window==='undefined'?globalThis:window);
