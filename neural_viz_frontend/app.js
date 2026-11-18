/**
 * Fruitfly Neural Dashboard — MaleCNS Visual Connectome
 * Real-time visualization of Drosophila connectome activity driving DOOM
 */

// ===== Configuration =====
const HTTP_API = `http://${location.hostname}:8765`;
const WS_URL = `ws://${location.hostname}:8766/ws`;
const RECONNECT_DELAY = 2000;
const MAX_LOG_ENTRIES = 200;
const NEURAL_HISTORY_LENGTH = 120; // frames of history for sparklines
const POLL_INTERVAL = 100; // ms - HTTP polling fallback

// Neuron population definitions with colors
const NEURON_POPS = [
  { key: 'DNp20_L', label: 'DNp20 L', color: '#c8f169', category: 'descending' },
  { key: 'DNp20_R', label: 'DNp20 R', color: '#a8d149', category: 'descending' },
  { key: 'DNpe017_L', label: 'DNpe017 L', color: '#8fd640', category: 'descending' },
  { key: 'DNpe017_R', label: 'DNpe017 R', color: '#74bb3a', category: 'descending' },
  { key: 'DNp09', label: 'DNp09', color: '#3ddbd9', category: 'forward' },
  { key: 'MDN', label: 'MDN', color: '#f2b85c', category: 'reverse' },
  { key: 'DNa02', label: 'DNa02', color: '#b87cff', category: 'descending' },
  { key: 'LC11', label: 'LC11', color: '#ff6b9d', category: 'visual' },
  { key: 'LC18', label: 'LC18', color: '#ff8fab', category: 'visual' },
  { key: 'LC17', label: 'LC17', color: '#ffb3c6', category: 'visual' },
  { key: 'LPLC2', label: 'LPLC2', color: '#ff4d43', category: 'looming' },
  { key: 'LC4', label: 'LC4', color: '#ff7843', category: 'looming' },
  { key: 'LC6', label: 'LC6', color: '#ff9f43', category: 'looming' },
];

// ===== State =====
let ws = null;
let reconnectTimer = null;
let paused = false;
let neuralHistory = []; // array of { timestamp, rates }
let currentFrame = 0;
let lastFrameTime = performance.now();
let frameTimes = [];
let animationFrameId = null;

// DOM Elements
const els = {
  connIndicator: document.getElementById('conn-indicator'),
  connText: document.getElementById('conn-text'),
  modeBadge: document.getElementById('mode-badge'),
  fpsMetric: document.getElementById('fps-metric').querySelector('.value'),
  frameMetric: document.getElementById('frame-metric').querySelector('.value'),
  spikesMetric: document.getElementById('spikes-metric').querySelector('.value'),
  simMetric: document.getElementById('sim-metric').querySelector('.value'),
  kernelMetric: document.getElementById('kernel-metric').querySelector('.value'),
  neuralCanvas: document.getElementById('neural-canvas'),
  neuralLegend: document.getElementById('neural-legend'),
  retinalCanvas: document.getElementById('retinal-canvas'),
  connectomeCanvas: document.getElementById('connectome-canvas'),
  decodedCanvas: document.getElementById('decoded-canvas'),
  brainViewSelect: document.getElementById('brain-view'),
  brainViews: document.querySelectorAll('.brain-view'),
  actionCells: document.querySelectorAll('.action-cell'),
  turnDelta: document.getElementById('turn-delta'),
  visualDn: document.getElementById('visual-dn'),
  visualL: document.getElementById('visual-l'),
  visualR: document.getElementById('visual-r'),
  looming: document.getElementById('looming'),
  objects: document.getElementById('objects'),
  lumaMean: document.getElementById('luma-mean'),
  lumaStd: document.getElementById('luma-std'),
  totalSpikes: document.getElementById('total-spikes'),
  simTime: document.getElementById('sim-time'),
  logContent: document.getElementById('log-content'),
  logPanel: document.getElementById('log-panel'),
  logToggle: document.getElementById('log-toggle'),
  neuralPause: document.getElementById('neural-pause'),
};

// Canvas contexts
const ctx = {
  neural: els.neuralCanvas.getContext('2d'),
  retinal: els.retinalCanvas.getContext('2d'),
  connectome: els.connectomeCanvas.getContext('2d'),
  decoded: els.decodedCanvas.getContext('2d'),
};

// ===== Utility Functions =====
function clamp(v, min, max) { return Math.max(min, Math.min(max, v)); }
function lerp(a, b, t) { return a + (b - a) * t; }
function now() { return performance.now(); }

function resizeCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  canvas.style.width = rect.width + 'px';
  canvas.style.height = rect.height + 'px';
  canvas.getContext('2d').scale(dpr, dpr);
  return { width: rect.width, height: rect.height };
}

function resizeAllCanvases() {
  Object.values(ctx).forEach(c => resizeCanvas(c.canvas));
}

window.addEventListener('resize', () => {
  resizeAllCanvases();
  drawAll();
});

function logEntry(type, data) {
  const time = new Date().toLocaleTimeString();
  const entry = document.createElement('div');
  entry.className = 'log-entry';
  entry.innerHTML = `<span class="log-time">[${time}]</span><span class="log-type">${type}</span><span class="log-data">${JSON.stringify(data)}</span>`;
  els.logContent.insertBefore(entry, els.logContent.firstChild);
  while (els.logContent.children.length > MAX_LOG_ENTRIES) {
    els.logContent.removeChild(els.logContent.lastChild);
  }
}

// ===== Connection (WebSocket + HTTP Polling Fallback) =====
let useWebSocket = true;
let pollTimer = null;
let lastPolledFrame = 0;

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;

  els.connIndicator.classList.remove('connected');
  els.connIndicator.classList.add('disconnected');
  els.connText.textContent = 'Connecting…';

  // Try WebSocket first
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    useWebSocket = true;
    els.connIndicator.classList.remove('disconnected');
    els.connIndicator.classList.add('connected');
    els.connText.textContent = 'CONNECTED (WS)';
    els.modeBadge.textContent = 'LIVE';
    logEntry('WS', { status: 'connected' });
    stopPolling();
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'state' || msg.type === 'update') {
        handleNeuralData(msg.data);
      }
    } catch (e) {
      console.error('WS parse error:', e);
    }
  };

  ws.onclose = () => {
    els.connIndicator.classList.remove('connected');
    els.connIndicator.classList.add('disconnected');
    els.connText.textContent = 'WS closed - polling…';
    els.modeBadge.textContent = 'POLLING';
    logEntry('WS', { status: 'disconnected, falling back to polling' });
    startPolling();
  };

  ws.onerror = (err) => {
    logEntry('WS', { error: 'WS error, will fallback to polling' });
  };

  // Fallback to polling after 3 seconds if WS doesn't connect
  setTimeout(() => {
    if (ws.readyState !== WebSocket.OPEN) {
      ws.close();
      startPolling();
    }
  }, 3000);
}

function startPolling() {
  if (pollTimer) return;
  useWebSocket = false;
  logEntry('HTTP', { status: 'started polling' });
  pollTimer = setInterval(pollState, POLL_INTERVAL);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function pollState() {
  try {
    const resp = await fetch(`${HTTP_API}/api/state`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (data.frame !== lastPolledFrame) {
      lastPolledFrame = data.frame;
      handleNeuralData(data);
    }
    // Update connection status
    if (els.connText.textContent.includes('polling')) {
      els.connText.textContent = 'CONNECTED (HTTP)';
      els.modeBadge.textContent = 'POLLING';
      els.connIndicator.classList.remove('disconnected');
      els.connIndicator.classList.add('connected');
    }
  } catch (e) {
    logEntry('HTTP', { error: e.message });
    els.connIndicator.classList.remove('connected');
    els.connIndicator.classList.add('disconnected');
    els.connText.textContent = 'DISCONNECTED';
    els.modeBadge.textContent = 'OFFLINE';
  }
}

function scheduleReconnect() {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connect, RECONNECT_DELAY);
}

// ===== Neural Data Handler =====
function handleNeuralData(data) {
  if (paused) return;

  currentFrame = data.frame || currentFrame + 1;
  const frameTime = now();
  frameTimes.push(frameTime);
  while (frameTimes.length > 60 && frameTimes[frameTimes.length - 1] - frameTimes[0] > 1000) {
    frameTimes.shift();
  }
  const fps = frameTimes.length / ((frameTimes[frameTimes.length - 1] - frameTimes[0]) / 1000) || 0;

  // Update metrics
  els.fpsMetric.textContent = Math.round(fps);
  els.frameMetric.textContent = currentFrame;
  els.spikesMetric.textContent = data.spikes || 0;
  els.simMetric.textContent = (data.simulation_ms || 0).toFixed(1);
  els.kernelMetric.textContent = (data.kernel_ms || 0).toFixed(1);

  // Store history for sparklines
  neuralHistory.push({
    timestamp: frameTime,
    rates: data.rates || {},
  });
  if (neuralHistory.length > NEURAL_HISTORY_LENGTH) neuralHistory.shift();

  // Update decoder state
  els.turnDelta.textContent = (data.turn_delta || 0).toFixed(3);
  els.visualDn.textContent = (data.visual_dn || 0).toFixed(3);
  els.visualL.textContent = (data.rates?.visual_L || 0).toFixed(3);
  els.visualR.textContent = (data.rates?.visual_R || 0).toFixed(3);
  els.looming.textContent = (data.rates?.looming_detector || 0).toFixed(3);
  els.objects.textContent = (data.rates?.object_detector || 0).toFixed(3);

  // Update game telemetry
  els.lumaMean.textContent = (data.frame_luma_mean || 0).toFixed(1);
  els.lumaStd.textContent = (data.frame_luma_std || 0).toFixed(1);
  els.totalSpikes.textContent = data.total_spikes || 0;
  els.simTime.textContent = (data.simulation_ms || 0).toFixed(1);

  // Update action cells
  const actions = new Set(data.actions || data.decoded_actions || []);
  els.actionCells.forEach(cell => {
    const action = cell.dataset.action;
    if (actions.has(action)) {
      cell.classList.add('active');
      // Remove active after brief delay
      setTimeout(() => cell.classList.remove('active'), 300);
    }
  });

  // Update decoded canvas data
  lastDecodedData = {
    turn: data.turn_delta || 0,
    visual: data.visual_dn || 0,
    visualL: data.rates?.visual_L || 0,
    visualR: data.rates?.visual_R || 0,
    looming: data.rates?.looming_detector || 0,
    objects: data.rates?.object_detector || 0,
    actions: actions,
  };

  // Log occasionally
  if (currentFrame % 30 === 0) {
    logEntry('NEURAL', {
      frame: currentFrame,
      spikes: data.spikes,
      actions: [...actions],
      turn: data.turn_delta,
    });
  }

  // Trigger redraw
  scheduleDraw();
}

let lastDecodedData = {};
let drawScheduled = false;
function scheduleDraw() {
  if (!drawScheduled) {
    drawScheduled = true;
    requestAnimationFrame(() => {
      drawScheduled = false;
      drawAll();
    });
  }
}

// ===== Drawing Functions =====
function drawAll() {
  drawNeuralPanel();
  drawRetinalView();
  drawConnectomeView();
  drawDecodedView();
}

function clearCanvas(context, width, height) {
  context.clearRect(0, 0, width, height);
}

// --- Neural Population Sparklines ---
function drawNeuralPanel() {
  const canvas = els.neuralCanvas;
  const size = resizeCanvas(canvas);
  const { width, height } = size;
  const c = ctx.neural;
  clearCanvas(c, width, height);

  if (neuralHistory.length < 2) return;

  const padding = { top: 20, right: 10, bottom: 30, left: 50 };
  const plotW = width - padding.left - padding.right;
  const plotH = height - padding.top - padding.bottom;
  const popCount = NEURON_POPS.length;
  const rowH = plotH / popCount;

  // Draw background grid
  c.strokeStyle = '#1a252f';
  c.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = padding.top + (i / 4) * plotH;
    c.beginPath();
    c.moveTo(padding.left, y);
    c.lineTo(width - padding.right, y);
    c.stroke();
  }
  for (let i = 0; i <= 10; i++) {
    const x = padding.left + (i / 10) * plotW;
    c.beginPath();
    c.moveTo(x, padding.top);
    c.lineTo(x, height - padding.bottom);
    c.stroke();
  }

  // Find max rate for scaling
  let maxRate = 1;
  neuralHistory.forEach(h => {
    NEURON_POPS.forEach(p => {
      const r = h.rates[p.key];
      if (r !== undefined) maxRate = Math.max(maxRate, r);
    });
  });
  maxRate = Math.max(maxRate, 5); // minimum scale

  // Draw each population
  NEURON_POPS.forEach((pop, idx) => {
    const rowTop = padding.top + idx * rowH;
    const rowCenter = rowTop + rowH * 0.5;
    const zeroY = rowCenter;
    const scale = (rowH * 0.4) / maxRate;

    // Population label
    c.fillStyle = pop.color;
    c.font = '10px JetBrains Mono';
    c.textAlign = 'right';
    c.textBaseline = 'middle';
    c.fillText(pop.label, padding.left - 8, rowCenter);

    // Draw sparkline
    c.strokeStyle = pop.color;
    c.lineWidth = 1.5;
    c.lineCap = 'round';
    c.lineJoin = 'round';
    c.beginPath();

    neuralHistory.forEach((h, i) => {
      const rate = h.rates[pop.key] || 0;
      const x = padding.left + (i / (NEURAL_HISTORY_LENGTH - 1)) * plotW;
      const y = zeroY - rate * scale;
      if (i === 0) c.moveTo(x, y);
      else c.lineTo(x, y);
    });
    c.stroke();

    // Current value indicator
    const latest = neuralHistory[neuralHistory.length - 1];
    const currentRate = latest.rates[pop.key] || 0;
    const cx = width - padding.right;
    const cy = zeroY - currentRate * scale;
    c.fillStyle = pop.color;
    c.beginPath();
    c.arc(cx, cy, 3, 0, Math.PI * 2);
    c.fill();
    c.fillStyle = '#fff';
    c.font = '9px JetBrains Mono';
    c.textAlign = 'left';
    c.fillText(currentRate.toFixed(1), cx + 6, cy + 3);
  });

  // Time axis
  c.fillStyle = '#5a6d64';
  c.font = '8px JetBrains Mono';
  c.textAlign = 'center';
  c.fillText('-20s', padding.left, height - padding.bottom + 14);
  c.fillText('NOW', width - padding.right, height - padding.bottom + 14);
}

// --- Retinal View (simulated compound eye input) ---
function drawRetinalView() {
  const canvas = els.retinalCanvas;
  const size = resizeCanvas(canvas);
  const { width, height } = size;
  const c = ctx.retinal;
  clearCanvas(c, width, height);

  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.min(width, height) * 0.42;

  // Draw compound eye facets (hexagonal grid)
  const facetSize = radius / 8;
  const cols = Math.ceil(width / facetSize);
  const rows = Math.ceil(height / facetSize);

  // Simulated retinal activity based on neural data
  const visualActivity = neuralHistory.length > 0
    ? (neuralHistory[neuralHistory.length - 1].rates.visual_total || 0)
    : 0;
  const activityLevel = clamp(visualActivity / 50, 0, 1);

  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      const x = col * facetSize * 1.1 + (row % 2) * facetSize * 0.55;
      const y = row * facetSize * 0.95;
      const dx = x - centerX;
      const dy = y - centerY;
      const dist = Math.sqrt(dx * dx + dy * dy);

      if (dist > radius) continue;

      // Base luminance with noise
      const noise = (Math.sin(x * 0.1) * Math.cos(y * 0.1) + Math.sin(x * 0.05 + now() * 0.001)) * 0.5;
      const activation = activityLevel * (1 - dist / radius) + noise * 0.1;
      const intensity = clamp(activation, 0, 1);

      // Hexagon
      c.beginPath();
      for (let i = 0; i < 6; i++) {
        const angle = (i / 6) * Math.PI * 2;
        c.lineTo(x + Math.cos(angle) * facetSize * 0.5, y + Math.sin(angle) * facetSize * 0.5);
      }
      c.closePath();

      // Color based on activation - luminance channel
      const r = Math.floor(20 + intensity * 180);
      const g = Math.floor(15 + intensity * 100);
      const b = Math.floor(10 + intensity * 50);
      c.fillStyle = `rgb(${r},${g},${b})`;
      c.fill();

      // Chromatic accent for high activation
      if (intensity > 0.7) {
        c.strokeStyle = `rgba(200, 241, 105, ${(intensity - 0.7) * 3})`;
        c.lineWidth = 1;
        c.stroke();
      }
    }
  }

  // Center reticle
  c.strokeStyle = 'rgba(200, 241, 105, 0.5)';
  c.lineWidth = 1;
  c.setLineDash([4, 4]);
  c.beginPath();
  c.arc(centerX, centerY, radius, 0, Math.PI * 2);
  c.stroke();
  c.setLineDash([]);

  // Activity ring
  const ringRadius = radius + 10;
  c.strokeStyle = `rgba(200, 241, 105, ${0.3 + activityLevel * 0.5})`;
  c.lineWidth = 3;
  c.beginPath();
  c.arc(centerX, centerY, ringRadius, -Math.PI / 2, -Math.PI / 2 + activityLevel * Math.PI * 2);
  c.stroke();
}

// --- Connectome View (3D-ish neuron network) ---
const connectomeNodes = [];
const connectomeEdges = [];

function initConnectome() {
  // Generate nodes in 3D space organized by brain regions
  const regions = [
    { name: 'Retina', x: -1, y: 0, z: 0, count: 8, color: '#3ddbd9', size: 0.8 },
    { name: 'Lamina', x: -0.6, y: 0, z: 0, count: 12, color: '#3ddbd9', size: 0.7 },
    { name: 'Medulla', x: -0.2, y: 0, z: 0, count: 20, color: '#b87cff', size: 0.6 },
    { name: 'Lobula', x: 0.2, y: 0, z: 0, count: 16, color: '#ff8fab', size: 0.7 },
    { name: 'LC Neurons', x: 0.5, y: 0.3, z: 0, count: 12, color: '#ff6b9d', size: 0.9 },
    { name: 'LPLC2', x: 0.5, y: -0.3, z: 0, count: 8, color: '#ff4d43', size: 1.0 },
    { name: 'Descending', x: 0.9, y: 0, z: 0, count: 10, color: '#c8f169', size: 1.2 },
  ];

  let nodeId = 0;
  regions.forEach(region => {
    for (let i = 0; i < region.count; i++) {
      const angle = (i / region.count) * Math.PI * 2;
      const r = 0.15 + Math.random() * 0.1;
      connectomeNodes.push({
        id: nodeId++,
        x: region.x + Math.cos(angle) * r,
        y: region.y + Math.sin(angle) * r * 0.5,
        z: region.z + (Math.random() - 0.5) * 0.2,
        region: region.name,
        color: region.color,
        baseSize: region.size,
        activation: 0,
        targetActivation: 0,
      });
    }
  });

  // Create edges (feedforward connections)
  for (let i = 0; i < connectomeNodes.length; i++) {
    const a = connectomeNodes[i];
    // Connect to nodes in next region
    connectomeNodes.forEach(b => {
      if (b.x > a.x && b.x - a.x < 0.5 && Math.random() < 0.15) {
        connectomeEdges.push({ from: a.id, to: b.id, weight: 0.3 + Math.random() * 0.7 });
      }
    });
  }
}

function updateConnectomeActivations() {
  if (neuralHistory.length === 0) return;

  const latest = neuralHistory[neuralHistory.length - 1].rates;

  // Map neural rates to node activations
  connectomeNodes.forEach(node => {
    let target = 0;
    if (node.region === 'Retina' || node.region === 'Lamina') {
      target = (latest.visual_total || 0) / 100;
    } else if (node.region === 'Medulla') {
      target = (latest.object_detector || 0) / 50;
    } else if (node.region === 'LC Neurons') {
      target = (latest.object_detector || 0) / 30;
    } else if (node.region === 'LPLC2') {
      target = (latest.looming_detector || 0) / 20;
    } else if (node.region === 'Descending') {
      target = (latest.visual_dn || 0) / 30;
    }
    node.targetActivation = clamp(target + (Math.random() - 0.5) * 0.1, 0, 1);
    // Smooth interpolation
    node.activation = lerp(node.activation, node.targetActivation, 0.15);
  });
}

function drawConnectomeView() {
  const canvas = els.connectomeCanvas;
  const size = resizeCanvas(canvas);
  const { width, height } = size;
  const c = ctx.connectome;
  clearCanvas(c, width, height);

  if (connectomeNodes.length === 0) initConnectome();
  updateConnectomeActivations();

  // 3D projection
  const scale = Math.min(width, height) * 0.35;
  const centerX = width / 2;
  const centerY = height / 2;
  const rotationY = now() * 0.00015; // Slow rotation
  const rotationX = -0.2;

  // Project nodes
  const projected = connectomeNodes.map(node => {
    // Rotate Y
    let x = node.x * Math.cos(rotationY) - node.z * Math.sin(rotationY);
    let z = node.x * Math.sin(rotationY) + node.z * Math.cos(rotationY);
    // Rotate X
    const y = node.y * Math.cos(rotationX) - z * Math.sin(rotationX);
    z = node.y * Math.sin(rotationX) + z * Math.cos(rotationX);

    // Perspective
    const perspective = 2 / (2 + z);
    return {
      ...node,
      px: centerX + x * scale * perspective,
      py: centerY + y * scale * perspective,
      pz: z,
      pscale: perspective,
    };
  });

  // Sort by depth for painter's algorithm
  projected.sort((a, b) => b.pz - a.pz);

  // Draw edges
  connectomeEdges.forEach(edge => {
    const from = projected.find(n => n.id === edge.from);
    const to = projected.find(n => n.id === edge.to);
    if (!from || !to) return;

    const act = (from.activation + to.activation) * 0.5 * edge.weight;
    if (act < 0.02) return;

    c.beginPath();
    c.moveTo(from.px, from.py);
    c.lineTo(to.px, to.py);

    const alpha = clamp(act * 0.6, 0, 0.5);
    const r = parseInt(from.color.slice(1, 3), 16);
    const g = parseInt(from.color.slice(3, 5), 16);
    const b = parseInt(from.color.slice(5, 7), 16);
    c.strokeStyle = `rgba(${r},${g},${b},${alpha})`;
    c.lineWidth = clamp(act * 2, 0.5, 2);
    c.stroke();
  });

  // Draw nodes
  projected.forEach(node => {
    const size = node.baseSize * node.pscale * (1 + node.activation * 2);
    const alpha = 0.3 + node.activation * 0.7;

    // Glow
    if (node.activation > 0.3) {
      const gradient = c.createRadialGradient(node.px, node.py, 0, node.px, node.py, size * 3);
      gradient.addColorStop(0, `${node.color}40`);
      gradient.addColorStop(1, `${node.color}00`);
      c.fillStyle = gradient;
      c.beginPath();
      c.arc(node.px, node.py, size * 3, 0, Math.PI * 2);
      c.fill();
    }

    // Node body
    c.fillStyle = node.color;
    c.globalAlpha = alpha;
    c.beginPath();
    c.arc(node.px, node.py, Math.max(1.5, size), 0, Math.PI * 2);
    c.fill();
    c.globalAlpha = 1;
  });

  // Region labels
  const regions = [...new Set(projected.map(n => n.region))];
  c.font = '10px Space Grotesk';
  c.textAlign = 'center';
  regions.forEach(region => {
    const nodesInRegion = projected.filter(n => n.region === region);
    if (nodesInRegion.length === 0) return;
    const avgX = nodesInRegion.reduce((s, n) => s + n.px, 0) / nodesInRegion.length;
    const avgY = nodesInRegion.reduce((s, n) => s + n.py, 0) / nodesInRegion.length;
    const color = nodesInRegion[0].color;
    c.fillStyle = color;
    c.fillText(region, avgX, avgY - 20);
  });
}

// --- Decoded View (motor commands) ---
function drawDecodedView() {
  const canvas = els.decodedCanvas;
  const size = resizeCanvas(canvas);
  const { width, height } = size;
  const c = ctx.decoded;
  clearCanvas(c, width, height);

  const data = lastDecodedData;
  const centerX = width / 2;
  const centerY = height / 2;

  // Steering indicator (bilateral visual DN asymmetry)
  const turn = data.turn || 0;
  const visualL = data.visualL || 0;
  const visualR = data.visualR || 0;
  const visual = data.visual || 0;
  const looming = data.looming || 0;
  const objects = data.objects || 0;

  // Left/Right visual bars
  const barW = 60;
  const barH = 160;
  const leftX = centerX - 120;
  const rightX = centerX + 60;
  const barY = centerY + barH / 2;

  // Left visual DN
  drawVerticalBar(c, leftX, centerY - barH / 2, barW, barH, visualL, 30, '#c8f169', 'VISUAL L');
  // Right visual DN
  drawVerticalBar(c, rightX, centerY - barH / 2, barW, barH, visualR, 30, '#a8d149', 'VISUAL R');

  // Turn delta indicator (steering)
  const turnX = centerX;
  const turnY = centerY - barH / 2 - 40;
  c.fillStyle = '#5a6d64';
  c.font = '10px Space Grotesk';
  c.textAlign = 'center';
  c.fillText('STEERING Δ', turnX, turnY - 10);

  const turnWidth = clamp(Math.abs(turn) * 80, 0, 180);
  c.fillStyle = turn > 0 ? '#3ddbd9' : '#ff6b9d';
  c.fillRect(turnX - turnWidth / 2, turnY, turnWidth, 8);
  c.strokeStyle = '#1a252f';
  c.lineWidth = 1;
  c.strokeRect(turnX - 180 / 2, turnY, 180, 8);
  // Center line
  c.strokeStyle = '#5a6d64';
  c.beginPath();
  c.moveTo(turnX, turnY - 2);
  c.lineTo(turnX, turnY + 10);
  c.stroke();

  // Turn direction arrow
  c.fillStyle = turn > 0.05 ? '#3ddbd9' : (turn < -0.05 ? '#ff6b9d' : '#5a6d64');
  c.font = '24px JetBrains Mono';
  c.textAlign = 'center';
  c.fillText(turn > 0.05 ? '▶ RIGHT' : (turn < -0.05 ? '◀ LEFT' : '● CENTER'), turnX, turnY + 30);

  // Looming detector (fire trigger)
  const loomY = centerY + barH / 2 + 40;
  c.fillStyle = '#5a6d64';
  c.font = '10px Space Grotesk';
  c.textAlign = 'center';
  c.fillText('LOOMING DETECTOR → FIRE', centerX, loomY - 10);

  const loomWidth = clamp(looming * 40, 0, 200);
  const loomGradient = c.createLinearGradient(centerX - 100, 0, centerX + 100, 0);
  loomGradient.addColorStop(0, '#ff9f43');
  loomGradient.addColorStop(0.5, '#ff7843');
  loomGradient.addColorStop(1, '#ff4d43');
  c.fillStyle = loomGradient;
  c.fillRect(centerX - loomWidth / 2, loomY, loomWidth, 16);
  c.strokeStyle = '#1a252f';
  c.strokeRect(centerX - 100, loomY, 200, 16);

  // Fire indicator
  if (data.actions?.has('fire')) {
    c.fillStyle = '#ff4d43';
    c.font = 'bold 20px Space Grotesk';
    c.fillText('✦ FIRE ✦', centerX, loomY + 40);
    // Pulse effect
    const pulse = (Math.sin(now() * 0.01) + 1) * 0.5;
    c.strokeStyle = `rgba(255, 77, 67, ${0.5 + pulse * 0.5})`;
    c.lineWidth = 3;
    c.beginPath();
    c.arc(centerX, loomY + 8, 50 + pulse * 30, 0, Math.PI * 2);
    c.stroke();
  }

  // Object detector
  const objY = loomY + 60;
  c.fillStyle = '#5a6d64';
  c.font = '10px Space Grotesk';
  c.textAlign = 'center';
  c.fillText(`OBJECT DETECTOR: ${objects.toFixed(1)} Hz`, centerX, objY);

  // Active actions list
  if (data.actions && data.actions.size > 0) {
    c.fillStyle = '#c8f169';
    c.font = '11px Space Grotesk';
    c.textAlign = 'center';
    const activeActions = [...data.actions].join(' • ');
    c.fillText(activeActions.toUpperCase(), centerX, height - 30);
  }
}

function drawVerticalBar(ctx, x, y, w, h, value, maxValue, color, label) {
  const fillH = clamp((value / maxValue) * h, 0, h);
  const barX = x;
  const barY = y + h - fillH;

  // Background
  ctx.fillStyle = '#0a0f14';
  ctx.fillRect(barX, y, w, h);
  ctx.strokeStyle = '#1a252f';
  ctx.lineWidth = 1;
  ctx.strokeRect(barX, y, w, h);

  // Fill
  if (fillH > 0) {
    const grad = ctx.createLinearGradient(0, y + h, 0, y);
    grad.addColorStop(0, color);
    grad.addColorStop(1, `${color}40`);
    ctx.fillStyle = grad;
    ctx.fillRect(barX + 1, barY + 1, w - 2, fillH - 2);
  }

  // Label
  ctx.fillStyle = '#5a6d64';
  ctx.font = '9px Space Grotesk';
  ctx.textAlign = 'center';
  ctx.fillText(label, x + w / 2, y - 6);

  // Value
  ctx.fillStyle = color;
  ctx.font = '12px JetBrains Mono';
  ctx.textAlign = 'center';
  ctx.fillText(value.toFixed(1), x + w / 2, y + h + 18);
}

// ===== UI Controls =====
els.brainViewSelect.addEventListener('change', (e) => {
  const view = e.target.value;
  els.brainViews.forEach(v => {
    v.classList.toggle('active', v.dataset.view === view);
    v.hidden = v.dataset.view !== view;
  });
});

els.neuralPause.addEventListener('click', () => {
  paused = !paused;
  els.neuralPause.textContent = paused ? '▶' : '⏸';
  els.neuralPause.title = paused ? 'Resume' : 'Pause';
  els.modeBadge.textContent = paused ? 'PAUSED' : 'LIVE';
});

els.logToggle.addEventListener('click', () => {
  els.logPanel.classList.toggle('collapsed');
  els.logToggle.textContent = els.logPanel.classList.contains('collapsed') ? '⌃' : '⌄';
});

// Fullscreen handlers
function setupFullscreen(btnId, canvasId, title) {
  const btn = document.getElementById(btnId);
  if (!btn) return;
  btn.addEventListener('click', () => openFullscreen(canvasId, title));
}

function openFullscreen(canvasId, title) {
  const overlay = document.createElement('div');
  overlay.className = 'fullscreen-overlay';
  overlay.innerHTML = `
    <div class="fullscreen-header">
      <h2>${title}</h2>
      <button class="fullscreen-close" aria-label="Close">✕</button>
    </div>
    <div class="fullscreen-content">
      <canvas id="fs-${canvasId}"></canvas>
    </div>
  `;
  document.body.appendChild(overlay);

  const closeBtn = overlay.querySelector('.fullscreen-close');
  const fsCanvas = overlay.querySelector(`#fs-${canvasId}`);
  const fsCtx = fsCanvas.getContext('2d');

  function resize() {
    const dpr = window.devicePixelRatio || 1;
    fsCanvas.width = window.innerWidth * dpr;
    fsCanvas.height = window.innerHeight * dpr;
    fsCanvas.style.width = '100%';
    fsCanvas.style.height = '100%';
    fsCtx.scale(dpr, dpr);
  }
  resize();
  window.addEventListener('resize', resize);

  function close() {
    window.removeEventListener('resize', resize);
    overlay.classList.remove('active');
    setTimeout(() => overlay.remove(), 300);
  }
  closeBtn.addEventListener('click', close);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

  // Render loop
  let lastDraw = 0;
  function renderFullscreen(ts) {
    if (!overlay.isConnected) return;
    if (canvasId === 'neural-canvas') drawNeuralPanelFS(fsCtx, window.innerWidth, window.innerHeight);
    else if (canvasId === 'retinal-canvas') drawRetinalViewFS(fsCtx, window.innerWidth, window.innerHeight);
    else if (canvasId === 'connectome-canvas') drawConnectomeViewFS(fsCtx, window.innerWidth, window.innerHeight);
    else if (canvasId === 'decoded-canvas') drawDecodedViewFS(fsCtx, window.innerWidth, window.innerHeight);
    requestAnimationFrame(renderFullscreen);
  }

  requestAnimationFrame(renderFullscreen);
  // Force reflow for animation
  overlay.offsetHeight;
  overlay.classList.add('active');
}

// Fullscreen drawing functions (adapted for fullscreen)
function drawNeuralPanelFS(c, width, height) {
  c.fillStyle = '#05080c';
  c.fillRect(0, 0, width, height);
  // Simplified version - just scale up the regular draw
  const origCanvas = els.neuralCanvas;
  const origW = origCanvas.width / (window.devicePixelRatio || 1);
  const origH = origCanvas.height / (window.devicePixelRatio || 1);
  c.drawImage(origCanvas, 0, 0, origW, origH, 0, 0, width, height);
}

function drawRetinalViewFS(c, width, height) {
  c.fillStyle = '#05080c';
  c.fillRect(0, 0, width, height);
  const origCanvas = els.retinalCanvas;
  const origW = origCanvas.width / (window.devicePixelRatio || 1);
  const origH = origCanvas.height / (window.devicePixelRatio || 1);
  c.drawImage(origCanvas, 0, 0, origW, origH, 0, 0, width, height);
}

function drawConnectomeViewFS(c, width, height) {
  c.fillStyle = '#05080c';
  c.fillRect(0, 0, width, height);
  const origCanvas = els.connectomeCanvas;
  const origW = origCanvas.width / (window.devicePixelRatio || 1);
  const origH = origCanvas.height / (window.devicePixelRatio || 1);
  c.drawImage(origCanvas, 0, 0, origW, origH, 0, 0, width, height);
}

function drawDecodedViewFS(c, width, height) {
  c.fillStyle = '#05080c';
  c.fillRect(0, 0, width, height);
  const origCanvas = els.decodedCanvas;
  const origW = origCanvas.width / (window.devicePixelRatio || 1);
  const origH = origCanvas.height / (window.devicePixelRatio || 1);
  c.drawImage(origCanvas, 0, 0, origW, origH, 0, 0, width, height);
}

setupFullscreen('neural-fullscreen', 'neural-canvas', 'NEURAL POPULATION ACTIVITY');
setupFullscreen('brain-fullscreen', 'connectome-canvas', 'CONNECTOME ACTIVITY');
setupFullscreen('action-fullscreen', 'decoded-canvas', 'DECODED COMMANDS');

// ===== Initialization =====
function init() {
  resizeAllCanvases();

  // Build legend
  NEURON_POPS.forEach(pop => {
    const item = document.createElement('div');
    item.className = 'legend-item';
    item.innerHTML = `<span class="legend-swatch" style="background:${pop.color};"></span><span>${pop.label}</span>`;
    els.neuralLegend.appendChild(item);
  });

  // Initial draw
  drawAll();

  // Connect to server
  connect();

  // Periodic redraw for animations
  function animate() {
    drawRetinalView();
    drawConnectomeView();
    drawDecodedView();
    animationFrameId = requestAnimationFrame(animate);
  }
  animate();
}

// Start
init();

// Cleanup on unload
window.addEventListener('beforeunload', () => {
  if (ws) ws.close();
  if (reconnectTimer) clearTimeout(reconnectTimer);
  if (animationFrameId) cancelAnimationFrame(animationFrameId);
});