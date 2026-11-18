(() => {
  const canvas = document.getElementById('game');
  const ctx = canvas.getContext('2d');
  const $ = (id) => document.getElementById(id);
  const W = 640, H = 360, FOV = Math.PI / 2.9;
  canvas.width = W; canvas.height = H;
  const map = [
    '1111111111111111','1000000000000001','1020000000003001','1000110001100001',
    '1000100000100001','1000000000000001','1003000000002001','1000001111000001',
    '1000001001000001','1000001001000001','1000000000000001','1030000000000201',
    '1000110001100001','1000000000000001','1000000000000001','1111111111111111'
  ];
  const wall = (x,y) => map[Math.floor(y)]?.[Math.floor(x)] !== '0';
  let player, enemies, keys = {}, running = false, paused = false, pilotMode = true, last = 0, zBuffer = [], kills = 0, score = 0, wave = 1, fireCooldown = 0, hurtCooldown = 0, ammo = 12;
  const reset = () => {
    player = {x:2.5,y:2.5,a:.2,hp:100};
    enemies = [];
    for(let i=0;i<5;i++) spawnEnemy();
    kills=0;score=0;wave=1;ammo=12;fireCooldown=0;hurtCooldown=0;
    updateHud();
  };
  function spawnEnemy(){
    let x,y,tries=0;
    do{x=2+Math.random()*11;y=2+Math.random()*11;tries++}while((wall(x,y)||Math.hypot(x-player.x,y-player.y)<4)&&tries<100);
    enemies.push({x,y,hp:2,phase:Math.random()*6.28,attack:0});
  }
  function resize(){const rect=canvas.getBoundingClientRect();if(rect.width&&rect.height){/* CSS scales the fixed retro framebuffer */}}
  function cast(angle){
    const sin=Math.sin(angle),cos=Math.cos(angle);
    let d=0,hit=0,side=0;
    while(d<20&&!hit){d+=.035;const x=player.x+cos*d,y=player.y+sin*d;if(wall(x,y)){hit=1;side=(Math.floor(x)!==Math.floor(player.x+cos*(d-.035)))?1:0;}}
    return {d:Math.max(.05,d*Math.cos(angle-player.a)),side};
  }
  function drawWorld(){
    const sky=ctx.createLinearGradient(0,0,0,H/2);sky.addColorStop(0,'#151c26');sky.addColorStop(1,'#4b3029');ctx.fillStyle=sky;ctx.fillRect(0,0,W,H/2);
    const floor=ctx.createLinearGradient(0,H/2,0,H);floor.addColorStop(0,'#34251f');floor.addColorStop(1,'#090b0d');ctx.fillStyle=floor;ctx.fillRect(0,H/2,W,H/2);
    zBuffer.length=W;
    for(let x=0;x<W;x++){
      const angle=player.a+(x/W-.5)*FOV,hit=cast(angle),d=hit.d;zBuffer[x]=d;
      const height=Math.min(H,H/(d*.82)),top=(H-height)/2;
      const shade=Math.max(22,155-d*17)*(hit.side?.72:1);
      const brick=Math.floor((x*13+Math.floor(top/12)*7)%13);
      ctx.fillStyle='rgb('+Math.floor(shade)+','+Math.floor(shade*.48)+','+Math.floor(shade*.34)+')';
      ctx.fillRect(x,top,1,height);
      if(brick===0){ctx.fillStyle='#170f0d55';ctx.fillRect(x,top,1,height)}
    }
    drawEnemies();
    drawWeapon();
  }
  function drawEnemies(){
    const visible=enemies.map(e=>{let dx=e.x-player.x,dy=e.y-player.y;let angle=Math.atan2(dy,dx)-player.a;while(angle>Math.PI)angle-=Math.PI*2;while(angle<-Math.PI)angle+=Math.PI*2;return{e,angle,d:Math.hypot(dx,dy)}}).filter(o=>Math.abs(o.angle)<FOV*.62&&o.d>.2).sort((a,b)=>b.d-a.d);
    for(const o of visible){
      const sx=(.5+o.angle/FOV)*W, size=Math.min(H,H/(o.d*.72)), sy=H/2-size*.52;
      if(sx<0||sx>=W)continue;
      const col=Math.max(0,Math.min(W-1,Math.floor(sx)));
      if(o.d>zBuffer[col]+.2)continue;
      const s=size/100;
      ctx.save();ctx.translate(sx,sy);
      // Demonic fruit: a floating, angry rotten berry with horns.
      ctx.fillStyle='#d8b07b';ctx.beginPath();ctx.moveTo(-17*s,12*s);ctx.lineTo(-28*s,-12*s);ctx.lineTo(-7*s,-3*s);ctx.fill();
      ctx.beginPath();ctx.moveTo(17*s,12*s);ctx.lineTo(28*s,-12*s);ctx.lineTo(7*s,-3*s);ctx.fill();
      ctx.fillStyle='#7f2927';ctx.beginPath();ctx.ellipse(0,0,24*s,30*s,0,0,Math.PI*2);ctx.fill();
      ctx.fillStyle='#d84a36';ctx.beginPath();ctx.ellipse(-7*s,-8*s,8*s,7*s,0,0,Math.PI*2);ctx.ellipse(8*s,-8*s,8*s,7*s,0,0,Math.PI*2);ctx.fill();
      ctx.fillStyle='#fff3c7';ctx.beginPath();ctx.arc(-7*s,-8*s,3*s,0,Math.PI*2);ctx.arc(8*s,-8*s,3*s,0,Math.PI*2);ctx.fill();
      ctx.fillStyle='#170b0a';ctx.fillRect(-11*s,8*s,22*s,5*s);
      ctx.fillStyle='#f1bd66';ctx.fillRect(-18*s,27*s,36*s,5*s);
      ctx.restore();
    }
  }
  function drawWeapon(){
    const bob=Math.sin(performance.now()*.009)*2;
    ctx.save();ctx.translate(W/2,H-22+bob);
    ctx.fillStyle='#38291e';ctx.beginPath();ctx.moveTo(-34,20);ctx.lineTo(-24,-25);ctx.lineTo(-9,-42);ctx.lineTo(9,-42);ctx.lineTo(24,-25);ctx.lineTo(34,20);ctx.fill();
    ctx.fillStyle='#b56d35';ctx.fillRect(-15,-48,30,25);ctx.fillStyle='#3b4140';ctx.fillRect(-8,-67,16,25);ctx.fillStyle='#d8a35c';ctx.fillRect(-4,-69,8,5);
    ctx.fillStyle='#202729';ctx.fillRect(-24,-15,48,24);ctx.restore();
  }
  function fire(){
    if(!running||paused||fireCooldown>0||ammo<=0)return;
    ammo--;fireCooldown=.28;
    let target=null,best=Infinity;
    for(const e of enemies){let a=Math.atan2(e.y-player.y,e.x-player.x)-player.a;while(a>Math.PI)a-=Math.PI*2;while(a<-Math.PI)a+=Math.PI*2;let d=Math.hypot(e.x-player.x,e.y-player.y);if(Math.abs(a)<.11&&d<best&&!wall(player.x+Math.cos(player.a)*d,player.y+Math.sin(player.a)*d)){target=e;best=d;}}
    if(target){target.hp--;score+=25;if(target.hp<=0){enemies.splice(enemies.indexOf(target),1);kills++;score+=100;}}
    if(ammo===0&&enemies.length){ammo=12;}
    updateHud();
  }
  function updatePilot(dt){
    if(!enemies.length)return;
    const target=enemies.reduce((best,e)=>Math.hypot(e.x-player.x,e.y-player.y)<Math.hypot(best.x-player.x,best.y-player.y)?e:best,enemies[0]);
    const dx=target.x-player.x,dy=target.y-player.y,d=Math.hypot(dx,dy);
    let diff=Math.atan2(dy,dx)-player.a;while(diff>Math.PI)diff-=Math.PI*2;while(diff<-Math.PI)diff+=Math.PI*2;
    // A tiny reactive controller: orient toward the nearest target, keep a safe gap, and fire when aligned.
    player.a+=Math.max(-1,Math.min(1,diff))*dt*2.7;
    if(Math.abs(diff)<.16)fire();
    const direction=d>3.2?1:(d<1.8?-1:0),speed=1.8*dt;
    const strafe=(Math.abs(diff)>.65?Math.sign(diff)*.35:0);
    const vx=Math.cos(player.a)*direction*speed+Math.cos(player.a+Math.PI/2)*strafe*speed;
    const vy=Math.sin(player.a)*direction*speed+Math.sin(player.a+Math.PI/2)*strafe*speed;
    if(!wall(player.x+vx,player.y))player.x+=vx;
    if(!wall(player.x,player.y+vy))player.y+=vy;
  }
  function update(dt){
    fireCooldown=Math.max(0,fireCooldown-dt);hurtCooldown=Math.max(0,hurtCooldown-dt);
    if(pilotMode)updatePilot(dt);
    let speed=(keys.Shift?3.8:2.5)*dt,dx=0,dy=0;
    if(!pilotMode&&(keys.KeyW||keys.ArrowUp)){dx+=Math.cos(player.a)*speed;dy+=Math.sin(player.a)*speed}
    if(!pilotMode&&(keys.KeyS||keys.ArrowDown)){dx-=Math.cos(player.a)*speed;dy-=Math.sin(player.a)*speed}
    if(!pilotMode&&keys.KeyA){dx+=Math.cos(player.a-Math.PI/2)*speed;dy+=Math.sin(player.a-Math.PI/2)*speed}
    if(!pilotMode&&keys.KeyD){dx+=Math.cos(player.a+Math.PI/2)*speed;dy+=Math.sin(player.a+Math.PI/2)*speed}
    if(!wall(player.x+dx,player.y))player.x+=dx;if(!wall(player.x,player.y+dy))player.y+=dy;
    if(!pilotMode){if(keys.ArrowLeft)player.a-=2*dt;if(keys.ArrowRight)player.a+=2*dt;if(keys.Space)fire();}
    for(const e of enemies){
      const d=Math.hypot(player.x-e.x,player.y-e.y);
      if(d>0.65){const vx=(player.x-e.x)/d*.55*dt,vy=(player.y-e.y)/d*.55*dt;if(!wall(e.x+vx,e.y))e.x+=vx;if(!wall(e.x,e.y+vy))e.y+=vy;}
      else if(hurtCooldown<=0){player.hp=Math.max(0,player.hp-8);hurtCooldown=.7;$('damage').style.opacity='.25';setTimeout(()=>$('damage').style.opacity='0',100);updateHud();}
    }
    if(enemies.length===0){wave++;for(let i=0;i<4+wave;i++)spawnEnemy();ammo=12;$('level').textContent='WAVE '+String(wave).padStart(2,'0');updateHud();}
    if(player.hp<=0){running=false;showMessage('THE FLY HAS BEEN<br><em>SWATTED.</em>','REBOOT NEURAL RUN');}
  }
  function updateHud(){
    $('health').textContent=player.hp;$('healthbar').style.width=player.hp+'%';$('ammo').textContent=ammo;$('ammobar').style.width=(ammo/12*100)+'%';$('score').textContent='KILLS '+String(kills).padStart(3,'0')+' · SCORE '+String(score).padStart(4,'0');
  }
  function showMessage(title,button){$('message').classList.remove('hidden');$('message').querySelector('h1').innerHTML=title;$('start').textContent=button;}
  function loop(now){
    const dt=Math.min(.05,(now-last)/1000||0);last=now;
    if(running&&!paused)update(dt);
    if(player){drawWorld();}
    requestAnimationFrame(loop);
  }
  $('start').addEventListener('click',()=>{if(!player||player.hp<=0)reset();running=true;paused=false;$('message').classList.add('hidden');canvas.requestPointerLock?.();});
  document.addEventListener('keydown',e=>{keys[e.code]=true;if(['Space','ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.code))e.preventDefault();if(e.code==='KeyP'){pilotMode=!pilotMode;$('pilot-status').textContent='AI PILOT: '+(pilotMode?'ON':'OFF');}if(e.code==='Escape'&&running){paused=!paused;if(paused)showMessage('NEURAL LINK<br><em>PAUSED.</em>','RESUME RUN');else $('message').classList.add('hidden');}});
  document.addEventListener('keyup',e=>keys[e.code]=false);
  document.addEventListener('mousemove',e=>{if(document.pointerLockElement===canvas&&running&&!paused&&!pilotMode)player.a+=e.movementX*.0025;});
  canvas.addEventListener('click',()=>{if(running&&!paused){if(document.pointerLockElement!==canvas)canvas.requestPointerLock?.();fire();}});
  reset();requestAnimationFrame(loop);window.addEventListener('resize',resize);

  // Initialize brain visualization
  let brainViz = null;
  try {
    const brainCanvas = document.getElementById('brain-viz');
    if (brainCanvas && window.FruitFlyBrainViz) {
      brainViz = new FruitFlyBrainViz('brain-viz');
      brainViz.start();
      console.log('[BrainViz] Neural visualization started');
    }
  } catch (e) {
    console.warn('[BrainViz] Failed to initialize:', e);
  }

  // Hook into pilot actions to drive brain viz
  const originalUpdatePilot = updatePilot;
  updatePilot = function(dt) {
    const actions = [];
    if (!player) return originalUpdatePilot(dt);
    
    const target = enemies.reduce((best, e) => {
      const d = Math.hypot(player.x - e.x, player.y - e.y);
      if (!best || d < best.d) return {e, d};
      return best;
    }, null);
    
    if (target) {
      const dx = target.e.x - player.x;
      const dy = target.e.y - player.y;
      const angle = Math.atan2(dy, dx);
      let diff = angle - player.a;
      while (diff > Math.PI) diff -= Math.PI * 2;
      while (diff < -Math.PI) diff += Math.PI * 2;
      const d = target.d;
      
      if (Math.abs(diff) > 0.16) {
        actions.push(diff > 0 ? 'right' : 'left');
      } else {
        actions.push('forward');
      }
      if (d < 2.5 && Math.abs(diff) < 0.3) {
        actions.push('fire');
      }
      if (d < 1.8) {
        actions.push('reverse');
      }
    }
    
    if (brainViz && actions.length) {
      const rates = {};
      if (actions.includes('forward')) {
        rates.DNp09 = 40; rates.DNpe017 = 35;
      }
      if (actions.includes('reverse')) {
        rates.MDN = 45;
      }
      if (actions.includes('left')) {
        rates.DNa02 = 38; rates.LPLC2 = 30;
      }
      if (actions.includes('right')) {
        rates.DNa02 = 38; rates.LPLC2 = 30;
      }
      if (actions.includes('fire')) {
        rates.DNa02 = 50; rates.DNp20 = 40;
      }
      // Visual input always active
      rates.LC11 = 25; rates.LC18 = 20; rates.LC17 = 15;
      rates.LPLC2 = 18; rates.LC4 = 12; rates.LC6 = 10;
      
      brainViz.updateRates(rates);
      for (const a of actions) brainViz.highlightAction(a);
    }
    
    return originalUpdatePilot(dt);
  };
})();