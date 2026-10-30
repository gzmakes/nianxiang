const assert=require('assert');const {FeedbackRound}=require('./feedback.js');let r=new FeedbackRound();r.start();
for(let i=0;i<100;i++)r.step(.1,false,90,60);assert.equal(r.elapsed,0);assert.equal(r.above,0);
for(let i=0;i<50;i++)r.step(.1,true,70,60);assert(Math.abs(r.above-5)<.001);
r.step(.1,false,70,60);assert.equal(r.streak,0);assert(Math.abs(r.above-5)<.001);
r.step(.1,true,20,60);assert.equal(r.streak,0);assert(r.best>4.9);
for(let i=0;i<51;i++)r.step(.1,true,70,60);assert(r.done&&r.won);
r.reset();r.start();r.step(60,true,80,60);assert.equal(r.above,.1);
r.reset();r.start();for(let i=0;i<601;i++)r.step(.1,true,20,60);assert(r.done&&!r.won);
console.log('Game checks passed: invalid input, cumulative goal, streak, timeout, long-frame cap');
