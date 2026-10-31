// Existing focused UI fixtures load the new shared connection modules; no source API is stubbed here.
const fs=require('node:fs'),vm=require('node:vm');
module.exports=inputs=>{
 const ctx=vm.createContext(inputs);
 ctx.window ||= {};
 ctx.document ||= {};
 ctx.document.querySelectorAll ||= ()=>[];
 ctx.URL ||= URL;
 ctx.connectionIntro ||= {resume(){},start(){},stop(){}};
 ctx.expandTurns ||= messages=>messages;
 ctx.mobileSourceFormEpoch ??= 0;
 if(ctx.$){const find=ctx.$;ctx.$=(...args)=>{const node=find(...args);if(node?.classList&&!node.classList.toggle)node.classList.toggle=(name,on)=>on?node.classList.add(name):node.classList.remove(name);return node;};}
 vm.runInContext(fs.readFileSync('web/connection-intro.js','utf8'),ctx);
 vm.runInContext(fs.readFileSync('web/feishu-account-picker.js','utf8'),ctx);
 return ctx;
};
