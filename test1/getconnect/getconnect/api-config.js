/**
 * GetConnect.Web - API Configuration & Helper Module
 * Connects frontend to the FastAPI backend
 */

const API_CONFIG = {
    // Change this to your backend URL (default: localhost:8000)
    BASE_URL: window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
        ? `http://${window.location.hostname}:8000`
        : window.location.origin,
    API_PREFIX: '/api/v1',
    WS_PREFIX: '/ws',
};

// Build full API URL
function apiUrl(path) {
    return `${API_CONFIG.BASE_URL}${API_CONFIG.API_PREFIX}${path}`;
}

// Build WebSocket URL
function wsUrl(path) {
    const protocol = API_CONFIG.BASE_URL.startsWith('https') ? 'wss' : 'ws';
    const host = API_CONFIG.BASE_URL.replace(/^https?:\/\//, '');
    return `${protocol}://${host}${API_CONFIG.WS_PREFIX}${path}`;
}

// Generic fetch wrapper with error handling
async function apiFetch(path, options = {}) {
    const url = apiUrl(path);
    const token = localStorage.getItem('auth_token');

    const headers = {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        ...(options.headers || {}),
    };

    try {
        const response = await fetch(url, {
            ...options,
            headers,
        });

        const data = await response.json();

        if (!response.ok) {
            throw { status: response.status, detail: data.detail || 'Request failed' };
        }

        return data;
    } catch (err) {
        if (err.status) throw err;
        console.warn(`API request failed: ${url}`, err);
        throw { status: 0, detail: 'Cannot connect to backend. Is the server running?' };
    }
}

// ===== AUTH HELPERS =====

async function apiLogin(email, password) {
    const data = await apiFetch('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
    });
    if (data.token) {
        localStorage.setItem('auth_token', data.token);
        localStorage.setItem('user_name', data.user.name);
        localStorage.setItem('user_email', data.user.email);
    }
    return data;
}

async function apiRegister(name, email, password) {
    return await apiFetch('/auth/register', {
        method: 'POST',
        body: JSON.stringify({ name, email, password }),
    });
}

function apiLogout() {
    localStorage.removeItem('auth_token');
    localStorage.removeItem('user_name');
    localStorage.removeItem('user_email');
    window.location.href = 'login.html';
}

function isLoggedIn() {
    return !!localStorage.getItem('auth_token');
}

function getCurrentUser() {
    return {
        name: localStorage.getItem('user_name') || 'Guest',
        email: localStorage.getItem('user_email') || '',
    };
}

// ===== CLUSTER / DASHBOARD HELPERS =====

async function apiGetClusterStatus() {
    return await apiFetch('/cluster/status');
}

async function apiGetDisplayStatus() {
    return await apiFetch('/display/status');
}

async function apiHealthCheck() {
    return await apiFetch('/health');
}

// ===== TASK HELPERS =====

async function apiGetTasks() {
    return await apiFetch('/tasks');
}

async function apiCreateTask(taskData) {
    return await apiFetch('/tasks', {
        method: 'POST',
        body: JSON.stringify(taskData),
    });
}

async function apiGetTask(taskId) {
    return await apiFetch(`/tasks/${taskId}`);
}

async function apiCancelTask(taskId) {
    return await apiFetch(`/tasks/${taskId}`, {
        method: 'DELETE',
    });
}

// ===== NODE HELPERS =====

async function apiGetNodes() {
    return await apiFetch('/nodes');
}

async function apiDrainNode(nodeId) {
    return await apiFetch(`/control/drain/${nodeId}`, {
        method: 'POST',
    });
}

// ===== CONTACT HELPER =====

async function apiSubmitContact(name, email, subject, message) {
    return await apiFetch('/contact', {
        method: 'POST',
        body: JSON.stringify({ name, email, subject, message }),
    });
}

// ===== WEBSOCKET HELPERS =====

function connectMetricsWS(onMessage) {
    const url = wsUrl('/metrics');
    let ws = null;
    let reconnectTimer = null;

    function connect() {
        ws = new WebSocket(url);

        ws.onopen = () => {
            console.log('WebSocket connected:', url);
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                onMessage(data);
            } catch (e) {
                console.warn('WS parse error:', e);
            }
        };

        ws.onclose = () => {
            console.log('WebSocket disconnected, reconnecting in 3s...');
            reconnectTimer = setTimeout(connect, 3000);
        };

        ws.onerror = (err) => {
            console.warn('WebSocket error:', err);
            ws.close();
        };
    }

    connect();

    return {
        close() {
            if (reconnectTimer) clearTimeout(reconnectTimer);
            if (ws) ws.close();
        }
    };
}

function connectTaskWS(taskId, onMessage) {
    const url = wsUrl(`/tasks/${taskId}`);
    const ws = new WebSocket(url);

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            onMessage(data);
        } catch (e) {
            console.warn('WS parse error:', e);
        }
    };

    ws.onerror = (err) => {
        console.warn('Task WS error:', err);
    };

    return ws;
}

// ===== CONNECTION STATUS BANNER =====

function showConnectionStatus() {
    // Create a small status indicator
    const statusDiv = document.createElement('div');
    statusDiv.id = 'api-status-banner';
    statusDiv.style.cssText = `
        position: fixed; bottom: 16px; right: 16px; z-index: 9999;
        padding: 8px 16px; border-radius: 8px; font-size: 0.85rem;
        font-family: 'Inter', sans-serif; display: flex; align-items: center; gap: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15); transition: all 0.3s ease;
    `;

    async function checkConnection() {
        try {
            await apiHealthCheck();
            statusDiv.style.background = '#10b981';
            statusDiv.style.color = 'white';
            statusDiv.innerHTML = '<i class="fas fa-plug" style="font-size:0.9em"></i> Backend Connected';
            setTimeout(() => { statusDiv.style.opacity = '0.6'; }, 3000);
        } catch (e) {
            statusDiv.style.background = '#ef4444';
            statusDiv.style.color = 'white';
            statusDiv.style.opacity = '1';
            statusDiv.innerHTML = '<i class="fas fa-exclamation-triangle" style="font-size:0.9em"></i> Backend Offline';
        }
    }

    document.body.appendChild(statusDiv);
    checkConnection();
    setInterval(checkConnection, 15000);
}

// Auto-show connection status on dashboard/tasks/analytics pages
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        const page = window.location.pathname;
        if (page.includes('dashboard') || page.includes('tasks') || page.includes('analytics')) {
            showConnectionStatus();
        }
    });
} else {
    const page = window.location.pathname;
    if (page.includes('dashboard') || page.includes('tasks') || page.includes('analytics')) {
        showConnectionStatus();
    }
}
