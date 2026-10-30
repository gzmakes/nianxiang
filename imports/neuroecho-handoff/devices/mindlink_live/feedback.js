// Feedback goal: hold a valid score above threshold for 10 cumulative seconds.
// No claim of attention improvement; manufacturer scores are not probabilities.
class FeedbackRound {
 constructor(){this.reset()}
 reset(){this.running=false;this.elapsed=0;this.above=0;this.streak=0;this.best=0;this.done=false;this.won=false}
 start(){this.reset();this.running=true}
 step(dt,valid,score,threshold){
  if(!valid){this.streak=0;return;}
  if(!this.running||this.done)return;
  dt=Math.min(Math.max(dt,0),.1);this.elapsed+=dt;
  if(score>=threshold){this.above+=dt;this.streak+=dt;this.best=Math.max(this.best,this.streak)}else this.streak=0;
  if(this.above>=10||this.elapsed>=60){this.done=true;this.running=false;this.won=this.above>=10}
 }
}
if(typeof module!=='undefined')module.exports={FeedbackRound};
if(typeof window!=='undefined'){
 const round=new FeedbackRound();window.feedbackRound=round;
 let current=null,received=0,lastFrame=performance.now(),ball=.12,history=[];
 const el=id=>document.getElementById(id);
 function scoreFor(s){let source=el('controlSource').value;if(!s||!s.live||s.quality!==0)return null;
  if(source==='personal')return s.personal?.valid?s.personal.value:null;
  if(source==='model')return s.model?.scores?s.model.scores[2]*100:null;
  return s.vendor?.[source]??null;
 }
 function historyPlot(s){
  let[g,w,h]=setup('scores'),l=48,r=w-20,t=12,b=h-27;
  g.fillStyle='#9badc4';g.textAlign='right';
  for(let v=0;v<=100;v+=25){let y=b-v/100*(b-t);g.strokeStyle='#293a52';g.beginPath();g.moveTo(l,y);g.lineTo(r,y);g.stroke();g.fillText(v,l-8,y+4)}
  for(const [key,col]of [['attention','#67dbcf'],['meditation','#c1a1ff']]){
   g.strokeStyle=col;g.lineWidth=2;g.beginPath();let pen=false,prev=null;
   for(const row of s.vendor_history||[]){let age=s.elapsed-row.t;if(age>120)continue;let v=row[key];
    if(v===null||v===undefined){pen=false;continue}if(prev!==null&&row.t-prev>2.2)pen=false;
    let x=r-age/120*(r-l),y=b-v/100*(b-t);if(pen)g.lineTo(x,y);else g.moveTo(x,y);pen=true;prev=row.t;
   }g.stroke();
  }
  g.textAlign='center';for(let j=0;j<5;j++)g.fillText((-120+j*30)+' s',l+(r-l)*j/4,b+20);
 }
 window.updateFeedback=function(s){current=s;received=performance.now();
  el('recordStatus').textContent=s.recording?.active?'正在录制：'+s.recording.file:s.recording?.error?'录制错误：'+s.recording.error:'未录制';
  el('personalValue').textContent=s.personal?.valid?s.personal.value.toFixed(1):s.personal?.model?'等待有效数据':'未加载';
  el('attentionValue').textContent=s.vendor?.attention??'—';el('meditationValue').textContent=s.vendor?.meditation??'—';
  let scores=s.model?.scores;
  ['rest','medium','hard'].forEach((k,i)=>{el(k+'Score').textContent=scores?(scores[i]*100).toFixed(1)+'%':'—';el(k+'Bar').style.width=scores?(scores[i]*100)+'%':'0%'});
  el('modelStatus').textContent=scores?'实时估计 · 未校准的类别得分，不是你的心理状态概率':'模型暂不输出：'+((s.model?.reasons||[]).join(' / ')||'等待数据');
  historyPlot(s);
 };
 async function post(path,body={}){let r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});let data=await r.json();if(!r.ok)throw Error(data.error||r.status);return data}
 el('recordStart').onclick=()=>post('/api/v1/recording/start').then(()=>el('recordStatus').textContent='录制已开始').catch(e=>el('recordStatus').textContent=e.message);
 el('recordStop').onclick=()=>post('/api/v1/recording/stop').then(()=>el('recordStatus').textContent='录制已停止').catch(e=>el('recordStatus').textContent=e.message);
 el('markLabel').onclick=()=>post('/api/v1/markers',{label:el('labelSelect').value}).then(()=>el('recordStatus').textContent='状态已标记').catch(e=>el('recordStatus').textContent=e.message);
 el('startGame').onclick=()=>{round.start();history=[];el('roundResult').textContent='正在进行'};
 el('stopGame').onclick=()=>{round.running=false;el('roundResult').textContent='已停止'};
 el('controlSource').onchange=()=>{round.reset();ball=.12;el('roundResult').textContent='已切换来源，请开始新一轮'};
 el('threshold').oninput=()=>{el('thresholdValue').textContent=el('threshold').value;round.reset();el('roundResult').textContent='阈值已变更，请开始新一轮'};
 el('exportGame').onclick=()=>{let u=URL.createObjectURL(new Blob([JSON.stringify({type:'feedback_game_not_attention_assessment',source:el('controlSource').value,threshold:+el('threshold').value,round,history},null,2)],{type:'application/json'})),a=document.createElement('a');a.href=u;a.download='mindlink-feedback-'+Date.now()+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)};
 let logAt=0;
 function animate(now){
  let dt=(now-lastFrame)/1000;lastFrame=now;
  let score=scoreFor(current),fresh=now-received<1500;
  if(!fresh&&!paused){el('personalValue').textContent='数据过期';el('attentionValue').textContent='—';el('meditationValue').textContent='—';['rest','medium','hard'].forEach(k=>{el(k+'Score').textContent='—';el(k+'Bar').style.width='0%'});el('modelStatus').textContent='数据过期／服务未连接，暂停估计'}
  let valid=score!==null&&fresh&&!paused&&!document.hidden;
  if(round.running&&now-logAt>=1000){history.push({at:new Date().toISOString(),score:valid?score:null,quality:current?.quality,source:el('controlSource').value});logAt=now}
  round.step(dt,valid,score,+el('threshold').value);
  if(valid)ball+=(score/100-ball)*Math.min(dt*3,1);
  el('gameScore').textContent=valid?score.toFixed(0):'—';el('progress').textContent=round.above.toFixed(1)+' / 10 秒';
  el('gameTime').textContent=Math.max(0,60-round.elapsed).toFixed(0)+' 秒';el('bestStreak').textContent=round.best.toFixed(1)+' 秒';
  el('gameStatus').textContent=paused?'显示暂停，小球暂停计分':!valid?'等待有效信号：接触不良、伪迹、数据过期时不计分':round.done?(round.won?'本轮目标达成':'本轮结束'):round.running?'保持舒适姿势，让小球进入目标区':'信号已就绪，点击开始一轮';
  if(round.done)el('roundResult').textContent=round.won?'目标达成！这表示反馈分数达到目标，不代表注意力已被验证提升。':'本轮完成，可以调整阈值再试。';
  let[g,w,h]=setup('ball'),l=45,r=w-45,t=22,b=h-30,target=b-(+el('threshold').value/100)*(b-t);
  g.fillStyle='#193e45';g.fillRect(l,t,r-l,target-t);g.strokeStyle='#58c6b8';g.setLineDash([5,5]);g.beginPath();g.moveTo(l,target);g.lineTo(r,target);g.stroke();g.setLineDash([]);g.fillStyle='#a6e9dc';g.textAlign='left';g.fillText('目标区 ≥ '+el('threshold').value,l+10,t+18);
  let x=(l+r)/2,y=b-ball*(b-t);g.beginPath();g.arc(x,y,16,0,Math.PI*2);g.fillStyle=valid?'#f4c77b':'#8190a6';g.shadowColor=valid?'#f4c77b':'transparent';g.shadowBlur=18;g.fill();g.shadowBlur=0;
  g.fillStyle='#9badc4';g.textAlign='right';g.fillText('100',l-8,t+5);g.fillText('0',l-8,b);
  requestAnimationFrame(animate);
 }
 requestAnimationFrame(animate);
}
