
console.log('[API Module] Loading...');

function codedMessage(errorData, fallback) {
    const d = errorData && errorData.detail;
    const code = (d && typeof d === 'object' && typeof d.code === 'string' && d.code)
        || (errorData && typeof errorData.code === 'string' && errorData.code) || '';
    const i18n = typeof window !== 'undefined' ? window.CloudeI18n : null;
    if (!code || !i18n || typeof i18n.t !== 'function') return fallback;
    const key = `api.error.${code}`;
    const sentence = i18n.t(key);
    return sentence && sentence !== key ? sentence : fallback;
}

class API {
    constructor() {
        const here = window.location.host ? window.location : new URL(document.baseURI);
        const protocol = here.protocol === 'https:' ? 'https:' : 'http:';
        const wsProtocol = here.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = here.host;

        this.baseURL = `${protocol}//${host}/api/v1`;
        this.wsBaseURL = `${wsProtocol}//${host}`;

        this._refreshPromise = null;

        this.ARCHIVE_TIMEOUTS = {
            hierarchy: 10000,
            transcript: 15000,
            body: 30000,
            search: 45000,
            exportPreflight: 20000
        };
    }

    getToken() {
        return localStorage.getItem('claude_tunnel_token');
    }

    async call(endpoint, options = {}, _meta = {}) {
        const dedupe = globalThis.BootFetchDedupe;
        if (!dedupe || _meta._retrying) return this._callOnce(endpoint, options, _meta);
        const declared = Array.isArray(options.expectedStatuses) ? [...options.expectedStatuses].sort().join(',') : '';
        return dedupe.run(`api:${declared}:${this.baseURL}${endpoint}`, options, () => this._callOnce(endpoint, options, _meta));
    }

    async _callOnce(endpoint, options = {}, _meta = {}) {
        const { expectedStatuses = [], ...fetchOnlyOptions } = options;

        const headers = { ...(options.headers || {}) };
        if (!headers['Content-Type'] && options.body && typeof options.body === 'object') {
            headers['Content-Type'] = 'application/json';
        }

        const fetchOptions = {
            ...fetchOnlyOptions,
            headers
        };

        if (fetchOptions.body && typeof fetchOptions.body === 'object') {
            fetchOptions.body = JSON.stringify(fetchOptions.body);
        }

        try {
            const response = await this.rawCall(endpoint, fetchOptions, _meta);

            if (!response.ok) {
                const err = await this._errorFromResponse(response);
                if (typeof window.dispatchEvent === 'function') window.dispatchEvent(new CustomEvent('cloude:api-refusal', { detail: { status: response.status, body: err.body } }));
                throw err;
            }

            return await response.json();
        } catch (error) {
            const status = error && error.status;
            if (status && expectedStatuses.includes(status)) {
                console.debug(`API [${endpoint}]: expected ${status} - ${error.message}`);
            } else {
                console.error(`API Error [${endpoint}]:`, error);
            }
            throw error;
        }
    }

    async _errorFromResponse(response) {
        const errorData = await response.json().catch(() => ({}));
        const detail = errorData.detail;
        const message = (typeof detail === 'string' && detail)
            || (detail && typeof detail === 'object' && detail.message)
            || (detail && typeof detail === 'object' && typeof detail.detail === 'string' && detail.detail)
            || errorData.message
            || `HTTP ${response.status}`;
        const err = new Error(codedMessage(errorData, message));
        err.status = response.status;
        err.detail = detail;
        err.body = errorData;
        return err;
    }

    async _singleFlightRefresh() {
        if (this._refreshPromise) {
            return this._refreshPromise;
        }
        this._refreshPromise = (async () => {
            try {
                return await window.Auth.refresh();
            } finally {
                this._refreshPromise = null;
            }
        })();
        return this._refreshPromise;
    }

    handleUnauthorized() {
        if (window.Auth) {
            window.Auth.clearToken();
        } else {
            localStorage.removeItem('claude_tunnel_token');
            localStorage.removeItem('claude_refresh_token');
        }

        window.dispatchEvent(new CustomEvent('auth-required'));
    }

    async verifyTOTP(totpCode) {
        const response = await fetch(`${this.baseURL}/auth/verify`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code: totpCode })
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            const detail = errorData.detail;
            const reason = detail && typeof detail === 'object' ? detail.reason : undefined;
            const text = (v) => (typeof v === 'string' && v ? v : '');
            let message = text(errorData.error) || text(detail) || text(detail && detail.message)
                || text(errorData.message) || 'Unknown error';

            if (response.status === 429) {
                const retryAfterRaw = response.headers.get('Retry-After');
                const retrySec = parseInt(retryAfterRaw, 10);
                if (Number.isFinite(retrySec) && retrySec > 0 && !/try again/i.test(message)) {
                    message = `${message.replace(/\.$/, '')}. Try again in ${retrySec}s.`;
                }
            }

            const err = new Error(message);
            err.status = response.status;
            err.reason = reason;
            throw err;
        }

        return await response.json();
    }

    async checkAuthStatus() {
        return await this.call('/auth/status');
    }

    async getCommonCommands() {
        return await this.call('/config/common-commands');
    }

    async toggleFavoriteCommand(command, favorite) {
        return await this.call('/config/common-commands/favorite', {
            method: 'POST',
            body: { command: command, favorite: !!favorite }
        });
    }

    async getSlashCommands(projectPath = null) {
        const q = projectPath ? `?project_path=${encodeURIComponent(projectPath)}` : '';
        return await this.call(`/config/slash-commands${q}`);
    }

    async updateSettings(patch) {
        return await this.call('/config/settings', {
            method: 'PATCH',
            body: patch
        });
    }

    async createSession(params = {}) {
        return await this.call('/sessions', {
            method: 'POST',
            body: params
        });
    }

    async getSession(sessionId = null, { includeScrollback = false, cols = null, rows = null, parallelHistory = false, scrollbackLines = null } = {}) {
        if (parallelHistory && includeScrollback) {
            const pending = this.getSession(sessionId, { includeScrollback, cols, rows, scrollbackLines })
                .then((full) => (full && full.initial_scrollback_b64) || null, () => null);
            const info = await this.getSession(sessionId);
            if (info && typeof info === 'object') {
                Object.defineProperty(info, 'initial_scrollback_pending', { value: pending });
            }
            return info;
        }
        const params = [];
        if (sessionId) {
            params.push(`session_id=${encodeURIComponent(sessionId)}`);
        }
        if (includeScrollback) {
            params.push('include_scrollback=1');
        }
        if (includeScrollback && scrollbackLines && scrollbackLines > 0) {
            params.push(`scrollback_lines=${encodeURIComponent(String(scrollbackLines))}`);
        }
        if (cols && cols > 0) {
            params.push(`cols=${encodeURIComponent(String(cols))}`);
        }
        if (rows && rows > 0) {
            params.push(`rows=${encodeURIComponent(String(rows))}`);
        }
        const q = params.length ? `?${params.join('&')}` : '';
        return await this.call(`/sessions${q}`, { expectedStatuses: [404] });
    }

    async listSessions() {
        return await this._listingRead('list', '/sessions/list');
    }

    async _singleFlight(endpoint) {
        if (!this._flights) this._flights = new Map();
        let flight = this._flights.get(endpoint);
        if (!flight) {
            flight = this.call(endpoint).finally(() => this._flights.delete(endpoint));
            this._flights.set(endpoint, flight);
        }
        const value = await flight;
        return value === null || typeof value !== 'object' ? value : JSON.parse(JSON.stringify(value));
    }

    _pushed(name) {
        const push = globalThis.ListingPush;
        if (!push || typeof push.rows !== 'function') return null;
        return push.rows(name);
    }

    async _listingRead(name, endpoint) {
        const live = this._pushed(name);
        if (live) return live;
        const push = globalThis.ListingPush;
        const cached = push && typeof push.provisionalRows === 'function' ? await push.provisionalRows(name) : null;
        return cached || this._pushed(name) || await this._singleFlight(endpoint);
    }

    async getCurrentSession() {
        try {
            return await this.getSession();
        } catch (error) {
            const msg = (error && error.message) || '';
            if (/No active session|HTTP 404|404/i.test(msg)) {
                return null;
            }
            throw error;
        }
    }

    async destroySession(sessionId = null) {
        return await this._leaderSafe((confirmName) => {
            const parts = [];
            if (sessionId) parts.push(`session_id=${encodeURIComponent(sessionId)}`);
            if (confirmName) parts.push(`confirm_name=${encodeURIComponent(confirmName)}`);
            return this.call(`/sessions${parts.length ? '?' + parts.join('&') : ''}`, { method: 'DELETE' });
        });
    }

    async _leaderSafe(run) {
        try {
            return await run(null);
        } catch (err) {
            const d = err && err.status === 409 && err.detail;
            const ask = window.CloudeWeb && window.CloudeWeb.askLeaderConfirm;
            if (!d || d.code !== 'leader_protected' || typeof ask !== 'function') throw err;
            const typed = await ask({ name: d.name, rank: d.rank, action: d.action });
            if (typed === null || typed === undefined) {
                err.cancelled = true;
                throw err;
            }
            return await run(typed);
        }
    }

    async uploadFile(blob, filename = '', sessionId = null) {
        let declared = String(filename || '').trim();
        if (!declared) {
            const type = (blob && blob.type) || '';
            const ext = (type.split('/')[1] || 'bin').split(';')[0];
            declared = `paste.${ext}`;
        }
        const form = new FormData();
        form.append('file', blob, declared);

        const q = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
        try {
            const response = await this.rawCall(`/sessions/upload-file${q}`, { method: 'POST', body: form });
            if (!response.ok) throw await this._errorFromResponse(response);
            return await response.json();
        } catch (error) {
            console.error('API Error [uploadFile]:', error);
            throw error;
        }
    }

    async rawCall(endpoint, init = {}, _meta = {}) {
        const token = this.getToken();
        const headers = { ...(init.headers || {}) };
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        const response = await fetch(`${this.baseURL}${endpoint}`, {
            ...init,
            headers,
        });
        if (response.status === 401) {
            if (!_meta._retrying && window.Auth && window.Auth.getRefreshToken()) {
                const refreshed = await this._singleFlightRefresh();
                if (refreshed === true) {
                    return this.rawCall(endpoint, init, { _retrying: true });
                }
                if (refreshed === 'network-error') {
                    if (window.Auth) window.Auth.clearToken({ accessOnly: true });
                    const err = new Error('Network unavailable; please retry');
                    err.code = 'NetworkUnavailable';
                    err.status = 0;
                    throw err;
                }
            }
            this.handleUnauthorized();
            throw new Error('Authentication required. Please log in again.');
        }
        return response;
    }

    async uploadSessionBackgroundImage(name, file) {
        const form = new FormData();
        form.append('file', file, (file && file.name) || 'background');
        const response = await this.rawCall(
            `/sessions/${encodeURIComponent(name)}/background/image`,
            { method: 'PUT', body: form },
        );
        if (!response.ok) throw await this._errorFromResponse(response);
        return await response.json();
    }

    async fetchSessionBackgroundImage(name) {
        const response = await this.rawCall(
            `/sessions/${encodeURIComponent(name)}/background/image`,
            { method: 'GET' },
        );
        if (response.status === 404) return null;
        if (!response.ok) {
            const err = new Error(`HTTP ${response.status}`);
            err.status = response.status;
            throw err;
        }
        return await response.blob();
    }

    async deleteSessionBackgroundImage(name) {
        const response = await this.rawCall(
            `/sessions/${encodeURIComponent(name)}/background/image`,
            { method: 'DELETE' },
        );
        if (!response.ok) {
            const err = new Error(`HTTP ${response.status}`);
            err.status = response.status;
            throw err;
        }
    }

    getWebSocketURL(sessionId = null, path = '/ws/terminal') {
        const q = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
        return `${this.wsBaseURL}${path}${q}`;
    }

    openWebSocket(sessionId = null, path = '/ws/terminal', options = {}) {
        const token = this.getToken();
        const params = [];
        if (sessionId) params.push(`session_id=${encodeURIComponent(sessionId)}`);
        if (options && options.observer === true) {
            params.push('observer=1');
            if (options.interactive === true) params.push('interactive=1');
        } else if (path === '/ws/terminal' && window.TerminalSizeMaster) {
            params.push(`client_id=${encodeURIComponent(window.TerminalSizeMaster.clientId())}`);
        }
        const q = params.length ? `?${params.join('&')}` : '';
        const url = `${this.wsBaseURL}${path}${q}`;
        return new WebSocket(url, ['cloude.jwt.v1', token]);
    }

    async getSessionToasts(sessionId, { unackedOnly = true } = {}) {
        const q = unackedOnly ? '?unacked=true' : '';
        return await this.call(
            `/sessions/${encodeURIComponent(sessionId)}/toasts${q}`
        );
    }

    async ackToast(toastId, sessionId) {
        const q = `?session_id=${encodeURIComponent(sessionId)}`;
        return await this.call(`/toasts/${encodeURIComponent(toastId)}/ack${q}`, {
            method: 'POST',
        });
    }

    async oneShotSkill(sessionId, text) {
        return await this.call(
            `/sessions/${encodeURIComponent(sessionId)}/skills/one-shot`,
            { method: 'POST', body: { text }, expectedStatuses: [409] },
        );
    }
}

window.API = new API();
console.log('[API Module] Exported as window.API:', window.API);
