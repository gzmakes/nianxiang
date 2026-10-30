const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const contract=require('../web/contact-contract');
test('Web/H5 and desktop run byte-identical contact guards',()=>{assert.equal(fs.readFileSync('web/contact-contract.js','utf8'),fs.readFileSync('desktop/contact-contract.js','utf8'));});
test('capability gate requires all three independently meaningful flags',()=>{for(const missing of ['companion_boundaries','bounded_followup_contact','unified_contact_claim']){const features={companion_boundaries:true,bounded_followup_contact:true,unified_contact_claim:true};delete features[missing];assert.equal(contract.supported({features}),false);}assert.equal(contract.supported({features:{}}),false);});
test('exact target, occurrence, channel and bounded lease are mandatory before presentation',()=>{
 const now=Date.now(),item={id:'f',due_at:new Date(now-1).toISOString(),contact_expires_at:new Date(now+1800000).toISOString()};
 const claim={claimed:true,claim_id:'c',followup_id:'f',occurrence_at:item.due_at,channel:'in_app',expires_at:new Date(now+60000).toISOString()};
 assert.equal(contract.claimMatches(claim,item,'in_app',now),true);
 for(const patch of [{claimed:'true'},{followup_id:'other'},{occurrence_at:'bad'},{channel:'system'},{expires_at:new Date(now).toISOString()}])assert.equal(contract.claimMatches({...claim,...patch},item,'in_app',now),false);
 assert.equal(contract.recheckMatches({...claim,allowed:true},claim,item,'in_app',now),true);assert.equal(contract.recheckMatches({...claim,allowed:true,claim_id:'other'},claim,item,'in_app',now),false);
});
