const WS_URL = `ws://${window.location.host}/ws`;
const AGENTS = ['hypothesis', 'data_engineer', 'quant_analyst', 'risk_auditor', 'strategy_writer'];
const AGENT_LABELS = {
  hypothesis: 'hypo', data_engineer: 'data', quant_analyst: 'quant',
  risk_auditor: 'risk', strategy_writer: 'writer'
};
const STAGE_ORDER = ['hypothesis', 'data_engineer', 'quant_analyst', 'risk_auditor', 'strategy_writer'];

const STATUS_ICON = {
  success: '✅',
  completed: '✅',
  running: '🔄',
  failed: '❌',
  consultation_needed: '⚠️',
  pending: '⏳',
  skipped: '⏳',
  unknown: '⏳'
};

const STATUS_CLASS = {
  success: 'success',
  completed: 'completed',
  running: 'running',
  failed: 'failed',
  consultation_needed: 'consultation_needed',
  pending: 'pending',
  skipped: 'skipped',
  unknown: 'unknown'
};

let state = { pipeline: {}, agents: {}, runs: [], logs: {} };
let selectedAgent = 'hypothesis';
let ws = null;
let reconnectDelay = 3000;
let reconnectTimer = null;
let pingTimer = null;
let lastLogRenderTime = 0;
let pendingLogCount = 0;

function init() {
  renderSkeleton();
  connectWS();
}

function renderSkeleton() {
  const app = document.getElementById('app');
  app.innerHTML = `
    <div class="header">
      <h1>Quant Cluster Monitor</h1>
      <div class="header-status">
        <span id="ws-status">Connecting…</span>
        <div id="ws-dot" class="ws-dot"></div>
      </div>
    </div>
    <div class="main">
      <aside class="sidebar">
        <div class="sidebar-section">
          <h3>Agents</h3>
          <div id="agent-list"></div>
        </div>
        <div class="sidebar-section">
          <h3>Data Router</h3>
          <div id="data-router"></div>
        </div>
        <div class="sidebar-section">
          <h3>Recent Runs</h3>
          <div id="run-list"></div>
        </div>
      </aside>
      <div class="content">
        <div class="content-header">
          <h2 id="pipeline-title">No active pipeline</h2>
        </div>
        <div class="content-body">
          <div class="pipeline-section">
            <h3>Pipeline Flow</h3>
            <div id="pipeline-flow" class="pipeline-flow"></div>
          </div>
          <div class="activity-section">
            <h3>Activity Feed</h3>
            <div id="activity-feed" class="activity-list"></div>
          </div>
          <div id="agent-detail"></div>
          <div class="log-stream" id="log-stream">
            <div class="log-header" id="log-header">
              <h3>Log Stream</h3>
              <span class="log-toggle">▼</span>
            </div>
            <div class="log-body" id="log-body"></div>
          </div>
        </div>
      </div>
    </div>
  `;

  document.getElementById('log-header').addEventListener('click', () => {
    document.getElementById('log-stream').classList.toggle('collapsed');
  });
}

function connectWS() {
  if (ws) {
    try { ws.close(); } catch (e) {}
  }

  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    updateWSStatus('connected');
    reconnectDelay = 3000;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    startPing();
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleMessage(msg);
    } catch (e) {
      console.error('Failed to parse WS message', e);
    }
  };

  ws.onclose = () => {
    updateWSStatus('disconnected');
    stopPing();
    scheduleReconnect();
  };

  ws.onerror = () => {
    updateWSStatus('disconnected');
  };
}

function updateWSStatus(status) {
  const label = document.getElementById('ws-status');
  const dot = document.getElementById('ws-dot');
  if (!label || !dot) return;
  if (status === 'connected') {
    label.textContent = 'Connected';
    dot.className = 'ws-dot connected';
  } else {
    label.textContent = 'Disconnected';
    dot.className = 'ws-dot disconnected';
  }
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectWS();
    reconnectDelay = Math.min(reconnectDelay * 2, 30000);
  }, reconnectDelay);
}

function startPing() {
  stopPing();
  pingTimer = setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'ping' }));
    }
  }, 10000);
}

function stopPing() {
  if (pingTimer) {
    clearInterval(pingTimer);
    pingTimer = null;
  }
}

function handleMessage(msg) {
  switch (msg.type) {
    case 'init':
      state.pipeline = msg.pipeline || {};
      state.agents = msg.agents || {};
      state.runs = msg.runs || [];
      renderAll();
      break;
    case 'pipeline':
      state.pipeline = { ...msg };
      delete state.pipeline.type;
      renderTitle();
      renderPipeline();
      break;
    case 'agent_task': {
      const agentName = msg.agent;
      const data = { ...msg };
      delete data.type;
      delete data.agent;
      state.agents[agentName] = { ...(state.agents[agentName] || {}), ...data };
      renderAgentList();
      renderDataRouter();
      if (selectedAgent === agentName) {
        renderAgentDetail();
      }
      break;
    }
    case 'agent_activity': {
      const aName = msg.agent;
      const logEvent = { ...msg };
      delete logEvent.type;
      delete logEvent.agent;
      if (!state.logs[aName]) state.logs[aName] = [];
      state.logs[aName].push(logEvent);
      if (state.logs[aName].length > 200) {
        state.logs[aName] = state.logs[aName].slice(-200);
      }
      maybeRenderLogs();
      renderActivity();
      if (selectedAgent === aName) {
        renderAgentDetail();
      }
      break;
    }
    case 'heartbeat':
      break;
    default:
      break;
  }
}

function maybeRenderLogs() {
  const now = Date.now();
  if (now - lastLogRenderTime > 1000) {
    pendingLogCount = 0;
    lastLogRenderTime = now;
    renderLogStream();
    return;
  }
  pendingLogCount++;
  if (pendingLogCount > 20) {
    renderLogStreamThrottle();
  } else {
    renderLogStream();
  }
}

function renderAll() {
  renderTitle();
  renderAgentList();
  renderDataRouter();
  renderRunList();
  renderPipeline();
  renderActivity();
  renderAgentDetail();
  renderLogStream();
}

function renderTitle() {
  const el = document.getElementById('pipeline-title');
  const topic = state.pipeline?.topic;
  if (topic) {
    el.textContent = topic;
  } else {
    el.textContent = 'No active pipeline';
  }
}

function renderAgentList() {
  const container = document.getElementById('agent-list');
  if (!container) return;
  container.innerHTML = AGENTS.map(agent => {
    const data = state.agents[agent] || {};
    const status = data.status || 'unknown';
    const cls = STATUS_CLASS[status] || 'unknown';
    const active = agent === selectedAgent ? 'active' : '';
    return `
      <div class="sidebar-item ${active}" data-agent="${agent}">
        <div class="status-dot ${cls}"></div>
        <span>${AGENT_LABELS[agent]}</span>
      </div>
    `;
  }).join('');

  container.querySelectorAll('.sidebar-item').forEach(item => {
    item.addEventListener('click', () => {
      selectAgent(item.dataset.agent);
    });
  });
}

function renderDataRouter() {
  const container = document.getElementById('data-router');
  if (!container) return;
  const dr = state.agents['data_router'] || {};
  const status = dr.status || 'unknown';
  const cls = STATUS_CLASS[status] || 'unknown';
  container.innerHTML = `
    <div class="sidebar-item">
      <div class="status-dot ${cls}"></div>
      <span>data_router</span>
    </div>
  `;
}

function renderRunList() {
  const container = document.getElementById('run-list');
  if (!container) return;
  if (!state.runs || state.runs.length === 0) {
    container.innerHTML = '<div class="empty">No recent runs</div>';
    return;
  }
  container.innerHTML = state.runs.slice(0, 10).map(run => {
    const topic = run.topic || run.run_id || 'Unknown';
    const status = run.status || 'unknown';
    const created = run.created_at ? run.created_at.replace('T', ' ').substring(0, 19) : '';
    return `
      <div class="run-item">
        <div class="run-topic" title="${escapeHtml(topic)}">${escapeHtml(topic)}</div>
        <div class="run-meta">${escapeHtml(status)} · ${escapeHtml(created)}</div>
      </div>
    `;
  }).join('');
}

function renderPipeline() {
  const container = document.getElementById('pipeline-flow');
  if (!container) return;

  const tasks = state.pipeline?.tasks || {};
  const cards = STAGE_ORDER.map((agent, idx) => {
    const status = tasks[agent]?.status || 'pending';
    const icon = STATUS_ICON[status] || STATUS_ICON.pending;
    const cls = STATUS_CLASS[status] || 'pending';
    const label = AGENT_LABELS[agent];
    const arrow = idx < STAGE_ORDER.length - 1 ? '<span class="stage-arrow">→</span>' : '';
    return `
      <div class="stage-card" data-agent="${agent}">
        <span class="stage-icon">${icon}</span>
        <span class="stage-label">${label}</span>
      </div>
      ${arrow}
    `;
  }).join('');

  container.innerHTML = cards;

  container.querySelectorAll('.stage-card').forEach(card => {
    card.addEventListener('click', () => {
      selectAgent(card.dataset.agent);
    });
  });
}

function renderActivity() {
  const container = document.getElementById('activity-feed');
  if (!container) return;

  const activities = [];
  Object.entries(state.logs).forEach(([agent, logs]) => {
    logs.forEach(log => {
      activities.push({ agent, ...log });
    });
  });

  activities.sort((a, b) => {
    const ta = a.timestamp || '';
    const tb = b.timestamp || '';
    return ta.localeCompare(tb);
  });

  const recent = activities.slice(-5);
  if (recent.length === 0) {
    container.innerHTML = '<div class="empty">No recent activity</div>';
    return;
  }

  container.innerHTML = recent.map(act => {
    const ts = act.timestamp ? act.timestamp.split(' ')[1]?.substring(0, 8) || act.timestamp : '';
    const msg = formatActivityMessage(act);
    return `
      <div class="activity-item">
        <span class="activity-time">${escapeHtml(ts)}</span>
        <span class="activity-agent">${escapeHtml(AGENT_LABELS[act.agent] || act.agent)}</span>
        <span class="activity-msg">${escapeHtml(msg)}</span>
      </div>
    `;
  }).join('');
}

function formatActivityMessage(act) {
  switch (act.activity) {
    case 'api_call':
      return `API call #${act.call_num} ${act.model} (${act.latency_sec}s)`;
    case 'tool_call':
      return `tool ${act.tool} (${act.duration_sec}s, ${act.output_chars} chars)`;
    case 'turn_start':
      return `turn start session=${act.session}`;
    case 'turn_end':
      return `turn end reason=${act.reason}`;
    case 'log':
      return act.raw || 'log event';
    default:
      return act.raw || JSON.stringify(act);
  }
}

function selectAgent(agent) {
  if (!AGENTS.includes(agent)) return;
  selectedAgent = agent;
  renderAgentList();
  renderAgentDetail();
  renderLogStream();
}

function renderAgentDetail() {
  const container = document.getElementById('agent-detail');
  if (!container) return;
  const data = state.agents[selectedAgent] || {};
  const logs = state.logs[selectedAgent] || [];
  const toolCalls = logs.filter(l => l.activity === 'tool_call').slice(-5);

  container.innerHTML = `
    <div class="agent-detail">
      <h3>${AGENT_LABELS[selectedAgent]} Detail</h3>
      <div class="detail-grid">
        <div class="detail-item">
          <div class="detail-label">Status</div>
          <div class="detail-value">${escapeHtml(data.status || 'unknown')}</div>
        </div>
        <div class="detail-item">
          <div class="detail-label">Health</div>
          <div class="detail-value">${escapeHtml(data.health || 'unknown')}</div>
        </div>
        <div class="detail-item">
          <div class="detail-label">Uptime</div>
          <div class="detail-value">${formatDuration(data.uptime_sec || 0)}</div>
        </div>
        <div class="detail-item">
          <div class="detail-label">Session</div>
          <div class="detail-value">${escapeHtml(data.session || '—')}</div>
        </div>
        <div class="detail-item">
          <div class="detail-label">Container</div>
          <div class="detail-value">${escapeHtml(data.container_name || '—')}</div>
        </div>
        <div class="detail-item">
          <div class="detail-label">Recent Tools</div>
          <div class="detail-value">${toolCalls.map(t => escapeHtml(t.tool)).join(', ') || '—'}</div>
        </div>
      </div>
    </div>
  `;
}

function renderLogLines(logs) {
  if (!logs || logs.length === 0) return '<div class="empty">No logs</div>';
  return logs.slice(-50).map(log => {
    const ts = log.timestamp ? log.timestamp.split(' ')[1]?.substring(0, 12) || log.timestamp : '';
    let msg = '';
    switch (log.activity) {
      case 'api_call':
        msg = `API call #${log.call_num} model=${log.model} in=${log.input_tokens} out=${log.output_tokens} latency=${log.latency_sec}s`;
        break;
      case 'tool_call':
        msg = `tool ${log.tool} completed (${log.duration_sec}s, ${log.output_chars} chars)`;
        break;
      case 'turn_start':
        msg = `conversation turn: session=${log.session} model=${log.model} history=${log.history_len}`;
        break;
      case 'turn_end':
        msg = `Turn ended: reason=${log.reason} api_calls=${log.api_calls} budget=${log.budget} tool_turns=${log.tool_turns}`;
        break;
      case 'log':
        msg = log.raw || '';
        break;
      default:
        msg = JSON.stringify(log);
    }
    return `<div class="log-line"><span class="log-ts">${escapeHtml(ts)}</span>${escapeHtml(msg)}</div>`;
  }).join('');
}

function renderLogStream() {
  const body = document.getElementById('log-body');
  if (!body) return;
  const logs = state.logs[selectedAgent] || [];
  body.innerHTML = renderLogLines(logs);
  body.scrollTop = body.scrollHeight;
}

function renderLogStreamThrottle() {
  const body = document.getElementById('log-body');
  if (!body) return;
  const notice = body.querySelector('.log-throttle-notice');
  if (notice) {
    notice.textContent = `+${pendingLogCount} events`;
  } else {
    body.insertAdjacentHTML('beforeend', `<div class="log-throttle-notice">+${pendingLogCount} events</div>`);
  }
  body.scrollTop = body.scrollHeight;
}

function formatDuration(sec) {
  if (!sec || sec < 0) return '0s';
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${s}s`;
}

function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

document.addEventListener('DOMContentLoaded', init);
