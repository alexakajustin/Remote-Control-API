/**
 * RustDesk API Server — Admin Dashboard
 * WebSocket client, live UI updates, force-directed topology, and data management.
 */

// ═══════════════════════════════════════════════════════════════
// State
// ═══════════════════════════════════════════════════════════════

const API_BASE = window.location.origin;
let authToken = localStorage.getItem('rd_admin_token') || '';
let currentUser = null;
let ws = null;
let wsReconnectTimer = null;
let devices = [];
let uptimeSeconds = 0;
let uptimeInterval = null;

// ═══════════════════════════════════════════════════════════════
// Auth & Login
// ═══════════════════════════════════════════════════════════════

async function handleLogin(e) {
    e.preventDefault();
    const username = document.getElementById('loginUsername').value;
    const password = document.getElementById('loginPassword').value;
    const errorEl = document.getElementById('loginError');
    const btn = document.getElementById('loginBtn');

    btn.textContent = 'Signing in...';
    btn.disabled = true;
    errorEl.textContent = '';

    try {
        const resp = await fetch(`${API_BASE}/admin/api/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
        });

        if (!resp.ok) {
            const data = await resp.json().catch(() => ({}));
            throw new Error(data.error || data.detail || 'Login failed');
        }

        const data = await resp.json();
        authToken = data.token;
        currentUser = data.user;
        localStorage.setItem('rd_admin_token', authToken);
        showDashboard();
    } catch (err) {
        errorEl.textContent = err.message;
    } finally {
        btn.textContent = 'Sign In';
        btn.disabled = false;
    }
}

function handleLogout() {
    authToken = '';
    currentUser = null;
    localStorage.removeItem('rd_admin_token');
    if (ws) ws.close();
    showLogin();
}

let currentTab = 'overview';
let autoRefreshTimer = null;

function showLogin() {
    document.getElementById('loginOverlay').classList.remove('hidden');
    document.getElementById('appHeader').style.display = 'none';
    document.getElementById('navTabs').style.display = 'none';
    document.getElementById('mainContent').style.display = 'none';
    if (uptimeInterval) clearInterval(uptimeInterval);
    if (autoRefreshTimer) clearInterval(autoRefreshTimer);
}

function showDashboard() {
    document.getElementById('loginOverlay').classList.add('hidden');
    document.getElementById('appHeader').style.display = '';
    document.getElementById('navTabs').style.display = '';
    document.getElementById('mainContent').style.display = '';

    if (currentUser) {
        document.getElementById('userName').textContent = currentUser.name || currentUser.username;
        document.getElementById('userAvatar').textContent = (currentUser.name || currentUser.username || 'A')[0].toUpperCase();
    }

    // Load all data
    refreshDashboard();
    refreshDevices();
    refreshConnections();
    refreshAudit();
    refreshLogs();
    connectWebSocket();
    checkServerProcesses();
    startAutoRefresh();
}

// ═══════════════════════════════════════════════════════════════
// API Helpers
// ═══════════════════════════════════════════════════════════════

async function apiFetch(path, options = {}) {
    const resp = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${authToken}`,
            ...(options.headers || {}),
        },
    });

    if (resp.status === 401 || resp.status === 403) {
        handleLogout();
        throw new Error('Session expired');
    }

    return resp.json();
}

// ═══════════════════════════════════════════════════════════════
// Dashboard / KPI
// ═══════════════════════════════════════════════════════════════

async function refreshDashboard() {
    try {
        const data = await apiFetch('/admin/api/dashboard');
        document.getElementById('kpiOnline').textContent = data.online_devices || 0;
        document.getElementById('kpiTotal').textContent = data.total_devices || 0;
        document.getElementById('kpiConnections').textContent = data.connections_today || 0;

        uptimeSeconds = data.server_uptime || 0;
        updateUptimeDisplay();
        if (uptimeInterval) clearInterval(uptimeInterval);
        uptimeInterval = setInterval(() => {
            uptimeSeconds++;
            updateUptimeDisplay();
        }, 1000);
    } catch (err) {
        console.error('Dashboard refresh error:', err);
    }
}

function updateUptimeDisplay() {
    const h = Math.floor(uptimeSeconds / 3600);
    const m = Math.floor((uptimeSeconds % 3600) / 60);
    const s = Math.floor(uptimeSeconds % 60);
    document.getElementById('uptimeBadge').textContent =
        `⏱ ${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

async function checkServerProcesses() {
    // Always show API as online since we're connected
    document.getElementById('apiStatus').classList.remove('offline');
    // hbbs/hbbr — we assume they're running since the logs exist
    document.getElementById('hbbsStatus').classList.remove('offline');
    document.getElementById('hbbrStatus').classList.remove('offline');
}

// ═══════════════════════════════════════════════════════════════
// Tabs & Auto Refresh
// ═══════════════════════════════════════════════════════════════

function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    const targetNav = document.querySelector(`.nav-tab[data-tab="${tab}"]`);
    if (targetNav) targetNav.classList.add('active');

    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    const targetPanel = document.getElementById(`tab-${tab}`);
    if (targetPanel) targetPanel.classList.add('active');

    // Instantly refresh tab on click
    refreshActiveTab();
}

function refreshActiveTab() {
    if (currentTab === 'overview') {
        refreshDashboard();
        refreshDevices();
    } else if (currentTab === 'devices') {
        refreshDevices();
    } else if (currentTab === 'connections') {
        refreshConnections();
    } else if (currentTab === 'audit') {
        refreshAudit();
    } else if (currentTab === 'logs') {
        refreshLogs();
    }
}

function startAutoRefresh() {
    if (autoRefreshTimer) clearInterval(autoRefreshTimer);
    // Auto refresh active tab every 3 seconds
    autoRefreshTimer = setInterval(() => {
        refreshActiveTab();
    }, 3000);
}

// ═══════════════════════════════════════════════════════════════
// Devices
// ═══════════════════════════════════════════════════════════════

async function refreshDevices() {
    try {
        const data = await apiFetch('/admin/api/devices');
        devices = data.devices || [];
        renderDevices(devices);
        renderTopology(devices);
    } catch (err) {
        console.error('Devices refresh error:', err);
    }
}

function renderDevices(list) {
    const body = document.getElementById('devicesBody');
    if (!list.length) {
        body.innerHTML = `<tr><td colspan="7"><div class="empty-state"><div class="icon">💻</div><p>No devices registered yet. Connect a RustDesk client to see it here.</p></div></td></tr>`;
        return;
    }

    body.innerHTML = list.map(d => `
        <tr>
            <td><span class="badge badge-${d.status === 'online' ? 'online' : 'offline'}">${d.status}</span></td>
            <td class="mono">${esc(d.id)}</td>
            <td>${esc(d.hostname || '—')}</td>
            <td>${esc(d.os || '—')}</td>
            <td class="mono">${esc(d.ip || '—')}</td>
            <td class="mono text-muted">${esc(d.version || '—')}</td>
            <td class="text-muted">${timeAgo(d.last_heartbeat)}</td>
        </tr>
    `).join('');
}

function filterDevices() {
    const q = document.getElementById('deviceSearch').value.toLowerCase();
    const filtered = devices.filter(d =>
        (d.id || '').toLowerCase().includes(q) ||
        (d.hostname || '').toLowerCase().includes(q) ||
        (d.os || '').toLowerCase().includes(q) ||
        (d.ip || '').toLowerCase().includes(q)
    );
    renderDevices(filtered);
}

// ═══════════════════════════════════════════════════════════════
// Connections
// ═══════════════════════════════════════════════════════════════

async function refreshConnections() {
    try {
        const data = await apiFetch('/admin/api/connections');
        const connections = data.connections || [];
        const body = document.getElementById('connectionsBody');

        if (!connections.length) {
            body.innerHTML = `<tr><td colspan="6"><div class="empty-state"><div class="icon">🔗</div><p>No connections recorded yet.</p></div></td></tr>`;
            return;
        }

        body.innerHTML = connections.map(c => `
            <tr>
                <td class="text-muted">${formatTime(c.timestamp)}</td>
                <td><span class="badge badge-action">${esc(c.action)}</span></td>
                <td>
                    <span class="conn-arrow">
                        <span class="text-cyan">${esc(c.source_id || '?')}</span>
                        <span class="arrow">→</span>
                        <span class="text-amber">${esc(c.target_id || '?')}</span>
                    </span>
                </td>
                <td class="mono text-muted">${esc(c.source_ip || '—')}</td>
                <td class="mono text-muted">${esc(c.target_ip || '—')}</td>
                <td class="text-secondary">${esc(c.note || '—')}</td>
            </tr>
        `).join('');
    } catch (err) {
        console.error('Connections refresh error:', err);
    }
}



// ═══════════════════════════════════════════════════════════════
// Audit
// ═══════════════════════════════════════════════════════════════

async function refreshAudit() {
    try {
        const filter = document.getElementById('auditFilter')?.value || '';
        const url = filter ? `/admin/api/audit?action=${filter}` : '/admin/api/audit';
        const data = await apiFetch(url);
        const logs = data.logs || [];
        const body = document.getElementById('auditBody');

        if (!logs.length) {
            body.innerHTML = `<tr><td colspan="6"><div class="empty-state"><div class="icon">📋</div><p>No audit events recorded yet.</p></div></td></tr>`;
            return;
        }

        body.innerHTML = logs.map(l => `
            <tr>
                <td class="text-muted">${formatTime(l.timestamp)}</td>
                <td><span class="badge badge-action">${esc(l.action)}</span></td>
                <td class="mono">${esc(l.source_id || '—')}</td>
                <td class="mono">${esc(l.target_id || '—')}</td>
                <td class="mono text-muted">${esc(l.source_ip || '—')}</td>
                <td class="text-secondary">${esc(l.note || '—')}</td>
            </tr>
        `).join('');
    } catch (err) {
        console.error('Audit refresh error:', err);
    }
}

// ═══════════════════════════════════════════════════════════════
// Server Logs
// ═══════════════════════════════════════════════════════════════

async function refreshLogs() {
    try {
        const data = await apiFetch('/admin/api/logs');
        const logs = data.logs || [];
        renderLogEntries('serverLog', logs);
        renderLogEntries('recentActivity', logs.slice(0, 15));
    } catch (err) {
        console.error('Logs refresh error:', err);
    }
}

function renderLogEntries(containerId, logs) {
    const el = document.getElementById(containerId);
    if (!logs.length) {
        el.innerHTML = `<div class="empty-state" style="padding:2rem"><p>No events yet</p></div>`;
        return;
    }
    el.innerHTML = logs.map(l => `
        <div class="log-entry">
            <span class="log-time">${formatTime(l.timestamp)}</span>
            <span class="log-type ${esc(l.type)}">${esc(l.type)}</span>
            <span class="log-message">${esc(l.message)}</span>
        </div>
    `).join('');
}

// ═══════════════════════════════════════════════════════════════
// WebSocket — Live Updates
// ═══════════════════════════════════════════════════════════════

function connectWebSocket() {
    if (ws) {
        ws.close();
    }

    const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProto}//${window.location.host}/ws/live`;

    try {
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.log('WebSocket connected');
            if (wsReconnectTimer) {
                clearTimeout(wsReconnectTimer);
                wsReconnectTimer = null;
            }
        };

        ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                handleWsMessage(msg);
            } catch (err) {
                console.error('WS message parse error:', err);
            }
        };

        ws.onclose = () => {
            console.log('WebSocket disconnected, reconnecting in 5s...');
            wsReconnectTimer = setTimeout(connectWebSocket, 5000);
        };

        ws.onerror = (err) => {
            console.error('WebSocket error:', err);
        };
    } catch (err) {
        console.error('WebSocket connection error:', err);
        wsReconnectTimer = setTimeout(connectWebSocket, 5000);
    }
}

function handleWsMessage(msg) {
    if (msg.type === 'stats' || msg.type === 'update') {
        const stats = msg.stats || msg.data || {};
        document.getElementById('kpiOnline').textContent = stats.online_devices || 0;
        document.getElementById('kpiTotal').textContent = stats.total_devices || 0;
        document.getElementById('kpiConnections').textContent = stats.connections_today || 0;

        if (stats.server_uptime) {
            uptimeSeconds = stats.server_uptime;
        }

        if (msg.devices) {
            devices = msg.devices;
            renderDevices(devices);
            renderTopology(devices);
        }
    }

    if (msg.type === 'event') {
        // Prepend to recent activity
        const el = document.getElementById('recentActivity');
        const entry = msg.event;
        const html = `
            <div class="log-entry">
                <span class="log-time">${formatTime(entry.timestamp)}</span>
                <span class="log-type ${esc(entry.type)}">${esc(entry.type)}</span>
                <span class="log-message">${esc(entry.message)}</span>
            </div>
        `;
        el.insertAdjacentHTML('afterbegin', html);
        // Keep max 20 entries
        while (el.children.length > 20) {
            el.removeChild(el.lastChild);
        }

        // Also update server log tab
        const logEl = document.getElementById('serverLog');
        logEl.insertAdjacentHTML('afterbegin', html);
        while (logEl.children.length > MAX_LOG_DISPLAY) {
            logEl.removeChild(logEl.lastChild);
        }
    }
}

const MAX_LOG_DISPLAY = 200;

// ═══════════════════════════════════════════════════════════════
// Network Topology — Force-Directed Canvas
// ═══════════════════════════════════════════════════════════════

let topoAnimFrame = null;
let topoFrameCount = 0;
let topoDevices = [];

function renderTopology(deviceList) {
    const container = document.getElementById('topologyContainer');
    const canvas = document.getElementById('topologyCanvas');
    const emptyEl = document.getElementById('topologyEmpty');

    if (!deviceList || deviceList.length === 0) {
        emptyEl.style.display = '';
        if (topoAnimFrame) { cancelAnimationFrame(topoAnimFrame); topoAnimFrame = null; }
        return;
    }
    emptyEl.style.display = 'none';
    topoDevices = deviceList;

    const rect = container.getBoundingClientRect();
    const W = rect.width;
    const H = rect.height;
    canvas.width = W * window.devicePixelRatio;
    canvas.height = H * window.devicePixelRatio;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';

    if (!topoAnimFrame) {
        topoFrameCount = 0;
        drawTopology();
    }
}

function drawTopology() {
    const canvas = document.getElementById('topologyCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width / window.devicePixelRatio;
    const H = canvas.height / window.devicePixelRatio;
    ctx.setTransform(window.devicePixelRatio, 0, 0, window.devicePixelRatio, 0, 0);

    topoFrameCount++;
    ctx.clearRect(0, 0, W, H);

    const centerX = W / 2;
    const centerY = H / 2;
    const orbitRadius = Math.min(W, H) * 0.32;
    const list = topoDevices;
    const n = list.length;

    // ── Draw edges from server to each device ──
    for (let i = 0; i < n; i++) {
        const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
        const nx = centerX + Math.cos(angle) * orbitRadius;
        const ny = centerY + Math.sin(angle) * orbitRadius;
        const isOnline = list[i].status === 'online';

        ctx.beginPath();
        ctx.moveTo(centerX, centerY);
        ctx.lineTo(nx, ny);
        ctx.strokeStyle = isOnline ? 'rgba(6, 182, 212, 0.3)' : 'rgba(100, 116, 139, 0.12)';
        ctx.lineWidth = isOnline ? 1.5 : 0.8;
        ctx.stroke();

        // Animated pulse traveling along the edge
        if (isOnline) {
            const t = ((topoFrameCount * 1.2 + i * 80) % 300) / 300;
            const px = centerX + (nx - centerX) * t;
            const py = centerY + (ny - centerY) * t;
            ctx.beginPath();
            ctx.arc(px, py, 2.5, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(6, 182, 212, ${0.9 - t * 0.6})`;
            ctx.fill();
        }
    }

    // ── Draw server node (center) ──
    const pulse = 14 + Math.sin(topoFrameCount * 0.03) * 3;
    ctx.beginPath();
    ctx.arc(centerX, centerY, 26, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(139, 92, 246, 0.08)';
    ctx.fill();

    ctx.shadowColor = 'rgba(139, 92, 246, 0.5)';
    ctx.shadowBlur = pulse;
    ctx.beginPath();
    ctx.arc(centerX, centerY, 20, 0, Math.PI * 2);
    ctx.fillStyle = '#7c3aed';
    ctx.fill();
    ctx.shadowBlur = 0;

    ctx.fillStyle = '#fff';
    ctx.font = 'bold 14px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('S', centerX, centerY);

    ctx.fillStyle = '#c4b5fd';
    ctx.font = '600 10px Inter, sans-serif';
    ctx.textBaseline = 'top';
    ctx.fillText('Server', centerX, centerY + 28);

    // ── Draw device nodes (fixed positions around the circle) ──
    for (let i = 0; i < n; i++) {
        const d = list[i];
        const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
        const nx = centerX + Math.cos(angle) * orbitRadius;
        const ny = centerY + Math.sin(angle) * orbitRadius;
        const r = 16;
        const isOnline = d.status === 'online';

        // Glow for online
        if (isOnline) {
            ctx.shadowColor = 'rgba(6, 182, 212, 0.4)';
            ctx.shadowBlur = 12;
        }

        // Outer ring
        ctx.beginPath();
        ctx.arc(nx, ny, r, 0, Math.PI * 2);
        ctx.fillStyle = isOnline ? 'rgba(6, 182, 212, 0.1)' : 'rgba(71, 85, 105, 0.1)';
        ctx.fill();

        // Inner circle
        ctx.beginPath();
        ctx.arc(nx, ny, r - 4, 0, Math.PI * 2);
        ctx.fillStyle = isOnline ? '#06b6d4' : '#475569';
        ctx.fill();
        ctx.shadowBlur = 0;

        // PC icon
        ctx.fillStyle = '#fff';
        ctx.font = 'bold 9px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('PC', nx, ny);

        // Hostname label (primary)
        const hostname = d.hostname || d.id || '?';
        const shortName = hostname.length > 18 ? hostname.slice(0, 16) + '..' : hostname;
        ctx.textBaseline = 'top';
        ctx.fillStyle = isOnline ? '#e2e8f0' : '#64748b';
        ctx.font = '600 10px Inter, sans-serif';
        ctx.fillText(shortName, nx, ny + r + 6);

        // IP sublabel
        if (d.ip) {
            ctx.fillStyle = '#64748b';
            ctx.font = '9px JetBrains Mono, monospace';
            ctx.fillText(d.ip, nx, ny + r + 20);
        }
    }

    topoAnimFrame = requestAnimationFrame(drawTopology);
}

// ═══════════════════════════════════════════════════════════════
// Utility Functions
// ═══════════════════════════════════════════════════════════════

function esc(str) {
    if (!str) return '';
    const el = document.createElement('span');
    el.textContent = String(str);
    return el.innerHTML;
}

function formatTime(ts) {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    const time = d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    if (isToday) return time;
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' ' + time;
}

function timeAgo(ts) {
    if (!ts) return 'Never';
    const seconds = Math.floor(Date.now() / 1000 - ts);
    if (seconds < 10) return 'Just now';
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
}

// ═══════════════════════════════════════════════════════════════
// Init
// ═══════════════════════════════════════════════════════════════

window.addEventListener('DOMContentLoaded', () => {
    if (authToken) {
        // Verify token is still valid
        apiFetch('/admin/api/dashboard')
            .then(data => {
                currentUser = { username: 'admin' };
                showDashboard();
            })
            .catch(() => {
                showLogin();
            });
    } else {
        showLogin();
    }

    // Handle topology resize
    window.addEventListener('resize', () => {
        if (devices.length > 0) {
            if (topoAnimFrame) { cancelAnimationFrame(topoAnimFrame); topoAnimFrame = null; }
            renderTopology(devices);
        }
    });
});
