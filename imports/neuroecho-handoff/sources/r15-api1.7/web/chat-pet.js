/* Browser port of dsh-pet's interaction ideas (MIT). The locally installed
 * non-commercial animation files are served separately and are not bundled. */
(() => {
  'use strict';
  const INVENTORY = {"random:玩耍":["三球抛接","下五子棋","优雅女仆舞","凭空生花","动物环绕","原地专心玩魔方","原地跳跃抓碎头顶物品","原地蹲下玩玩具汽车","变鸽子","可爱宅舞","吹气球","吹笛子","小提琴演奏","扑克魔术","抽陀螺","拆礼物","撸猫","放风筝","玩水枪","玩游戏气急败坏","荡秋千","蓝鲸现世","蝴蝶蜜蜂环绕头顶开花","踢毽子","轻快摇摆舞","骑木马","鲸鱼吐泡泡特效"],"turn":["东张西望"],"random:时节":["中秋赏月吃月饼","写福字","吃年糕","吃汤圆","吃粽子","吃腊八粥","吃重阳糕","吃青团","吃饺子","堆雪人","插茱萸赏菊","收红包","放孔明灯","放河灯","放烟花","穿针乞巧","舞狮头","萌化小幽灵","被落叶淹没","装点圣诞树","讨糖南瓜灯"],"event:balance":["余额-分文不剩","余额-数金皱眉","余额-袋空如洗","余额-金袋叮当","余额-钱袋如常","余额-钱袋满溢"],"random:小动作":["偷吃零食被抓住","写代码","原地小憩沉眠","原地敲击桌面互动","原地重力下蹲压缩","哈欠连天","女仆屈膝礼仪","小幅度原地360度旋转展示","悠闲哼歌","打瞌睡被惊醒","摇扇纳凉","整体换装试色","晨间刷牙","照镜子","用鲸鱼尾巴拍打地面","被吓一跳","超大伸懒腰","轻快记录"],"move":["原地左转奔跑","原地漂浮踏步","螃蟹走路"],"random:吃什么":["吃Token","吃冰淇淋融化","吃午餐","吃大闸蟹","吃早餐","吃晚餐","吃白饭","吃糖葫芦","吃西瓜","吃长寿面","大口吃零食","涮火锅"],"event:workStatus":["工作状态-原地踱步张望","工作状态-垂头叹气冒汗","工作状态-忙碌点按","工作状态-思考冒泡","工作状态-清点归档","工作状态-雀跃庆祝"],"idle":["待机呼吸休闲"],"random:文字":["是啊，吃什么","深度思考碎碎念"],"click":["点击回应-傲娇生气","点击回应-元气挥手","点击回应-害羞惊讶","点击回应-开心跃动","点击回应-挠痒咯咯笑"],"event:whisper":["碎碎念-发呆碎碎念","碎碎念-对屏碎碎念","碎碎念-擦桌碎碎念"],"drag":["被鼠标拖拽悬空反馈"]};
  const weights = {'小动作':20, '玩耍':20, '吃什么':16, '时节':14, '文字':10};
  const states = ['thinking','working','result','waiting','success','error'];
  const work = ['工作状态-思考冒泡','工作状态-忙碌点按','工作状态-清点归档','工作状态-原地踱步张望','工作状态-雀跃庆祝','工作状态-垂头叹气冒汗'];
  const workTexts = ['让我整理一下思路～','正在处理这一步。','这一步处理好啦，继续看看。','这里需要你确认一下。'];
  const texts = ['我在认真想哦。','给我一点点时间～','你说，我在听。','今天也一起加油吧！','摸摸鱼，再继续～','有灵感记得告诉我！','我在这里陪你。','让我偷偷伸个懒腰。'];
  const pick = (pool, previous) => {
    const options = pool.filter(x => x !== previous);
    const values = options.length ? options : pool;
    return values[Math.floor(Math.random() * values.length)];
  };
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(v, Math.max(lo, hi)));
  const root = document.createElement('div');
  root.className = 'chat-pet-root';
  root.innerHTML = `<div class="chat-pet-stage" aria-hidden="true"><video class="chat-pet-video" muted playsinline preload="auto"></video><video class="chat-pet-video" muted playsinline preload="auto"></video></div><button type="button" class="chat-pet-hit" aria-label="大肥鱼，点击互动；右键或长按打开菜单" aria-haspopup="menu" aria-expanded="false"></button><div class="chat-pet-bubble" role="status" aria-live="polite" hidden></div>`;
  const menu = document.createElement('div');
  menu.className = 'chat-pet-menu'; menu.hidden = true; menu.setAttribute('role','presentation');
  const tooltip=document.createElement('div');tooltip.className='chat-pet-tooltip';tooltip.hidden=true;
  tooltip.textContent='大肥鱼';tooltip.setAttribute('aria-hidden','true');
  const scoreCard=document.createElement('div');scoreCard.className='chat-pet-score';scoreCard.hidden=true;
  scoreCard.setAttribute('role','status');scoreCard.setAttribute('aria-live','polite');
  const scoreValue=document.createElement('div'),scoreDetail=document.createElement('div');
  scoreValue.className='chat-pet-score-value';scoreDetail.className='chat-pet-score-detail';scoreCard.append(scoreValue,scoreDetail);
  const restore=document.createElement('button');restore.type='button';restore.className='chat-pet-restore';
  restore.textContent='召回大肥鱼';restore.hidden=true;restore.setAttribute('aria-label','召回大肥鱼');
  document.body.append(root,menu,tooltip,scoreCard,restore);
  const videos = [...root.querySelectorAll('video')];
  const hit = root.querySelector('.chat-pet-hit');
  const bubble = root.querySelector('.chat-pet-bubble');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const reduceMotion = () => reduced.matches || document.documentElement.dataset.reduceMotion==='true';
  const runtime = {name:'', kind:'', slot:-1, facing:'left', paused:false, fixed:false, work:null, balance:null, locked:false, priority:0, movement:null, drag:null, x:0, y:0, vx:0, vy:0};
  let media = new Map(), memes=[], bubbleTimer=0, longTimer=0, motionRAF=0, physicsRAF=0, suppressClick=false, request=0, justThinking=false, previousDown=-1000, scoreClick=false;
  let userMoved=false, placementTimer=0, workTimer=0, scoreTimer=0, hiddenByUser=false, whisperGeneration=0;
  let conversationSeq=0, conversationRequest=null, pendingReply=null;
  const slotOwner=[0,0], slotPauseTimer=[0,0];
  let pending=false, activeEnded=false, consecutiveFailures=0;
  let menuDeferred=false, longPressPointerId=null, longPressClickPending=false, longPressGeneration=0, longPressClearTimer=0;
  const size = () => root.offsetWidth;
  const height = () => root.offsetHeight;
  const limits = () => {
    const minY=-height()*50/360+8;
    let maxY=innerHeight-height()*330/360-8;
    // Keep the interactive body above the mobile composer and any visible
    // attachment preview, including after a throw or keyboard resize.
    const composer=document.querySelector('#m-composer')?.getBoundingClientRect();
    if(composer && composer.width>0 && composer.height>0){
      const preview=document.querySelector('#m-image-preview')?.getBoundingClientRect();
      const safeTop=preview && preview.width>0 && preview.height>0 ? Math.min(composer.top,preview.top) : composer.top;
      maxY=Math.min(maxY,safeTop-height()*335/360-8);
    }
    return {minX:-size()*200/640+8,maxX:innerWidth-size()*440/640-8,minY,maxY:Math.max(minY,maxY)};
  };
  const paint = () => {root.style.transform=`translate3d(${runtime.x}px,${runtime.y}px,0)`;root.classList.toggle('is-right',runtime.facing==='right');fitBubble();};
  const bound = () => {const l=limits();runtime.x=clamp(runtime.x,l.minX,l.maxX);runtime.y=clamp(runtime.y,l.minY,l.maxY);};
  // Hover/score overlays are anchored in viewport coordinates and never
  // capture pointer events, so text entry and page controls remain usable.
  const hideTooltip = () => {tooltip.hidden=true;};
  const showTooltip = event => {
    if(event.pointerType==='touch' || runtime.drag || !menu.hidden)return hideTooltip();
    tooltip.hidden=false;
    const gap=size()*.022,w=tooltip.offsetWidth,h=tooltip.offsetHeight;
    let x=event.clientX+gap,y=event.clientY+gap;
    if(x+w>innerWidth-4)x=event.clientX-gap-w;
    if(y+h>innerHeight-4)y=event.clientY-gap-h;
    tooltip.style.left=clamp(x,4,innerWidth-w-4)+'px';
    tooltip.style.top=clamp(y,4,innerHeight-h-4)+'px';
  };
  const spawnScoreBurst = (x,y) => {
    if(reduceMotion())return;
    const layer=document.createElement('div');layer.className='chat-pet-burst';layer.setAttribute('aria-hidden','true');document.body.append(layer);
    const colors=['#ffb300','#ff8f00','#ff7043','#f4511e','#ffc400','#ffd54f','#ef5350'];
    const born=performance.now(),particles=[];
    for(let i=0;i<20;i++){
      const angle=Math.random()*Math.PI*2,speed=120+Math.random()*340,radius=3+Math.random()*4;
      const dot=document.createElement('div');dot.className='chat-pet-particle';
      dot.style.left=x+'px';dot.style.top=y+'px';dot.style.width=dot.style.height=radius*2+'px';
      dot.style.background=colors[Math.floor(Math.random()*colors.length)];layer.append(dot);
      particles.push({dot,vx:Math.cos(angle)*speed,vy:Math.sin(angle)*speed-80,life:500+Math.random()*400});
    }
    const step=now=>{
      if(reduceMotion()){layer.remove();return;}
      let alive=false;const elapsed=now-born;
      for(const p of particles){
        const progress=elapsed/p.life;if(progress>=1){p.dot.style.opacity='0';continue;}
        alive=true;const seconds=elapsed/1000;
        p.dot.style.transform=`translate(${p.vx*seconds}px,${p.vy*seconds+350*seconds*seconds}px)`;
        p.dot.style.opacity=String(Math.max(0,1-progress));
      }
      if(alive)requestAnimationFrame(step);else layer.remove();
    };
    requestAnimationFrame(step);
  };
  const showScore = (x,y,speed) => {
    const score=Math.max(1,Math.round(speed/100*462/size()));
    scoreValue.textContent=`+${score}`;scoreDetail.textContent=`速度 ${Math.round(speed)} · 大小 ${Math.round(size())}`;
    scoreCard.hidden=false;const w=scoreCard.offsetWidth,h=scoreCard.offsetHeight;
    scoreCard.style.left=clamp(x-w/2,4,innerWidth-w-4)+'px';
    scoreCard.style.top=clamp(y-h-14,4,innerHeight-h-4)+'px';
    scoreCard.classList.remove('is-in');void scoreCard.offsetWidth;scoreCard.classList.add('is-in');
    clearTimeout(scoreTimer);scoreTimer=setTimeout(()=>{scoreCard.hidden=true;},2200);
    spawnScoreBurst(x,y);
  };
  const home = () => {
    const composer = document.querySelector('#composer, #m-composer, [data-chat-pet-anchor]');
    const r = composer?.getBoundingClientRect();
    if(r && r.width){
      const bodyWidth=size()*240/640;
      const sidebar=document.querySelector('#design-context')?.getBoundingClientRect();
      const petTop=r.top-height()*280/360-8;
      const sidebarVisible=sidebar && sidebar.width>0 && sidebar.height>0 && sidebar.left>=r.left && sidebar.left<innerWidth && sidebar.bottom>petTop && sidebar.top<r.top;
      const rightBoundary=sidebarVisible?Math.min(innerWidth-8,sidebar.left-8):innerWidth-8;
      // Prefer the empty space just outside the composer's right edge. When a
      // sidebar or narrow viewport leaves insufficient space, place the body
      // above its right end without covering either the input or the sidebar.
      const bodyLeft=r.right+16+bodyWidth<=rightBoundary ? r.right+16 : Math.min(rightBoundary-bodyWidth,r.right-bodyWidth);
      runtime.x=bodyLeft-size()*200/640;
    }else runtime.x=innerWidth-size()*.75;
    runtime.y = r && r.height ? r.top-height()*330/360-8 : innerHeight-height()-110;
    bound();paint();return !!(r && r.width && r.height);
  };
  const fitBubble = () => {
    if(bubble.hidden)return;
    bubble.style.marginLeft='0px';bubble.classList.toggle('is-below',runtime.y<20);
    const r=bubble.getBoundingClientRect();bubble.style.marginLeft=(Math.max(0,8-r.left)-Math.max(0,r.right-innerWidth+8))+'px';
  };
  const say = (text, priority=2, meme=null, duration=10000) => {
    whisperGeneration++;
    if(!bubble.hidden && priority<runtime.priority)return false;
    runtime.priority=priority;bubble.replaceChildren();bubble.textContent=String(text);
    if(meme){
      const image=document.createElement('img');image.className='chat-pet-bubble-image';
      image.alt=`大肥鱼表情：${meme.name}`;image.referrerPolicy='no-referrer';image.loading='eager';
      image.addEventListener('load',fitBubble);image.addEventListener('error',()=>{image.remove();fitBubble();});
      image.src=meme.url;bubble.append(image);
    }
    bubble.hidden=false;fitBubble();
    clearTimeout(bubbleTimer);bubbleTimer=0;
    if(duration!==null)bubbleTimer=setTimeout(()=>{
      whisperGeneration++;
      bubble.hidden=true;runtime.priority=0;
      if(pendingReply){const reply=pendingReply;pendingReply=null;if(currentReply(reply.isCurrent))deliverReply(reply.text);}
      if(bubble.hidden)showWorkBubble();
    },duration);
    return true;
  };
  const showWorkBubble = () => {
    const index=states.indexOf(runtime.work);
    if(index>=0 && index<4 && !runtime.paused && !runtime.locked && !runtime.drag && !hiddenByUser)
      say(workTexts[index],0,null,null);
  };
  const deliverReply = text => {
    if(!say(text,2))return false;
    if(!runtime.paused&&!runtime.locked&&!runtime.drag&&!runtime.work)
      void play(pick(INVENTORY['event:whisper'],runtime.name),'event');
    return true;
  };
  const currentReply = guard => {
    if(typeof guard!=='function')return true;
    try{return !!guard();}catch(_){return false;}
  };
  const showReply = (text,requestId,isCurrent) => {
    if(conversationRequest===null || requestId!==conversationRequest || typeof text!=='string' || !text.trim())return false;
    if(!currentReply(isCurrent)){conversationRequest=null;return false;}
    const chars=Array.from(text.trim()), message=chars.length>120?chars.slice(0,120).join('')+'…':chars.join('');
    conversationRequest=null;
    if(!deliverReply(message))pendingReply={text:message,requestId,isCurrent};
    return true;
  };
  const cancelConversation = requestId => {
    let cancelled=false;
    if(requestId===undefined || requestId===conversationRequest){cancelled=conversationRequest!==null;conversationRequest=null;}
    if(pendingReply && (requestId===undefined || requestId===pendingReply.requestId)){pendingReply=null;cancelled=true;}
    return cancelled;
  };
  const requestConversation = () => {
    const requestId=++conversationSeq;conversationRequest=requestId;pendingReply=null;
    closeMenu();document.querySelector('#input, #m-input')?.focus();say('想聊什么？我在听。',2);
    document.dispatchEvent(new CustomEvent('xinji-pet-chat-request',{detail:{requestId}}));
  };
  const squash = (strong=false) => {
    if(reduceMotion())return;
    root.classList.remove('is-squash','is-squash-strong');void root.offsetWidth;root.classList.add(strong?'is-squash-strong':'is-squash');
    setTimeout(()=>root.classList.remove('is-squash','is-squash-strong'),260);
  };
  const balanceClips=['余额-钱袋满溢','余额-金袋叮当','余额-钱袋如常','余额-数金皱眉','余额-袋空如洗','余额-分文不剩'];
  const showBalance = (percent, explicit=false) => {
    const tier=percent===100?5:Math.floor(percent/20);
    play(balanceClips[tier],'event',explicit);
    say(`额度已使用 ${percent}%`,1);
  };
  const stopMove = () => {cancelAnimationFrame(motionRAF);motionRAF=0;runtime.movement=null;};
  const stopPhysics = () => {cancelAnimationFrame(physicsRAF);physicsRAF=0;runtime.vx=runtime.vy=0;};
  const resume = () => {
    if(runtime.paused || runtime.locked || hiddenByUser)return;
    if(reduceMotion()){const index=states.indexOf(runtime.work);play(index>=0?work[index]:INVENTORY.idle[0],'still');return;}
    if(runtime.work && states.indexOf(runtime.work)>=0){play(work[states.indexOf(runtime.work)],'work');return;}
    play(pick(INVENTORY.idle,runtime.name),'idle');
  };
  const next = () => {
    if(runtime.paused || runtime.locked || runtime.drag || hiddenByUser)return;
    if(reduceMotion()){resume();return;}
    const roll=Math.random();
    if(roll<.10)return play(pick(INVENTORY.idle,runtime.name),'idle');
    if(!runtime.fixed && roll<.15)return play(pick(INVENTORY.turn,runtime.name),'turn');
    if(!runtime.fixed && roll<.20)return startMove(pick(INVENTORY.move,runtime.name));
    const cats=Object.keys(weights).filter(c=>!(c==='文字' && runtime.facing==='right'));
    let n=Math.random()*cats.reduce((sum,c)=>sum+weights[c],0),cat=cats[cats.length-1];
    for(const c of cats){n-=weights[c];if(n<=0){cat=c;break;}}
    play(pick(INVENTORY['random:'+cat],runtime.name),'action');
  };
  const play = async (name, kind='action', explicit=false) => {
    whisperGeneration++;
    const url=media.get(name);
    if(!url){
      say('动作素材暂不可用。',1);
      if(!pending && (activeEnded || runtime.slot<0) && ++consecutiveFailures<3){
        const fallback=INVENTORY.idle.find(item=>item!==name && media.has(item)) || Object.values(INVENTORY).flat().find(item=>item!==name && media.has(item));
        if(fallback)void play(fallback,fallback===INVENTORY.idle[0]?'idle':'action');
      }
      return false;
    }
    const token=++request, slot=runtime.slot===0?1:0, video=videos[slot], old=videos[runtime.slot];
    // Several requests can share the inactive slot while play() is pending.
    // Only its latest owner may stop it or commit the switch.
    clearTimeout(slotPauseTimer[slot]);slotPauseTimer[slot]=0;slotOwner[slot]=token;pending=true;
    video.onended=null;video.onerror=null;video.src=url;video.loop=false;video.muted=true;video.playsInline=true;
    try { await video.play(); } catch (error) {
      if(token!==request)return false;
      pending=false;
      if(runtime.movement)stopMove();
      consecutiveFailures++;
      const needsGesture=error?.name==='NotAllowedError';
      say(needsGesture?'点一下大肥鱼，让我动起来～':'这个动作暂时播放不了。',1);
      // Keep the previous clip running; if it ended while loading, restore a
      // different playable clip. A blocked autoplay must wait for a gesture.
      if((activeEnded || runtime.slot<0) && !needsGesture && consecutiveFailures<3){
        const fallback=INVENTORY.idle.find(item=>item!==name) || Object.values(INVENTORY).flat().find(item=>item!==name && media.has(item));
        if(fallback)void play(fallback,fallback===INVENTORY.idle[0]?'idle':'action');
      }
      return false;
    }
    if(token!==request){if(slotOwner[slot]===token && runtime.slot!==slot)video.pause();return false;}
    pending=false;activeEnded=false;
    runtime.name=name;runtime.kind=kind;runtime.slot=slot;
    video.classList.add('is-active');if(old){
      old.classList.remove('is-active');old.onended=null;old.onerror=null;
      const oldSlot=videos.indexOf(old),oldOwner=slotOwner[oldSlot];
      slotPauseTimer[oldSlot]=setTimeout(()=>{
        slotPauseTimer[oldSlot]=0;
        if(runtime.slot!==oldSlot && slotOwner[oldSlot]===oldOwner)old.pause();
      },200);
    }
    video.onerror=()=>{
      if(runtime.slot!==slot || slotOwner[slot]!==token)return;
      video.onerror=null;video.onended=null;activeEnded=true;consecutiveFailures++;
      if(runtime.movement)stopMove();
      say('这个动作暂时播放不了。',1);
      // A newer request already owns the inactive slot; let it finish rather
      // than stealing it. If it also fails, its catch path can recover.
      if(pending || runtime.paused || runtime.locked || hiddenByUser || consecutiveFailures>=3)return;
      const fallback=INVENTORY.idle.find(item=>item!==name && media.has(item)) || Object.values(INVENTORY).flat().find(item=>item!==name && media.has(item));
      if(fallback)void play(fallback,fallback===INVENTORY.idle[0]?'idle':'action');
    };
    video.onended=()=>{if(runtime.slot!==slot || slotOwner[slot]!==token)return;video.onended=null;video.onerror=null;activeEnded=true;consecutiveFailures=0;
      if(pending)return;
      if(kind==='turn'){runtime.facing=runtime.facing==='left'?'right':'left';paint();}
      // The menu is anchored to the pet. Do not let the random chain move the
      // pet away while the user is navigating the menu.
      if(!menu.hidden){menuDeferred=true;return;}
      const workIndex=states.indexOf(runtime.work);
      // Terminal clips can be shorter than the 10-second state. Keep their
      // final frame until the state timer expires; resume work after any
      // explicitly selected action instead of entering the random chain.
      if(workIndex>=0){if(kind==='work' && workIndex>=4 && name===work[workIndex])return;resume();return;}
      if(kind==='click'||kind==='drag'||kind==='event'||kind==='work'){resume();return;}next();};
    if(((runtime.paused || runtime.locked) && !explicit) || hiddenByUser || kind==='still')video.pause();
    return true;
  };
  const startMove = (name,explicit=false) => {
    stopMove(); const l=limits(), scale=size()/462, d=(60+Math.random()*180)*scale;
    let dir=runtime.facing==='right'?1:-1;let target=runtime.x+dir*d;
    if(target<l.minX||target>l.maxX){dir=-dir;target=runtime.x+dir*d;}
    if(target<l.minX||target>l.maxX){next();return;}
    runtime.facing=dir>0?'right':'left';paint();
    const start=runtime.x,duration=10042,begin=performance.now();runtime.movement={start,target};
    play(name,'move',explicit);
    const tick=now=>{if(!runtime.movement || ((runtime.paused || runtime.locked) && !explicit) || hiddenByUser)return;const p=clamp((now-begin-2000)/(duration-4000),0,1);const eased=p*p*(3-2*p);runtime.x=start+(target-start)*eased;paint();if(now-begin<duration)motionRAF=requestAnimationFrame(tick);else{runtime.movement=null;motionRAF=0;}};
    motionRAF=requestAnimationFrame(tick);
  };
  const startWhisper = explicit => {
    if(!explicit && (document.hidden || runtime.paused || runtime.locked || runtime.drag || runtime.work || hiddenByUser))return;
    if(!reduceMotion() || explicit)void play(pick(INVENTORY['event:whisper'],runtime.name),'event',explicit);
    const generation=++whisperGeneration;
    const snapshot={paused:runtime.paused,locked:runtime.locked,drag:runtime.drag,work:runtime.work,hidden:hiddenByUser,documentHidden:document.hidden};
    const generate=window.NianxiangPetWhisper?.generate;
    Promise.resolve().then(()=>typeof generate==='function'?generate():null).catch(()=>null).then(value=>{
      if(generation!==whisperGeneration || snapshot.paused!==runtime.paused || snapshot.locked!==runtime.locked ||
         snapshot.drag!==runtime.drag || snapshot.work!==runtime.work || snapshot.hidden!==hiddenByUser ||
         snapshot.documentHidden!==document.hidden)return;
      const message=typeof value==='string' && value.trim() ? value.trim() : pick(texts);
      say(message,2,memes.length?pick(memes):null);
    });
  };
  // Release estimator adapted from dsh-pet's MIT-licensed shared/physics.ts.
  const estimateRelease = (trail,now) => {
    if(!trail.length || now-trail[trail.length-1].t>150)return null;
    const win=trail.filter(s=>now-s.t<=150);if(win.length<2)return null;
    const first=win[0],last=win[win.length-1],span=last.t-first.t;if(span<20)return null;
    const bx=(last.x-first.x)/span*1000,by=(last.y-first.y)/span*1000,base=Math.hypot(bx,by);if(base<1e-6)return null;
    let previous=first;const segments=[];
    for(const sample of win.slice(1)){const dt=sample.t-previous.t;if(dt>=8){segments.push({speed:Math.hypot(sample.x-previous.x,sample.y-previous.y)/dt*1000,t:sample.t});previous=sample;}}
    const peak=segments.length?Math.max(...segments.map(s=>s.speed)):base;
    const accel=segments.length>=2?(segments[segments.length-1].speed-segments[0].speed)/Math.max((segments[segments.length-1].t-segments[0].t)/1000,.02):0;
    const raw=(base+peak)*.5*(1+Math.min(Math.max(accel,0)/8000,1)*.6),speed=3600*(1-Math.exp(-raw/3600));
    return speed<500?null:{vx:bx/base*speed,vy:by/base*speed};
  };
  const throwPet = (vx,vy) => {
    stopPhysics(); runtime.vx=vx;runtime.vy=vy;
    let previous=0, elapsed=0;
    const tick=now=>{
      if(!previous)previous=now;let dt=Math.min((now-previous)/1000,.05);previous=now;elapsed+=dt;
      const steps=Math.max(1,Math.ceil(Math.hypot(runtime.vx,runtime.vy)*dt/8)),sub=dt/steps,l=limits();
      for(let i=0;i<steps;i++){
        runtime.vy+=1400*sub;runtime.x+=runtime.vx*sub;runtime.y+=runtime.vy*sub;
        if(runtime.x<l.minX||runtime.x>l.maxX){runtime.x=clamp(runtime.x,l.minX,l.maxX);runtime.vx*=-.78;}
        if(runtime.y<l.minY){runtime.y=l.minY;runtime.vy=Math.abs(runtime.vy)*.78;}
        if(runtime.y>l.maxY){runtime.y=l.maxY;if(runtime.vy>80)squash(runtime.vy>500);runtime.vy=-Math.abs(runtime.vy)*.78;if(Math.abs(runtime.vy)<40)runtime.vy=0;runtime.vx*=Math.max(0,1-2.5*sub);}
      }
      paint();if(elapsed<15 && (Math.abs(runtime.vx)>15||Math.abs(runtime.vy)>40||runtime.y<l.maxY-1))physicsRAF=requestAnimationFrame(tick);else{physicsRAF=0;runtime.vx=runtime.vy=0;resume();}
    };physicsRAF=requestAnimationFrame(tick);
  };
  const hidePet = () => {
    whisperGeneration++;
    hiddenByUser=true;stopMove();stopPhysics();hideTooltip();scoreCard.hidden=true;
    ++request;pending=false;videos[runtime.slot]?.pause();root.hidden=true;
    const composer=document.querySelector('#composer, #m-composer, [data-chat-pet-anchor]')?.getBoundingClientRect();
    restore.hidden=false;
    restore.style.left=clamp(composer?.right-restore.offsetWidth-8 || runtime.x,8,innerWidth-restore.offsetWidth-8)+'px';
    restore.style.top=clamp(composer?.top-restore.offsetHeight-8 || runtime.y,8,innerHeight-restore.offsetHeight-8)+'px';
    restore.focus();
  };
  restore.addEventListener('click',()=>{
    whisperGeneration++;
    hiddenByUser=false;restore.hidden=true;root.hidden=false;bound();paint();
    if(!runtime.paused&&!runtime.locked)resume();
    hit.focus();
  });
  let menuPath=null, menuCloseTimer=0;
  const placeMenu = panels => {
    const panelWidth=Math.max(70,Math.min(180,(innerWidth-32)/3-6));
    const width=panelWidth*3+12;
    const bodyLeft=runtime.x+size()*200/640,bodyRight=runtime.x+size()*440/640;
    // Put the first panel next to the body and let the other two grow away
    // from it; reserving the columns keeps the first panel under the pointer.
    const openLeft=bodyLeft>innerWidth-bodyRight;
    const left=openLeft ? bodyLeft-width-8 : bodyRight+8;
    const composer=document.querySelector('#composer, #m-composer, [data-chat-pet-anchor]')?.getBoundingClientRect();
    // Keep the interactive panels above the input when there is enough room;
    // unusually small layouts still retain an accessible scrollable menu.
    const availableAbove=composer && composer.width && composer.height ? composer.top-16 : innerHeight-16;
    const menuHeight=Math.max(0,Math.min(innerHeight-16,availableAbove>=100?availableAbove:innerHeight-16));
    menu.style.width=`${width}px`;menu.style.height=`${menuHeight}px`;
    menu.style.left=clamp(left,8,innerWidth-width-8)+'px';menu.style.top='8px';
    const bodyCenter=runtime.y+height()*(50+335)/720;
    panels.forEach((panel,i)=>{
      panel.style.left=`${(openLeft?2-i:i)*(panelWidth+6)}px`;panel.style.width=`${panelWidth}px`;
      panel.style.maxHeight=`${Math.min(420,innerHeight*.75,menuHeight)}px`;
      const panelHeight=Math.min(panel.offsetHeight,menuHeight);
      panel.style.top=clamp(bodyCenter-8-panelHeight/2,0,menuHeight-panelHeight)+'px';
    });
  };
  const closeMenu = () => {
    clearTimeout(menuCloseTimer);menuCloseTimer=0;menu.hidden=true;menuPath=null;hit.setAttribute('aria-expanded','false');
    if(menuDeferred){
      menuDeferred=false;
      // Menu handlers may select an explicit action immediately after closing.
      // Let that action take ownership before resuming the automatic chain.
      Promise.resolve().then(()=>{
        if(!menu.hidden || pending || !activeEnded || runtime.paused || runtime.locked || runtime.drag || hiddenByUser)return;
        const workIndex=states.indexOf(runtime.work);
        if(workIndex>=4 && runtime.kind==='work' && runtime.name===work[workIndex])return;
        if(runtime.work || ['click','drag','event','work'].includes(runtime.kind))resume();else next();
      });
    }
  };
  const openMenu = () => {
    whisperGeneration++;
    stopMove();stopPhysics();clearTimeout(longTimer);runtime.drag=null;hideTooltip();root.classList.remove('is-dragging');
    clearTimeout(menuCloseTimer);menuCloseTimer=0;menu.hidden=false;hit.setAttribute('aria-expanded','true');menuPath=null;renderMenu([]);
    menu.children[0]?.children[0]?.focus();
  };
  const menuButton = (panel,label,handler,submenuPath=null) => {
    const b=document.createElement('button');b.type='button';b.setAttribute('role','menuitem');
    b.textContent=label+(submenuPath?'  ›':'');
    if(submenuPath){
      b.setAttribute('aria-haspopup','menu');
      const key=submenuPath.join('\u0000');b.setAttribute('aria-expanded',menuPath===key||menuPath.startsWith(key+'\u0000')?'true':'false');
      b.addEventListener('pointerenter',e=>{if(e.pointerType!=='touch')renderMenu(submenuPath);});
    }
    b.addEventListener('click',handler);panel.append(b);
  };
  const expandMenu = path => {renderMenu(path);menu.children[path.length]?.children[0]?.focus();};
  const renderMenu = path => {
    const pathKey=path.join('\u0000');
    if(menuPath===pathKey && menu.children.length)return;
    const previousScroll=[...menu.children].map(panel=>panel.scrollTop||0);
    menuPath=pathKey;menu.replaceChildren();const panels=[];
    const addPanel=()=>{const p=document.createElement('div');p.className='chat-pet-menu-panel';p.setAttribute('role','menu');menu.append(p);panels.push(p);return p;};
    const rootPanel=addPanel();
    menuButton(rootPanel,'工具',()=>expandMenu(['tools']),['tools']);
    menuButton(rootPanel,'动作',()=>expandMenu(['actions']),['actions']);
    if(path[0]==='tools'){
      const panel=addPanel();
      menuButton(panel,'碎碎念',()=>{closeMenu();startWhisper(true);});
      menuButton(panel,'对话',requestConversation);
      menuButton(panel,'查看余额',()=>{closeMenu();if(runtime.balance===null)say('还没有可用的余额信息。',1);else showBalance(runtime.balance,true);});
      menuButton(panel,'回到初始位置',()=>{closeMenu();home();});
      menuButton(panel,'显示位置',()=>expandMenu(['tools','display']),['tools','display']);
      menuButton(panel,runtime.fixed?'允许自由走动':'固定在这里',()=>{runtime.fixed=!runtime.fixed;closeMenu();});
      menuButton(panel,runtime.paused?'继续动画':'暂停动画',()=>{runtime.paused=!runtime.paused;const v=videos[runtime.slot];if(runtime.paused){v?.pause();stopMove();}else if(activeEnded)resume();else if(v)v.play().catch(()=>{});closeMenu();});
      if(path[1]==='display'){
        const display=addPanel();
        menuButton(display,'网页显示 ✓',()=>closeMenu());
        menuButton(display,'暂时收起',()=>{closeMenu();hidePet();});
      }
    }
    if(path[0]==='actions'){
      const panel=addPanel();
      const groups=[['待机','idle'],['转向','turn'],['拖拽','drag'],['点击回应','click'],['移动','move'],...Object.keys(weights).map(x=>[x,'random:'+x]),['余额','event:balance'],['碎碎念','event:whisper'],['工作状态','event:workStatus']];
      for(const [label,id] of groups)menuButton(panel,label,()=>expandMenu(['actions',id]),['actions',id]);
      if(path.length>1){
        const items=addPanel();
        for(const name of INVENTORY[path[1]]||[])menuButton(items,name,()=>{closeMenu();if(path[1]==='random:文字'){runtime.facing='left';paint();}if(path[1]==='move')startMove(name,true);else play(name,path[1].startsWith('event:')?'event':path[1]==='turn'?'turn':'action',true);});
      }
    }
    panels.forEach((panel,i)=>{panel.scrollTop=previousScroll[i]||0;});
    placeMenu(panels);
  };
  menu.addEventListener('pointerenter',()=>{clearTimeout(menuCloseTimer);menuCloseTimer=0;});
  menu.addEventListener('pointerleave',e=>{if(e?.pointerType==='touch')return;clearTimeout(menuCloseTimer);menuCloseTimer=setTimeout(closeMenu,200);});
  hit.addEventListener('pointerdown',e=>{
    if(e.button!==0)return;hideTooltip();const speed=Math.hypot(runtime.vx,runtime.vy);scoreClick=speed>=400;if(scoreClick){showScore(e.clientX,e.clientY,speed);suppressClick=true;}stopMove();stopPhysics();closeMenu();runtime.locked=false;
    hit.setPointerCapture?.(e.pointerId);const now=performance.now();const sling=now-previousDown<200;previousDown=sling?-1000:now;runtime.drag={id:e.pointerId,sx:e.clientX,sy:e.clientY,ox:runtime.x,oy:runtime.y,targetX:runtime.x,targetY:runtime.y,vx:0,vy:0,moved:false,sling,samples:[{x:e.clientX,y:e.clientY,t:now}]};
    clearTimeout(longTimer);if(e.pointerType==='touch')longTimer=setTimeout(()=>{if(runtime.drag&&!runtime.drag.moved){suppressClick=true;longPressPointerId=e.pointerId;longPressClickPending=true;longPressGeneration++;openMenu();}},500);
  });
  const spring = () => {
    let prev=0;const tick=now=>{const d=runtime.drag;if(!d||!d.moved)return;if(!prev)prev=now;const dt=Math.min((now-prev)/1000,.035);prev=now;d.vx+=((d.targetX-runtime.x)*200-d.vx*30)*dt;d.vy+=((d.targetY-runtime.y)*200-d.vy*30)*dt;runtime.x+=d.vx*dt;runtime.y+=d.vy*dt;bound();paint();motionRAF=requestAnimationFrame(tick);};motionRAF=requestAnimationFrame(tick);
  };
  hit.addEventListener('pointerenter',showTooltip);
  hit.addEventListener('pointerleave',hideTooltip);
  hit.addEventListener('pointermove',e=>{
    const d=runtime.drag;if(!d){showTooltip(e);return;}if(d.id!==e.pointerId)return;const dx=e.clientX-d.sx,dy=e.clientY-d.sy;
    if(!d.moved && Math.hypot(dx,dy)>5){d.moved=true;userMoved=true;clearTimeout(placementTimer);clearTimeout(longTimer);root.classList.add('is-dragging');play(pick(INVENTORY.drag),'drag');spring();}
    if(!d.moved)return;e.preventDefault();d.targetX=d.ox+dx;d.targetY=d.oy+dy;const now=performance.now();d.samples.push({x:e.clientX,y:e.clientY,t:now});d.samples=d.samples.filter(s=>now-s.t<200);
  });
  const endDrag = e => {
    clearTimeout(longTimer);const d=runtime.drag;
    if(!d||d.id!==e.pointerId){
      // A long press opened the menu and cleared drag state. Some browsers do
      // not synthesize a click afterwards; do not swallow the next real tap.
      if(e.pointerId===longPressPointerId){
        longPressPointerId=null;const generation=longPressGeneration;
        clearTimeout(longPressClearTimer);longPressClearTimer=setTimeout(()=>{longPressClearTimer=0;if(generation===longPressGeneration){suppressClick=false;longPressClickPending=false;}},750);
      }
      return;
    }
    runtime.drag=null;cancelAnimationFrame(motionRAF);motionRAF=0;root.classList.remove('is-dragging');
    if(d.moved){
      suppressClick=true;setTimeout(()=>{suppressClick=false;},0);
      let velocity=null;
      if(d.sling){const dx=e.clientX-d.sx,dy=e.clientY-d.sy;const factor=1200/(size()*.6);velocity={vx:-dx*factor,vy:-dy*factor};}
      else velocity=estimateRelease(d.samples,performance.now());
      if(velocity && !reduceMotion())throwPet(velocity.vx,velocity.vy);else{squash();resume();}
    }
  };
  hit.addEventListener('pointerup',endDrag);hit.addEventListener('pointercancel',e=>{endDrag(e);resume();});
  hit.addEventListener('click',()=>{if(suppressClick || scoreClick){suppressClick=false;scoreClick=false;return;}if(runtime.paused){runtime.paused=false;}squash(true);play(pick(INVENTORY.click,runtime.name),'click');say(pick(texts),2);});
  hit.addEventListener('contextmenu',e=>{e.preventDefault();openMenu();});
  // On touch screens the freshly opened menu may lie under the finger. The
  // release click can therefore target a menu item instead of the pet; catch
  // that one synthetic click before it reaches either target.
  document.addEventListener('click',e=>{
    if(!longPressClickPending)return;
    clearTimeout(longPressClearTimer);longPressClearTimer=0;longPressClickPending=false;suppressClick=false;e.preventDefault();e.stopImmediatePropagation();
  },true);
  document.addEventListener('pointerdown',e=>{
    whisperGeneration++;
    // A fresh press is a new interaction, even if the prior long-press click
    // never arrived. It must be allowed through immediately.
    if(longPressClickPending && longPressPointerId===null){clearTimeout(longPressClearTimer);longPressClearTimer=0;longPressClickPending=false;suppressClick=false;}
    if(!menu.hidden&&!menu.contains(e.target)&&e.target!==hit)closeMenu();
  });
  document.addEventListener('keydown',e=>{whisperGeneration++;if(e.key==='Escape'&&!menu.hidden){closeMenu();hit.focus();}});
  document.addEventListener('visibilitychange',()=>{whisperGeneration++;});
  const fitToViewport=()=>{bound();paint();if(!menu.hidden)closeMenu();};
  window.addEventListener('resize',fitToViewport);
  const mobileComposer=document.querySelector('#m-composer');
  const mobilePreview=mobileComposer && document.querySelector('#m-image-preview');
  if(mobileComposer && typeof ResizeObserver==='function'){
    const observer=new ResizeObserver(fitToViewport);observer.observe(mobileComposer);
    if(mobilePreview)observer.observe(mobilePreview);
  }
  if(mobilePreview)new MutationObserver(fitToViewport).observe(mobilePreview,{attributes:true,attributeFilter:['class','hidden','style']});
  window.visualViewport?.addEventListener('resize',fitToViewport);
  const setWork = status => {
    whisperGeneration++;
    const index=states.indexOf(status);runtime.work=index<0?null:status;
    clearTimeout(workTimer);workTimer=0;
    if(index<0 && !bubble.hidden && runtime.priority===0){clearTimeout(bubbleTimer);bubbleTimer=0;bubble.hidden=true;}
    if(index>=4)workTimer=setTimeout(()=>{
      if(runtime.work===status){
        runtime.work=null;
        // Do not cut off an explicit action that is playing or loading.
        if(!runtime.drag&&!pending && (runtime.kind==='work'||runtime.kind==='still') && runtime.name===work[index]){
          if(!menu.hidden || runtime.paused || runtime.locked){
            videos[runtime.slot]?.pause();activeEnded=true;if(!menu.hidden)menuDeferred=true;
          }
          else resume();
        }
      }
      workTimer=0;
    },10000);
    if(runtime.paused||runtime.locked||runtime.drag||hiddenByUser)return;
    if(index>=0){stopMove();play(work[index],reduceMotion()?'still':'work');if(index>=4)say(index===4?'这一轮完成啦！':'刚才遇到一点问题。',4);else showWorkBubble();}
    else resume();
  };
  reduced.addEventListener?.('change',()=>{
    if(reduceMotion()){stopMove();stopPhysics();if(!runtime.drag)resume();}
    else if(runtime.kind==='still')resume();
  });
  new MutationObserver(()=>{const state=document.documentElement.dataset.presenceState;
    if(state==='thinking'&&!justThinking){justThinking=true;setWork('thinking');}
    else if(state!=='thinking'&&justThinking){justThinking=false;setWork(null);}
  }).observe(document.documentElement,{attributes:true,attributeFilter:['data-presence-state']});
  window.NianxiangPet={play:(name)=>play(name,'event',true),say,setWork,home,showReply,cancelConversation,
    isConversationRequested:requestId=>conversationRequest!==null && (requestId===undefined || requestId===conversationRequest),
    setBalance:percent=>{if(runtime.locked||hiddenByUser||!Number.isFinite(percent)||percent<0||percent>100)return false;runtime.balance=percent;showBalance(percent);return true;},
    setLock:locked=>{
      whisperGeneration++;
      runtime.locked=!!locked;const video=videos[runtime.slot];
      if(runtime.locked){stopMove();stopPhysics();video?.pause();if(!bubble.hidden&&runtime.priority===0)bubble.hidden=true;return;}
      if(runtime.paused||runtime.drag||hiddenByUser)return;
      const index=states.indexOf(runtime.work);
      if(index>=4 && runtime.name===work[index] && activeEnded)return;
      // A state may have arrived while locked. Resume that state rather than
      // allowing the old idle clip to restart the random chain.
      if(index>=0 && (runtime.name!==work[index] || activeEnded)){
        play(work[index],reduceMotion()?'still':'work');
        if(index>=4)say(index===4?'这一轮完成啦！':'刚才遇到一点问题。',4);
      }else if(activeEnded || !video)resume();
      else if(!reduceMotion())video.play().catch(()=>{});
      showWorkBubble();
    },getState:()=>({...runtime})};
  const whisper=()=>{startWhisper(false);setTimeout(whisper,300000);};
  setTimeout(whisper,300000);
  // The chat shell starts hidden while session setup runs. Wait until the
  // composer has real geometry, unless the user has already placed the pet.
  const placeWhenReady = () => {
    if(userMoved)return;
    if(!home())placementTimer=setTimeout(placeWhenReady,500);
  };
  placeWhenReady();
  // Only this read-only same-origin manifest supplies images; user messages
  // and other conversation data are never included in the request.
  fetch('/api/pet-memes',{credentials:'same-origin'}).then(r=>r.ok?r.json():Promise.reject()).then(data=>{
    if(!data.available||!Array.isArray(data.memes))return;
    memes=data.memes.filter(item=>item && typeof item.name==='string' && typeof item.url==='string' && /^\/api\/pet-memes\/[^/?#]+\.png$/i.test(item.url));
  }).catch(()=>{memes=[];});
  fetch('/api/pet-assets',{credentials:'same-origin'}).then(r=>r.ok?r.json():Promise.reject()).then(data=>{
    if(!data.available||!Array.isArray(data.animations))throw new Error('unavailable');
    media=new Map(data.animations.filter(a=>a && typeof a.name==='string' && typeof a.url==='string').map(a=>[a.name,a.url]));
    if(!media.has(INVENTORY.idle[0]))throw new Error('idle missing');resume();
  }).catch(()=>{root.classList.add('is-unavailable');hit.setAttribute('aria-label','大肥鱼素材暂不可用');say('大肥鱼的动作素材暂不可用。',2);});
})();
