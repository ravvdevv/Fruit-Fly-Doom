const $=id=>document.getElementById(id),fmt=(v,n=1)=>Number.isFinite(Number(v))?Number(v).toFixed(n):"—",clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
let populationMax=1,lastScreenFrame=-1,frameRequest=null;const canvas=$("brain-canvas"),ctx=canvas.getContext("2d");
const names=["DNp20_L","DNp20_R","DNpe017_L","DNpe017_R","DNp09","MDN","DNa02","LC11","LC18","LC17","LPLC2","LC4","LC6"];
const nodes=[{name:"RETINA",x:.12,y:.5,keys:["visual_L","visual_R"]},{name:"LAMINA",x:.30,y:.5,keys:["object_detector"]},{name:"LOOM",x:.49,y:.2,keys:["looming_detector","LPLC2","LC4","LC6"]},{name:"LC",x:.49,y:.77,keys:["LC11","LC18","LC17"]},{name:"DN LEFT",x:.76,y:.28,keys:["DNp20_L","DNpe017_L","DNa02_L"]},{name:"DN RIGHT",x:.76,y:.72,keys:["DNp20_R","DNpe017_R","DNa02_R"]},{name:"MOTOR",x:.93,y:.5,keys:["DNp09","MDN"]}];
function drawBrain(r){const w=canvas.width,h=canvas.height;ctx.clearRect(0,0,w,h);ctx.strokeStyle="#293c55";ctx.lineWidth=2;[[0,4],[1,4],[1,5],[2,4],[2,5],[3,4],[3,5],[4,6],[5,6]].forEach(([a,b])=>{ctx.beginPath();ctx.moveTo(nodes[a].x*w,nodes[a].y*h);ctx.lineTo(nodes[b].x*w,nodes[b].y*h);ctx.stroke()});nodes.forEach(n=>{const v=n.keys.reduce((s,k)=>s+(Number(r[k])||0),0),p=clamp(v/Math.max(1,populationMax),0,1),x=n.x*w,y=n.y*h,rad=15+p*16;ctx.beginPath();ctx.arc(x,y,rad+8,0,Math.PI*2);ctx.fillStyle="rgba(104,225,210,"+(.035+p*.15)+")";ctx.fill();ctx.beginPath();ctx.arc(x,y,rad,0,Math.PI*2);ctx.fillStyle="rgba(65, "+Math.round(110+p*110)+", "+Math.round(155+p*95)+", .95)";ctx.fill();ctx.strokeStyle="#9debe1";ctx.stroke();ctx.fillStyle="#e6f2ff";ctx.font="11px monospace";ctx.textAlign="center";ctx.fillText(n.name,x,y+rad+19);ctx.fillStyle="#91a5bb";ctx.font="10px monospace";ctx.fillText(fmt(v,1),x,y+4)})}
function renderPop(r){const host=$("populations");host.innerHTML="";const keys=names.filter(k=>k in r);if(!keys.length){host.innerHTML="<p>No population activity received. Run with <code>--connectome</code> to display real FlyScroll readouts.</p>";return}populationMax=Math.max(1,...keys.map(k=>Number(r[k])||0));keys.forEach(k=>{const v=Number(r[k])||0,row=document.createElement("div");row.className="pop-row";row.innerHTML="<span>"+k.replace("_"," ")+"</span><i><b style='width:"+clamp(v/populationMax*100,0,100)+"%'></b></i><em>"+fmt(v,1)+"</em>";host.appendChild(row)})}
function actionsUI(a){const s=new Set(a||[]);window.flyActions=Array.from(s);const mode=s.has("attack")?"ATTACKING":s.has("left")?"TURNING LEFT":s.has("right")?"TURNING RIGHT":s.has("forward")?"WALKING / FLYING":s.has("backward")?"RETREATING":"OBSERVING";$("fly-mode").textContent=mode;$("fly-action").textContent=mode;$("fly-detail").textContent=s.size?"Motor output: "+Array.from(s).join(" · "):"No active action in this decision";$("action-row").innerHTML=[["FORWARD",s.has("forward")],["TURN",s.has("left")||s.has("right")],["ATTACK",s.has("attack")],["STRAFE",s.has("strafe_left")||s.has("strafe_right")]].map(([n,on])=>"<span class='"+(on?"active":"")+"'>"+n+(on?" ●":"")+"</span>").join("")}
function render(d){if(!d)return;if(!d.connected){$("live-dot").classList.remove("on");$("connection").textContent="SIMULATION DISCONNECTED";$("sim-status").textContent="OFFLINE";return}$("live-dot").classList.add("on");$("connection").textContent="SIMULATION CONNECTED";$("sim-status").textContent="RUNNING";$("fps").textContent=fmt(d.fps);$("frame").textContent=d.frame||0;$("spikes").textContent=d.spikes||0;if(Number(d.frame)!==lastScreenFrame){lastScreenFrame=Number(d.frame)||0;if(frameRequest)frameRequest.abort();frameRequest=new AbortController();fetch("/api/frame.jpg?v="+lastScreenFrame,{cache:"no-store",signal:frameRequest.signal}).then(r=>{if(!r.ok)throw new Error("Frame HTTP "+r.status);return r.blob()}).then(blob=>{const img=$("game-frame"),url=URL.createObjectURL(blob),old=img.dataset.objectUrl;img.onload=()=>{if(old)URL.revokeObjectURL(old);img.dataset.objectUrl=url};img.onerror=()=>URL.revokeObjectURL(url);img.src=url;$("screen-empty").style.display="none"}).catch(e=>{if(e.name!=="AbortError")console.warn("[FlyScroll] Game frame unavailable",e)})}const s=d.stats||{};["health","armor","ammo","kills","items","secrets"].forEach(k=>$(k).textContent=fmt(s[k],0));$("health").classList.toggle("critical",Number(s.health)<=25);$("health-bar").style.width=clamp(Number(s.health)||0,0,100)+"%";$("armor-bar").style.width=clamp(Number(s.armor)||0,0,100)+"%";$("target").textContent="TARGET · "+(d.target||"—");$("decision").textContent=d.target||"Exploring";$("decision-note").textContent="Reward "+fmt(d.reward,2)+" · Decision "+(d.frame||0);actionsUI(d.actions||[]);const r=d.rates||{},f=d.features||{};$("brain-status").textContent=d.brain_connected?"CONNECTOME ACTIVE":"CONNECTOME DISABLED";$("neural-time").textContent=fmt(d.neural_ms)+" ms simulated";$("kernel-time").textContent=fmt(d.kernel_ms)+" ms kernel";$("luma").textContent=fmt(f.luminance_mean??f.luma_mean??f.mean_luminance,2);$("chroma").textContent=fmt(f.chromatic_energy??f.chromatic_mean??f.chroma,2);$("visual-left").textContent=fmt(r.visual_L,2);$("visual-right").textContent=fmt(r.visual_R,2);$("object-value").textContent=fmt(r.object_detector,1);$("loom-value").textContent=fmt(r.looming_detector,1);$("object-bar").style.width=clamp((Number(r.object_detector)||0)/Math.max(1,populationMax)*100,0,100)+"%";$("loom-bar").style.width=clamp((Number(r.looming_detector)||0)/Math.max(1,populationMax)*100,0,100)+"%";drawBrain(r);renderPop(r)}
let polling=false;async function poll(){if(polling)return;polling=true;try{const res=await fetch("/api/state",{cache:"no-store"});if(!res.ok)throw new Error("State HTTP "+res.status);render(await res.json())}catch(e){$("connection").textContent="DASHBOARD SERVER DISCONNECTED";$("live-dot").classList.remove("on");console.warn("[FlyScroll] State poll failed",e)}finally{polling=false}}
setInterval(poll,250);poll();

// NeuroMechFly v2 anatomical 3D fly. The model meshes and rig metadata are
// served by the authors' Apache-2.0 fly-svg-maker asset mirror.
async function bootAnatomicalFly(THREE, FK, STL) {
  const canvas = $("fly3d");
  const status = $("fly-load-status");
  const base = "https://cdn.jsdelivr.net/gh/NeLy-EPFL/fly-svg-maker@main/assets";
  const label = (value) => { if (status) status.textContent = value; };
  try {
    label("LOADING NEUROMECHFLY MODEL…");
    const response = await fetch(base + "/model.json");
    if (!response.ok) throw new Error("Model metadata HTTP " + response.status);
    const model = await response.json();
    const files = Array.from(new Set(model.segments.map((s) => model.meshes[s].file)));
    const raw = {};
    let count = 0;
    label("LOADING ANATOMICAL MESHES · 0/" + files.length);
    await Promise.all(files.map(async (file) => {
      const r = await fetch(base + "/meshes/" + file);
      if (!r.ok) throw new Error("Mesh HTTP " + r.status + ": " + file);
      raw[file] = STL.parseBinarySTL(await r.arrayBuffer());
      count += 1;
      label("LOADING ANATOMICAL MESHES · " + count + "/" + files.length);
    }));

    const renderer = new THREE.WebGLRenderer({canvas,alpha:true,antialias:true,powerPreference:"low-power"});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1,1.75));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.25;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(34,1,0.01,1000);
    camera.up.set(0,0,1);
    scene.add(new THREE.HemisphereLight(0xe7f5ff,0x4b3021,2.0));
    const key = new THREE.DirectionalLight(0xffe4bd,3.1);
    key.position.set(-3,-4,7);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x77d9e7,1.8);
    rim.position.set(2,4,3);
    scene.add(rim);

    const pivot = new THREE.Group();
    const rig = new THREE.Group();
    scene.add(pivot);
    pivot.add(rig);
    const meshes = {};
    const materials = {};
    const basePose = FK.neutralPoseRad(model);
    const pose = Object.assign({},basePose);
    model.segments.forEach((segment) => {
      const spec = model.meshes[segment];
      const vertices = STL.transformVertices(raw[spec.file],model.meshScale,spec.mirror);
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position",new THREE.BufferAttribute(vertices,3));
      geometry.computeVertexNormals();
      const color = model.colors[segment] || [0.55,0.4,0.24,1];
      const alpha = color.length > 3 ? color[3] : 1;
      const material = new THREE.MeshStandardMaterial({
        color:new THREE.Color().setRGB(color[0],color[1],color[2],THREE.SRGBColorSpace),
        roughness:0.72,metalness:0.02,side:THREE.DoubleSide,
        transparent:alpha < 1,opacity:alpha
      });
      const mesh = new THREE.Mesh(geometry,material);
      mesh.matrixAutoUpdate = false;
      rig.add(mesh);
      meshes[segment] = mesh;
      materials[segment] = material;
    });

    const initial = FK.segmentTransforms(model,pose);
    Object.keys(meshes).forEach((name) => {
      const t = initial[name];
      meshes[name].matrix.set(t[0],t[1],t[2],t[3],t[4],t[5],t[6],t[7],t[8],t[9],t[10],t[11],t[12],t[13],t[14],t[15]);
    });
    rig.updateMatrixWorld(true);
    const bounds = new THREE.Box3().setFromObject(rig);
    const center = bounds.getCenter(new THREE.Vector3());
    const extent = bounds.getSize(new THREE.Vector3());
    const radius = Math.max(extent.length(),1);
    rig.position.copy(center).multiplyScalar(-1);
    pivot.position.copy(center);

    let distance = radius * 1.65;
    let yaw = -0.88;
    let pitch = 0.28;
    const target = center.clone();
    function updateCamera() {
      const horizontal = distance * Math.cos(pitch);
      camera.position.set(
        target.x + horizontal * Math.cos(yaw),
        target.y + horizontal * Math.sin(yaw),
        target.z + distance * Math.sin(pitch)
      );
      camera.lookAt(target);
    }
    updateCamera();
    function resize() {
      const rect = canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      renderer.setSize(rect.width,rect.height,false);
      camera.aspect = rect.width / rect.height;
      camera.updateProjectionMatrix();
    }
    const observer = new ResizeObserver(resize);
    observer.observe(canvas.parentElement);
    resize();

    let dragging = false, lastX = 0, lastY = 0;
    canvas.addEventListener("pointerdown",(e) => {
      dragging = true; lastX = e.clientX; lastY = e.clientY;
      canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener("pointermove",(e) => {
      if (!dragging) return;
      yaw -= (e.clientX-lastX)*0.008;
      pitch = Math.max(-1.15,Math.min(1.15,pitch+(e.clientY-lastY)*0.006));
      lastX = e.clientX; lastY = e.clientY; updateCamera();
    });
    const stop = () => { dragging = false; };
    canvas.addEventListener("pointerup",stop);
    canvas.addEventListener("pointercancel",stop);
    canvas.addEventListener("wheel",(e) => {
      e.preventDefault();
      distance = Math.max(radius*0.78,Math.min(radius*4.5,distance*Math.exp(e.deltaY*0.001)));
      updateCamera();
    },{passive:false});
    $("fly-reset").addEventListener("click",() => { yaw=-0.88; pitch=0.28; distance=radius*1.65; updateCamera(); });

    const dofs = {};
    model.dofs.forEach((d) => { dofs[d.child + ":" + d.axis] = d.name; });
    const dof = (child,axis) => dofs[child + ":" + axis];
    const legs = ["lf","lm","lh","rf","rm","rh"].map((id,index) => ({
      index,coxa:dof(id+"_coxa","pitch"),
      femur:dof(id+"_trochanterfemur","pitch"),
      tibia:dof(id+"_tibia","pitch")
    }));
    const leftWing = dof("l_wing","roll");
    const rightWing = dof("r_wing","roll");
    const headPitch = dof("c_head","pitch");
    const eyes = [materials.l_eye,materials.r_eye].filter(Boolean);

    function frame(now) {
      requestAnimationFrame(frame);
      const time = now * 0.001;
      const actions = new Set(window.flyActions || []);
      const forward = actions.has("forward") || actions.has("backward");
      const strafing = actions.has("strafe_left") || actions.has("strafe_right");
      const attacking = actions.has("attack");
      const gait = forward || strafing;
      const turn = (actions.has("left") ? 1 : 0) - (actions.has("right") ? 1 : 0);
      const strafe = (actions.has("strafe_left") ? 1 : 0) - (actions.has("strafe_right") ? 1 : 0);
      Object.keys(pose).forEach((name) => { pose[name] = basePose[name] || 0; });

      const wingBeat = Math.sin(time*145) * (gait || turn || attacking ? 0.62 : 0.38);
      if (leftWing) pose[leftWing] = (basePose[leftWing] || 0) + wingBeat;
      if (rightWing) pose[rightWing] = (basePose[rightWing] || 0) - wingBeat;
      legs.forEach((leg) => {
        const phase = time*(gait ? 8.5 : 1.25) + leg.index*Math.PI*0.72;
        const amplitude = gait ? 0.34 : 0.045;
        if (leg.coxa) pose[leg.coxa] = (basePose[leg.coxa] || 0) + Math.sin(phase)*amplitude;
        if (leg.femur) pose[leg.femur] = (basePose[leg.femur] || 0) + Math.sin(phase+1.1)*amplitude*1.25;
        if (leg.tibia) pose[leg.tibia] = (basePose[leg.tibia] || 0) + Math.max(0,Math.sin(phase+1.1))*(gait ? 0.42 : 0.035);
      });
      if (headPitch) pose[headPitch] = (basePose[headPitch] || 0) + (attacking ? -0.12 : 0);
      const transforms = FK.segmentTransforms(model,pose);
      Object.keys(meshes).forEach((name) => {
        const t = transforms[name];
        meshes[name].matrix.set(t[0],t[1],t[2],t[3],t[4],t[5],t[6],t[7],t[8],t[9],t[10],t[11],t[12],t[13],t[14],t[15]);
        meshes[name].matrixWorldNeedsUpdate = true;
      });
      pivot.rotation.z += ((turn*0.22 + strafe*0.12)-pivot.rotation.z)*0.08;
      pivot.position.z = center.z + Math.sin(time*(gait?10:1.8))*(gait?0.055:0.018);
      pivot.position.x = center.x + (attacking ? Math.sin(time*24)*0.025 : 0);
      eyes.forEach((mat) => {
        mat.emissive.setHex(attacking ? 0x5b1708 : 0x000000);
        mat.emissiveIntensity = attacking ? 0.75 + Math.sin(time*18)*0.2 : 0;
      });
      renderer.render(scene,camera);
    }
    label("MODEL READY · " + model.segments.length + " SEGMENTS");
    if (status) status.classList.add("hidden");
    console.info("[FlyScroll] NeuroMechFly v2 loaded",model.segments.length,"segments and",files.length,"unique meshes");
    requestAnimationFrame(frame);
  } catch (error) {
    console.error("[FlyScroll] 3D fly failed to load",error);
    label("3D MODEL FAILED · CHECK CONNECTION");
    $("fly-detail").textContent = "Research model failed to load. Check browser console.";
  }
}

Promise.all([
  import("https://cdn.jsdelivr.net/npm/three@0.180.0/build/three.module.js"),
  import("https://cdn.jsdelivr.net/gh/NeLy-EPFL/fly-svg-maker@main/fk.js"),
  import("https://cdn.jsdelivr.net/gh/NeLy-EPFL/fly-svg-maker@main/stl.js")
]).then(([THREE,FK,STL]) => bootAnatomicalFly(THREE,FK,STL)).catch((error) => {
  console.error("[FlyScroll] 3D renderer dependencies failed",error);
  const status = $("fly-load-status");
  if (status) status.textContent = "3D RENDERER FAILED · CHECK CONNECTION";
});
