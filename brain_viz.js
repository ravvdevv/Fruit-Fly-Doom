// Fruit Fly Brain Visualization - Real-time neural activity display
class FruitFlyBrainViz {
  constructor(canvasId, options = {}) {
    this.canvas = document.getElementById(canvasId);
    if (!this.canvas) throw new Error(`Canvas #${canvasId} not found`);
    this.ctx = this.canvas.getContext('2d');
    this.width = options.width || 400;
    this.height = options.height || 400;
    this.canvas.width = this.width;
    this.canvas.height = this.height;
    this.populations = this.definePopulations();
    this.connections = this.defineConnections();
    this.activity = {};
    for (const key of Object.keys(this.populations)) this.activity[key] = 0;
    this.spikes = [];
    this.spikeHistory = [];
    this.maxSpikes = 50;
    this.running = false;
    this.lastFrame = 0;
    this.time = 0;
    this.rateMap = this.defineRateMap();
    this.bindResize();
  }
definePopulations() {
    return {
      'DNa02_L': { x: 0.15, y: 0.75, type: 'DN', side: 'L', color: '#ff6b6b', label: 'DNa02' },
      'DNa02_R': { x: 0.85, y: 0.75, type: 'DN', side: 'R', color: '#ff6b6b', label: 'DNa02' },
      'DNp09_L': { x: 0.20, y: 0.65, type: 'DN', side: 'L', color: '#ff8e8e', label: 'DNp09' },
      'DNp09_R': { x: 0.80, y: 0.65, type: 'DN', side: 'R', color: '#ff8e8e', label: 'DNp09' },
      'MDN_L':   { x: 0.25, y: 0.55, type: 'DN', side: 'L', color: '#ffaaaa', label: 'MDN' },
      'MDN_R':   { x: 0.75, y: 0.55, type: 'DN', side: 'R', color: '#ffaaaa', label: 'MDN' },
      'DNp20_L': { x: 0.15, y: 0.45, type: 'DN', side: 'L', color: '#ffcccc', label: 'DNp20' },
      'DNp20_R': { x: 0.85, y: 0.45, type: 'DN', side: 'R', color: '#ffcccc', label: 'DNp20' },
      'DNpe017_L': { x: 0.20, y: 0.35, type: 'DN', side: 'L', color: '#ffe0e0', label: 'DNpe017' },
      'DNpe017_R': { x: 0.80, y: 0.35, type: 'DN', side: 'R', color: '#ffe0e0', label: 'DNpe017' },
      'LC11_L': { x: 0.10, y: 0.20, type: 'LC', side: 'L', color: '#6bff6b', label: 'LC11' },
      'LC11_R': { x: 0.90, y: 0.20, type: 'LC', side: 'R', color: '#6bff6b', label: 'LC11' },
      'LC18_L': { x: 0.15, y: 0.15, type: 'LC', side: 'L', color: '#8eff8e', label: 'LC18' },
      'LC18_R': { x: 0.85, y: 0.15, type: 'LC', side: 'R', color: '#8eff8e', label: 'LC18' },
      'LC17_L': { x: 0.20, y: 0.10, type: 'LC', side: 'L', color: '#aaffaa', label: 'LC17' },
      'LC17_R': { x: 0.80, y: 0.10, type: 'LC', side: 'R', color: '#aaffaa', label: 'LC17' },
      'LPLC2_L': { x: 0.25, y: 0.12, type: 'LC', side: 'L', color: '#ccffcc', label: 'LPLC2' },
      'LPLC2_R': { x: 0.75, y: 0.12, type: 'LC', side: 'R', color: '#ccffcc', label: 'LPLC2' },
      'LC4_L':  { x: 0.30, y: 0.18, type: 'LC', side: 'L', color: '#e0ffe0', label: 'LC4' },
      'LC4_R':  { x: 0.70, y: 0.18, type: 'LC', side: 'R', color: '#e0ffe0', label: 'LC4' },
      'LC6_L':  { x: 0.35, y: 0.25, type: 'LC', side: 'L', color: '#b8ffb8', label: 'LC6' },
      'LC6_R':  { x: 0.65, y: 0.25, type: 'LC', side: 'R', color: '#b8ffb8', label: 'LC6' },
    };
  }

  defineConnections() {
    return [
      ['LC11_L', 'DNp20_L'], ['LC11_R', 'DNp20_R'],
      ['LC18_L', 'DNpe017_L'], ['LC18_R', 'DNpe017_R'],
      ['LC17_L', 'MDN_L'], ['LC17_R', 'MDN_R'],
      ['LPLC2_L', 'DNa02_L'], ['LPLC2_R', 'DNa02_R'],
      ['LC4_L', 'DNp09_L'], ['LC4_R', 'DNp09_R'],
      ['LC6_L', 'DNp09_L'], ['LC6_R', 'DNp09_R'],
      ['DNa02_L', 'DNa02_R'], ['DNp09_L', 'DNp09_R'],
      ['MDN_L', 'MDN_R'], ['DNp20_L', 'DNp20_R'],
      ['DNpe017_L', 'DNpe017_R'],
    ];
  }

  defineRateMap() {
    return {
      'DNa02': ['DNa02_L', 'DNa02_R'],
      'DNp09': ['DNp09_L', 'DNp09_R'],
      'MDN': ['MDN_L', 'MDN_R'],
      'DNp20': ['DNp20_L', 'DNp20_R'],
      'DNpe017': ['DNpe017_L', 'DNpe017_R'],
      'LC11': ['LC11_L', 'LC11_R'],
      'LC18': ['LC18_L', 'LC18_R'],
      'LC17': ['LC17_L', 'LC17_R'],
      'LPLC2': ['LPLC2_L', 'LPLC2_R'],
      'LC4': ['LC4_L', 'LC4_R'],
      'LC6': ['LC6_L', 'LC6_R'],
    };
  }
bindResize() {
    const resize = () => {
      const rect = this.canvas.getBoundingClientRect();
      if (rect.width && rect.height) {
        this.canvas.width = rect.width;
        this.canvas.height = rect.height;
        this.width = rect.width;
        this.height = rect.height;
      }
    };
    window.addEventListener('resize', resize);
    resize();
  }

  updateRates(rates) {
    if (!rates) return;
    for (const [popName, rate] of Object.entries(rates)) {
      const targets = this.rateMap[popName];
      if (targets) {
        const activity = Math.min(1, rate / 50);
        for (const target of targets) {
          this.activity[target] = activity;
          if (activity > 0.3 && Math.random() < activity * 0.1) this.emitSpike(target);
        }
      }
    }
    for (const [key, rate] of Object.entries(rates)) {
      if ((key.includes('_L') || key.includes('_R')) && this.activity.hasOwnProperty(key)) {
        const activity = Math.min(1, rate / 50);
        this.activity[key] = activity;
        if (activity > 0.3 && Math.random() < activity * 0.1) this.emitSpike(key);
      }
    }
  }

  emitSpike(popKey) {
    const pop = this.populations[popKey];
    if (!pop) return;
    const x = pop.x * this.width;
    const y = pop.y * this.height;
    const angle = Math.random() * Math.PI * 2;
    const speed = 1 + Math.random() * 2;
    this.spikes.push({
      x, y,
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed,
      life: 1.0,
      color: pop.color,
      size: 3 + Math.random() * 4
    });
  }

  decayActivity(dt) {
    const decayRate = 0.95;
    for (const key of Object.keys(this.activity)) this.activity[key] *= decayRate;
  }

  updateSpikes(dt) {
    for (let i = this.spikes.length - 1; i >= 0; i--) {
      const s = this.spikes[i];
      s.x += s.vx * dt * 60;
      s.y += s.vy * dt * 60;
      s.life -= dt * 2;
      s.size *= 0.98;
      if (s.life <= 0 || s.size < 0.5) this.spikes.splice(i, 1);
    }
    this.spikeHistory.push(this.spikes.length);
    if (this.spikeHistory.length > 100) this.spikeHistory.shift();
  }
draw() {
    const ctx = this.ctx;
    const w = this.width, h = this.height;
    ctx.fillStyle = '#05080b';
    ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = '#1a1f26';
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 10; i++) {
      const x = (w / 10) * i, y = (h / 10) * i;
      ctx.beginPath();
      ctx.moveTo(x, 0); ctx.lineTo(x, h);
      ctx.moveTo(0, y); ctx.lineTo(w, y);
    }
    ctx.stroke();
    this.drawConnections();
    this.drawPopulations();
    this.drawSpikes();
    this.drawSpikeGraph();
    this.drawLabels();
  }

  drawConnections() {
    const ctx = this.ctx;
    ctx.lineWidth = 1;
    for (const [from, to] of this.connections) {
      const p1 = this.populations[from], p2 = this.populations[to];
      if (!p1 || !p2) continue;
      const x1 = p1.x * this.width, y1 = p1.y * this.height;
      const x2 = p2.x * this.width, y2 = p2.y * this.height;
      const act1 = this.activity[from] || 0, act2 = this.activity[to] || 0;
      const strength = (act1 + act2) / 2;
      ctx.strokeStyle = `rgba(100, 150, 100, ${0.1 + strength * 0.4})`;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      const cx = (x1 + x2) / 2, cy = (y1 + y2) / 2 - 20;
      ctx.quadraticCurveTo(cx, cy, x2, y2);
      ctx.stroke();
    }
  }

  drawPopulations() {
    const ctx = this.ctx;
    for (const [key, pop] of Object.entries(this.populations)) {
      const x = pop.x * this.width, y = pop.y * this.height;
      const activity = this.activity[key] || 0;
      const baseRadius = 8;
      const pulseRadius = baseRadius + activity * 12 + Math.sin(this.time * 8 + x * 0.1) * 2;
      if (activity > 0.1) {
        const grad = ctx.createRadialGradient(x, y, 0, x, y, pulseRadius * 2);
        grad.addColorStop(0, pop.color + '80');
        grad.addColorStop(1, pop.color + '00');
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(x, y, pulseRadius * 2, 0, Math.PI * 2);
        ctx.fill();
      }
      const intensity = 0.3 + activity * 0.7;
      ctx.fillStyle = pop.color;
      ctx.globalAlpha = intensity;
      ctx.beginPath();
      ctx.arc(x, y, pulseRadius, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
      if (activity > 0.5) {
        ctx.strokeStyle = pop.color;
        ctx.lineWidth = 2;
        ctx.globalAlpha = activity;
        ctx.beginPath();
        ctx.arc(x, y, pulseRadius + 4, 0, Math.PI * 2);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
    }
  }

  drawSpikes() {
    const ctx = this.ctx;
    for (const s of this.spikes) {
      ctx.globalAlpha = s.life;
      ctx.fillStyle = s.color;
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.size, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }
drawSpikeGraph() {
    const ctx = this.ctx;
    const w = this.width, h = this.height;
    const graphH = 60, graphY = h - graphH - 10;
    const graphW = w - 20, graphX = 10;
    ctx.fillStyle = 'rgba(0, 10, 5, 0.6)';
    ctx.fillRect(graphX, graphY, graphW, graphH);
    ctx.strokeStyle = 'rgba(100, 200, 100, 0.1)';
    ctx.lineWidth = 0.5;
    for (let i = 1; i < 4; i++) {
      const y = graphY + (graphH / 4) * i;
      ctx.beginPath();
      ctx.moveTo(graphX, y);
      ctx.lineTo(graphX + graphW, y);
      ctx.stroke();
    }
    if (this.spikeHistory.length > 1) {
      ctx.strokeStyle = '#6bff6b';
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (let i = 0; i < this.spikeHistory.length; i++) {
        const x = graphX + (graphW / (this.spikeHistory.length - 1)) * i;
        const y = graphY + graphH - (this.spikeHistory[i] / this.maxSpikes) * graphH;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    ctx.fillStyle = '#8fbb8f';
    ctx.font = '9px "IBM Plex Mono", monospace';
    ctx.fillText('NEURAL SPIKES / FRAME', graphX, graphY - 2);
  }

  drawLabels() {
    const ctx = this.ctx;
    ctx.font = '8px "IBM Plex Mono", monospace';
    ctx.textAlign = 'center';
    for (const [key, pop] of Object.entries(this.populations)) {
      const x = pop.x * this.width, y = pop.y * this.height + 18;
      const activity = this.activity[key] || 0;
      ctx.fillStyle = activity > 0.3 ? pop.color : '#5a6a5a';
      ctx.fillText(pop.label, x, y);
      if (activity > 0.1) {
        ctx.fillStyle = pop.color + 'aa';
        ctx.font = '7px "IBM Plex Mono", monospace';
        ctx.fillText((activity * 50).toFixed(1) + 'Hz', x, y + 10);
        ctx.font = '8px "IBM Plex Mono", monospace';
      }
    }
    ctx.textAlign = 'start';
  }

  highlightAction(action) {
    const actionMap = {
      'forward': ['DNp09_L', 'DNp09_R', 'DNpe017_L', 'DNpe017_R'],
      'reverse': ['MDN_L', 'MDN_R'],
      'left': ['DNa02_L', 'LPLC2_L'],
      'right': ['DNa02_R', 'LPLC2_R'],
      'fire': ['DNa02_L', 'DNa02_R', 'DNp20_L', 'DNp20_R'],
    };
    const targets = actionMap[action];
    if (targets) {
      for (const t of targets) {
        if (this.activity.hasOwnProperty(t)) {
          this.activity[t] = Math.max(this.activity[t], 0.8);
          this.emitSpike(t);
        }
      }
    }
  }

  animate(now) {
    if (!this.running) return;
    const dt = Math.min(0.05, (now - this.lastFrame) / 1000 || 0);
    this.lastFrame = now;
    this.time += dt;
    this.decayActivity(dt);
    this.updateSpikes(dt);
    this.draw();
    requestAnimationFrame(this.animate.bind(this));
  }

  start() {
    this.running = true;
    this.lastFrame = performance.now();
    requestAnimationFrame(this.animate.bind(this));
  }

  stop() {
    this.running = false;
  }
}

class BrainDataPoller {
  constructor(viz, options = {}) {
    this.viz = viz;
    this.url = options.url || '/brain-data.json';
    this.interval = options.interval || 200;
    this.timer = null;
  }
  start() {
    this.poll();
    this.timer = setInterval(() => this.poll(), this.interval);
  }
  stop() {
    if (this.timer) clearInterval(this.timer);
  }
  async poll() {
    try {
      const resp = await fetch(this.url + '?t=' + Date.now(), { cache: 'no-store' });
      if (resp.ok) {
        const data = await resp.json();
        if (data.rates) this.viz.updateRates(data.rates);
        if (data.actions) for (const a of data.actions) this.viz.highlightAction(a);
      }
    } catch (e) {}
  }
}

class BrainDataStdout {
  constructor(viz) { this.viz = viz; this.buffer = ''; }
  feed(line) {
    this.buffer += line;
    const lines = this.buffer.split('\n');
    this.buffer = lines.pop();
    for (const l of lines) {
      if (l.trim().startsWith('{')) {
        try {
          const data = JSON.parse(l);
          if (data.rates) this.viz.updateRates(data.rates);
          if (data.actions) for (const a of data.actions) this.viz.highlightAction(a);
        } catch (e) {}
      }
    }
  }
}

if (typeof module !== 'undefined') {
  module.exports = { FruitFlyBrainViz, BrainDataPoller, BrainDataStdout };
}