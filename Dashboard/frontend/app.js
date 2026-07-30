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
    refreshEndpoints();
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
        
        if (stats.server_uptime) {
            uptimeSeconds = stats.server_uptime;
        }

        if (msg.devices) {
            devices = msg.devices;
            renderDevices(devices);
        }



        if (msg.endpoints) {
            allDevices = msg.endpoints;
            renderEndpoints(msg.endpoints);
        }
        if (msg.active_conns) {
            renderActiveConnections(msg.active_conns);
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
        if (logEl) {
            logEl.insertAdjacentHTML('afterbegin', html);
            while (logEl.children.length > MAX_LOG_DISPLAY) {
                logEl.removeChild(logEl.lastChild);
            }
        }
    }
}

const MAX_LOG_DISPLAY = 200;

// ═══════════════════════════════════════════════════════════════
// Endpoints Management
// ═══════════════════════════════════════════════════════════════

let allDevices = [];

async function refreshEndpoints() {
    try {
        const data = await apiFetch('/admin/api/endpoints');
        if (data.endpoints) {
            allDevices = data.endpoints;
            renderEndpoints(allDevices);
        }
        if (data.active_conns) {
            renderActiveConnections(data.active_conns);
        }
    } catch (err) {
        console.error('Endpoints refresh error:', err);
    }
}

function renderActiveConnections(conns) {
    const body = document.getElementById('activeConnectionsBody');
    if (!conns || !conns.length) {
        body.innerHTML = `<tr><td colspan="3"><div class="empty-state"><div class="icon">🔌</div><p>No active connections right now.</p></div></td></tr>`;
        return;
    }

    const typeMap = {"0": "Desktop", "1": "File Transfer", "2": "RDP", "3": "Direct IP", "4": "RDP"};

    body.innerHTML = conns.map(c => {
        const sourceName = allDevices.find(d => d.id === c.source_id)?.hostname || c.source_id;
        const targetName = allDevices.find(d => d.id === c.target_id)?.hostname || c.target_id;
        const mode = typeMap[c.note] || c.note || "Session";
        
        return `
            <tr>
                <td><strong>${esc(sourceName)}</strong> <span class="mono text-muted">(${esc(c.source_id)})</span></td>
                <td><strong>${esc(targetName)}</strong> <span class="mono text-muted">(${esc(c.target_id)})</span></td>
                <td><span class="badge badge-action">${esc(mode)}</span></td>
            </tr>
        `;
    }).join('');
}

function renderEndpoints(endpoints) {
    const body = document.getElementById('endpointsBody');
    if (!endpoints || !endpoints.length) {
        body.innerHTML = `<tr><td colspan="5"><div class="empty-state"><div class="icon">📖</div><p>No devices connected yet.</p></div></td></tr>`;
        return;
    }

    body.innerHTML = endpoints.map(ep => {
        let rustdeskBadge = ep.status === 'online'
            ? '<span class="badge badge-online">RustDesk Online</span>'
            : '<span class="badge badge-offline">RustDesk Offline</span>';

        let pingBadge = '';
        if (ep.check_ping !== 0) {
            if (ep.status_ping === 'online') {
                pingBadge = '<span class="badge badge-online">Ping OK</span>';
            } else if (ep.status_ping === 'offline') {
                pingBadge = '<span class="badge badge-busy">Ping Fail</span>';
            } else {
                pingBadge = '<span class="badge badge-offline">Ping Checking...</span>';
            }
        }

        let rdpBadge = '';
        if (ep.check_rdp) {
            if (ep.status_rdp === 'online') {
                rdpBadge = `<span class="badge badge-online" style="border-color: rgba(6, 182, 212, 0.4); color: var(--accent-cyan);">RDP :${ep.rdp_port || 3389} Open</span>`;
            } else if (ep.status_rdp === 'offline') {
                rdpBadge = `<span class="badge badge-offline">RDP :${ep.rdp_port || 3389} Down</span>`;
            }
        }

        let busyBadge = '';
        if (ep.connected_to) {
            const targetLabel = ep.connected_to_name && ep.connected_to_name !== ep.connected_to ? `${ep.connected_to} (${ep.connected_to_name})` : ep.connected_to;
            const mode = ep.connected_to_type ? ` [${ep.connected_to_type}]` : '';
            busyBadge = `<span class="badge badge-busy">Controlling ${targetLabel}${mode}</span>`;
        } else if (ep.connected_from) {
            const sourceLabel = ep.connected_from_name && ep.connected_from_name !== ep.connected_from ? `${ep.connected_from} (${ep.connected_from_name})` : ep.connected_from;
            const mode = ep.connected_from_type ? ` [${ep.connected_from_type}]` : '';
            busyBadge = `<span class="badge badge-busy">Controlled by ${sourceLabel}${mode}</span>`;
        }

        const displayName = ep.custom_name ? ep.custom_name : (ep.hostname || 'localhost');

        return `
            <tr>
                <td><div style="display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;">${rustdeskBadge}${pingBadge}${rdpBadge}${busyBadge}</div></td>
                <td><strong>${esc(displayName)}</strong></td>
                <td class="mono">${esc(ep.id || '—')} 
                    ${ep.id ? `<button class="btn btn-sm" style="padding: 2px 6px" onclick="navigator.clipboard.writeText('${ep.id}')">Copy</button>` : ''}
                </td>
                <td class="mono">${esc(ep.ip || '—')} ${ep.check_rdp ? `(:${ep.rdp_port})` : ''}</td>
                <td class="text-right">
                    <button class="btn btn-sm btn-secondary" onclick="openEndpointModal('${ep.id}')">Edit</button>
                </td>
            </tr>
        `;
    }).join('');
}

function openEndpointModal(deviceId) {
    const ep = allDevices.find(d => d.id === deviceId);
    if (!ep) return;
    
    document.getElementById('epDeviceId').value = ep.id;
    document.getElementById('epName').value = ep.custom_name || '';
    document.getElementById('epCheckPing').checked = !!ep.check_ping;
    document.getElementById('epCheckRdp').checked = !!ep.check_rdp;
    document.getElementById('epRdpPort').value = ep.rdp_port || 3389;
    
    document.getElementById('endpointModal').style.display = 'flex';
}

function closeEndpointModal() {
    document.getElementById('endpointModal').style.display = 'none';
    document.getElementById('endpointForm').reset();
}

async function handleEndpointSubmit(e) {
    e.preventDefault();
    const deviceId = document.getElementById('epDeviceId').value;
    const payload = {
        custom_name: document.getElementById('epName').value,
        check_ping: document.getElementById('epCheckPing').checked,
        check_rdp: document.getElementById('epCheckRdp').checked,
        rdp_port: parseInt(document.getElementById('epRdpPort').value) || 3389
    };
    try {
        await apiFetch(`/admin/api/endpoints/${deviceId}`, {
            method: 'POST',
            body: JSON.stringify(payload)
        });
        closeEndpointModal();
        refreshEndpoints();
    } catch (err) {
        alert('Error saving monitoring settings: ' + err.message);
    }
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

        }
    });
});
