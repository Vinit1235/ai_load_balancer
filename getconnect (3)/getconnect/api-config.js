/**
 * GetConnect.Web — API Configuration & Helper Module
 * Connects frontend to the FastAPI backend running on port 8000
 */

const API_CONFIG = {
    BASE_URL: (() => {
        const host = window.location.hostname;
        const isFileProtocol = window.location.protocol === 'file:';
        const invalidOrigin = !window.location.origin || window.location.origin === 'null';
        if (isFileProtocol || invalidOrigin) {
            return 'http://127.0.0.1:8000';
        }
        if (host === 'localhost' || host === '127.0.0.1') {
            return `http://${host}:8000`;
        }
        return window.location.origin;
    })(),
    API_PREFIX: '/api/v1',
    WS_PREFIX: '/ws',
};

function apiUrl(path) {
    return `${API_CONFIG.BASE_URL}${API_CONFIG.API_PREFIX}${path}`;
}

function wsUrl(path) {
    const protocol = API_CONFIG.BASE_URL.startsWith('https') ? 'wss' : 'ws';
    const host = API_CONFIG.BASE_URL.replace(/^https?:\/\//, '');
    return `${protocol}://${host}${API_CONFIG.WS_PREFIX}${path}`;
}

async function apiFetch(path, options = {}) {
    const url = apiUrl(path);
    const token = localStorage.getItem('auth_token');
    const headers = {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        ...(options.headers || {}),
    };
    try {
        const response = await fetch(url, { ...options, headers });
        const data = await response.json();
        if (!response.ok) throw { status: response.status, detail: data.detail || 'Request failed' };
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
        // Also keep session key for legacy compatibility
        sessionStorage.setItem('userEmail', data.user.email);
        syncAuthNavigation();
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
    sessionStorage.removeItem('userEmail');
    syncAuthNavigation();
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

function syncAuthNavigation() {
    const loggedIn = isLoggedIn();
    const user = getCurrentUser();

    document.querySelectorAll('.nav-actions').forEach((actions) => {
        const loginControls = actions.querySelectorAll('a[href="login.html"], .btn-login, .btn-login-header');
        const registerControls = actions.querySelectorAll('a[href="register.html"], .btn-register, .btn-register-nav');
        const logoutControls = actions.querySelectorAll('#logoutBtn, [data-auth-logout="true"]');
        let authWidget = actions.querySelector('[data-auth-widget="true"]');

        if (loggedIn) {
            loginControls.forEach((control) => {
                control.style.display = 'none';
            });
            registerControls.forEach((control) => {
                control.style.display = 'none';
            });

            if (!authWidget) {
                authWidget = document.createElement('button');
                authWidget.type = 'button';
                authWidget.dataset.authWidget = 'true';
                authWidget.style.cssText = 'display:flex;align-items:center;gap:8px;padding:8px 14px;border-radius:999px;border:1px solid rgba(192,132,252,0.35);background:rgba(15,23,42,0.75);color:#e2e8ff;font:600 0.9rem Inter,sans-serif;cursor:pointer;';
                authWidget.innerHTML = `<i class="fas fa-user-circle"></i><span>${user.name || 'Account'}</span>`;
                authWidget.addEventListener('click', () => {
                    window.location.href = 'dashboard.html';
                });

                const mobileToggle = actions.querySelector('.mobile-toggle');
                if (mobileToggle) {
                    actions.insertBefore(authWidget, mobileToggle);
                } else {
                    actions.appendChild(authWidget);
                }
            } else {
                const label = authWidget.querySelector('span');
                if (label) {
                    label.textContent = user.name || 'Account';
                }
            }

            logoutControls.forEach((control) => {
                control.style.display = '';
                if (!control.dataset.authLogoutBound) {
                    control.addEventListener('click', apiLogout);
                    control.dataset.authLogoutBound = 'true';
                }
            });

            if (!logoutControls.length) {
                const logoutButton = document.createElement('button');
                logoutButton.type = 'button';
                logoutButton.dataset.authLogout = 'true';
                logoutButton.style.cssText = 'display:flex;align-items:center;gap:8px;padding:8px 14px;border-radius:999px;border:1px solid rgba(239,68,68,0.35);background:rgba(127,29,29,0.25);color:#fecaca;font:600 0.9rem Inter,sans-serif;cursor:pointer;';
                logoutButton.innerHTML = '<i class="fas fa-right-from-bracket"></i><span>Logout</span>';
                logoutButton.addEventListener('click', apiLogout);

                const mobileToggle = actions.querySelector('.mobile-toggle');
                if (mobileToggle) {
                    actions.insertBefore(logoutButton, mobileToggle);
                } else {
                    actions.appendChild(logoutButton);
                }
            }
        } else {
            loginControls.forEach((control) => {
                control.style.display = '';
                if (control.tagName === 'BUTTON') {
                    control.innerHTML = '<i class="fas fa-sign-in-alt"></i> Login';
                    if (!control.dataset.authLoginBound) {
                        control.addEventListener('click', () => {
                            window.location.href = 'login.html';
                        });
                        control.dataset.authLoginBound = 'true';
                    }
                }
            });

            registerControls.forEach((control) => {
                control.style.display = '';
                if (control.tagName === 'BUTTON') {
                    control.innerHTML = '<i class="fas fa-user-plus"></i> Register';
                    if (!control.dataset.authRegisterBound) {
                        control.addEventListener('click', () => {
                            window.location.href = 'register.html';
                        });
                        control.dataset.authRegisterBound = 'true';
                    }
                }
            });

            logoutControls.forEach((control) => {
                control.style.display = 'none';
            });

            authWidget?.remove();
        }
    });
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
    return await apiFetch(`/tasks/${taskId}/cancel`, { method: 'POST' });
}

async function apiDeleteTask(taskId) {
    return await apiFetch(`/tasks/${taskId}`, { method: 'DELETE' });
}

// ===== NODE HELPERS =====

async function apiGetNodes() {
    return await apiFetch('/nodes');
}

async function apiGetSchedulerStatus() {
    return await apiFetch('/scheduler/status');
}

async function apiDrainNode(nodeId) {
    return await apiFetch(`/control/drain/${nodeId}`, { method: 'POST' });
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
        ws.onopen = () => console.log('WebSocket connected:', url);
        ws.onmessage = (event) => {
            try { onMessage(JSON.parse(event.data)); } catch (e) { console.warn('WS parse error:', e); }
        };
        ws.onclose = () => {
            console.log('WebSocket disconnected, reconnecting in 3s...');
            reconnectTimer = setTimeout(connect, 3000);
        };
        ws.onerror = (err) => { console.warn('WebSocket error:', err); ws.close(); };
    }

    connect();
    return { close() { if (reconnectTimer) clearTimeout(reconnectTimer); if (ws) ws.close(); } };
}

// ===== AUTH GUARD =====

/**
 * Redirect to login if user is not authenticated.
 * Call on any page that requires login.
 */
function requireAuth() {
    if (!isLoggedIn()) {
        window.location.href = 'login.html';
        return false;
    }
    return true;
}

// ===== CONNECTION STATUS BANNER =====

function showConnectionStatus() {
    let statusDiv = document.getElementById('api-status-banner');
    if (!statusDiv) {
        statusDiv = document.createElement('div');
        statusDiv.id = 'api-status-banner';
        statusDiv.style.cssText = `
            position:fixed;bottom:16px;right:16px;z-index:9999;
            padding:8px 16px;border-radius:40px;font-size:.82rem;
            font-family:'Inter',sans-serif;display:flex;align-items:center;gap:8px;
            box-shadow:0 4px 20px rgba(0,0,0,0.4);transition:all .3s ease;
            backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,0.1);
        `;
        document.body.appendChild(statusDiv);
    }

    async function check() {
        try {
            await apiHealthCheck();
            statusDiv.style.background = 'rgba(16,185,129,0.85)';
            statusDiv.style.color = '#fff';
            statusDiv.innerHTML = '<i class="fas fa-plug" style="font-size:.85em"></i> Backend Connected';
            setTimeout(() => { statusDiv.style.opacity = '0.55'; }, 3000);
        } catch {
            statusDiv.style.background = 'rgba(239,68,68,0.9)';
            statusDiv.style.color = '#fff';
            statusDiv.style.opacity = '1';
            statusDiv.innerHTML = '<i class="fas fa-exclamation-triangle" style="font-size:.85em"></i> Backend Offline';
        }
    }

    check();
    setInterval(check, 15000);
}

// Auto-show connection status on key pages + enforce auth guards
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApiConfig);
} else {
    initApiConfig();
}

function initApiConfig() {
    const page = window.location.pathname;
    const protectedPages = ['dashboard', 'tasks', 'analytics'];
    const isProtected = protectedPages.some(p => page.includes(p));

    // Auth guard on protected pages
    if (isProtected && !isLoggedIn()) {
        window.location.href = 'login.html';
        return;
    }

    // Show connection status on data-driven pages
    if (isProtected) {
        showConnectionStatus();
    }

    syncAuthNavigation();
}

window.addEventListener('storage', syncAuthNavigation);

