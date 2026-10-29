
console.log('[API Module] Loading...');

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
        const token = this.getToken();

        const { expectedStatuses = [], ...fetchOnlyOptions } = options;

        const headers = { ...(options.headers || {}) };
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        if (!headers['Content-Type'] && options.body && typeof options.body === 'object') {
            headers['Content-Type'] = 'application/json';
        }

        const url = `${this.baseURL}${endpoint}`;
        const fetchOptions = {
            ...fetchOnlyOptions,
            headers
        };

        if (fetchOptions.body && typeof fetchOptions.body === 'object') {
            fetchOptions.body = JSON.stringify(fetchOptions.body);
        }

        try {
            const response = await fetch(url, fetchOptions);

            if (response.status === 401) {
                if (!_meta._retrying && window.Auth && window.Auth.getRefreshToken()) {
                    const refreshed = await this._singleFlightRefresh();
                    if (refreshed === true) {
                        console.log('API: 401 recovered via refresh, retrying original request');
                        return this.call(endpoint, options, { _retrying: true });
                    }
                    if (refreshed === 'network-error') {
                        console.warn('API: 401 + refresh hit network error - preserving refresh token');
                        if (window.Auth) {
                            window.Auth.clearToken({ accessOnly: true });
                        }
                        const err = new Error('Network unavailable; please retry');
                        err.code = 'NetworkUnavailable';
                        err.status = 0;
                        throw err;
                    }
                }
                console.log('API: 401 Unauthorized - triggering re-auth');
                this.handleUnauthorized();
                throw new Error('Authentication required. Please log in again.');
            }

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                // could not
                const detail = errorData.detail;
                const message = (typeof detail === 'string' && detail)
                    || (detail && typeof detail === 'object' && detail.message)
                    || (detail && typeof detail === 'object' && typeof detail.detail === 'string' && detail.detail)
                    || errorData.message
                    || `HTTP ${response.status}`;
                const err = new Error(message);
                err.status = response.status;
                err.detail = detail;
                err.body = errorData;
                if (typeof window.dispatchEvent === 'function') window.dispatchEvent(new CustomEvent('cloude:api-refusal', { detail: { status: response.status, body: errorData } }));
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

    async getProjects(includeArchived = false) {
        return await this.call(
            includeArchived ? '/projects?include_archived=true' : '/projects'
        );
    }

    async archiveProject(name) {
        return await this.call(
            `/projects/${encodeURIComponent(name)}/archive`,
            { method: 'POST' }
        );
    }

    async unarchiveProject(name) {
        return await this.call(
            `/projects/${encodeURIComponent(name)}/unarchive`,
            { method: 'POST' }
        );
    }

    async getProjectsPresence() {
        return await this.call('/projects/presence');
    }

    /* could not be read */
    async getProjectsAuthority() {
        return await this.call('/projects/authority');
    }

    /* CANNOT BE DETERMINED could not be read */
    async getSessionAttributionPrompt() {
        return await this.call('/sessions/attribution-prompt');
    }

    async declineSessionAttribution(tmuxNames) {
        return await this.call('/sessions/attribution-decline', {
            method: 'POST',
            body: { tmux_names: tmuxNames }
        });
    }

    async createProject(params) {
        return await this.call('/projects', {
            method: 'POST',
            body: params
        });
    }

    async checkProjectRoot(path) {
        return await this.call('/projects/check-root', {
            method: 'POST',
            body: { path }
        });
    }

    async updateProject(currentName, { newName, description, defaultLaunchProfile, color } = {}) {
        const body = {};
        if (newName !== undefined) body.new_name = newName;
        if (description !== undefined) body.description = description;
        if (defaultLaunchProfile !== undefined) body.default_launch_profile = defaultLaunchProfile;
        if (color !== undefined) body.color = color;
        return await this.call(`/projects/${encodeURIComponent(currentName)}`, {
            method: 'PATCH',
            body
        });
    }

    async cloneProjectFromGithub({ repoUrl, parentDir, projectName, description } = {}) {
        const body = { repo_url: repoUrl };
        if (parentDir !== undefined && parentDir !== '') body.parent_dir = parentDir;
        if (projectName !== undefined && projectName !== '') body.project_name = projectName;
        if (description !== undefined) body.description = description;
        return await this.call('/projects/clone', {
            method: 'POST',
            body
        });
    }

    async browseDirectory(path = null) {
        const query = path ? `?path=${encodeURIComponent(path)}` : '';
        return await this.call(`/filesystem/browse${query}`);
    }

    async makeDirectory(path) {
        return await this.call('/filesystem/mkdir', {
            method: 'POST',
            body: { path }
        });
    }

    async getProviders() {
        return await this.call('/providers');
    }

    async addProviderModel(model) {
        return await this.call('/providers/models', {
            method: 'POST',
            body: { model }
        });
    }

    async removeProviderModel(model) {
        return await this.call(`/providers/models/${encodeURIComponent(model)}`, {
            method: 'DELETE'
        });
    }

    async getSettings() {
        return await this.call('/config/settings');
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

    /* could not be determined */
    async getSessionTokenUsage(sessionId) {
        const id = encodeURIComponent(String(sessionId || ''));
        return await this.call(`/sessions/${id}/token-usage`);
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

    async uploadFile(blob, filename = '', sessionId = null, _meta = {}) {
        let declared = String(filename || '').trim();
        if (!declared) {
            const type = (blob && blob.type) || '';
            const ext = (type.split('/')[1] || 'bin').split(';')[0];
            declared = `paste.${ext}`;
        }
        const form = new FormData();
        form.append('file', blob, declared);

        const token = this.getToken();
        const headers = {};
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }

        const q = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
        const url = `${this.baseURL}/sessions/upload-file${q}`;
        try {
            const response = await fetch(url, {
                method: 'POST',
                headers,
                body: form,
            });

            if (response.status === 401) {
                if (!_meta._retrying && window.Auth && window.Auth.getRefreshToken()) {
                    const refreshed = await this._singleFlightRefresh();
                    if (refreshed === true) {
                        console.log('API: 401 recovered via refresh, retrying uploadFile');
                        return this.uploadFile(blob, declared, sessionId, { _retrying: true });
                    }
                    if (refreshed === 'network-error') {
                        console.warn('API: 401 + refresh hit network error on uploadFile - preserving refresh token');
                        if (window.Auth) {
                            window.Auth.clearToken({ accessOnly: true });
                        }
                        const err = new Error('Network unavailable; please retry');
                        err.code = 'NetworkUnavailable';
                        err.status = 0;
                        throw err;
                    }
                }
                console.log('API: 401 Unauthorized on uploadFile - triggering re-auth');
                this.handleUnauthorized();
                throw new Error('Authentication required. Please log in again.');
            }

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                const d = errorData.detail;
                const message = (typeof d === 'string' && d)
                    || (d && typeof d === 'object' && typeof d.message === 'string' && d.message)
                    || (d && typeof d === 'object' && typeof d.detail === 'string' && d.detail)
                    || (typeof errorData.message === 'string' && errorData.message)
                    || `HTTP ${response.status}`;
                const err = new Error(message);
                err.status = response.status;
                err.detail = d;
                throw err;
            }

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
        if (!response.ok) {
            const body = await response.json().catch(() => ({}));
            const err = new Error(body.detail || `HTTP ${response.status}`);
            err.status = response.status;
            throw err;
        }
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

    async destroyExternalSession(sessionName) {
        return await this._leaderSafe((confirmName) => this.call(
            `/sessions/external/${encodeURIComponent(sessionName)}${confirmName ? '?confirm_name=' + encodeURIComponent(confirmName) : ''}`,
            { method: 'DELETE' }
        ));
    }

    /* already running could not */
    async restartPreview(sessionName) {
        /* could not be read */
        const qs = encodeURIComponent(sessionName);
        return await this.call(`/sessions/restart/preview?session_name=${qs}`);
    }

    /* did not answer */
    async recreatePreview(sessionUuid) {
        const qs = encodeURIComponent(sessionUuid);
        return await this.call(`/sessions/recreate/preview?session_uuid=${qs}`);
    }

    async restartAccounts(sessionUuid) {
        return await this.call(`/sessions/${encodeURIComponent(sessionUuid)}/restart/accounts`);
    }

    async recreateSession(sessionUuid, agentType, account) {
        const body = { session_uuid: sessionUuid, agent_type: agentType };
        if (account && account.accountId) {
            body.account_id = account.accountId;
            body.account_pinned = account.pinned === true;
        }
        return await this.call('/sessions/recreate', { method: 'POST', body });
    }

    async respawnSession(sessionName, agentType, confirmRestartLive, account) {
        const body = { session_name: sessionName };
        if (agentType) body.agent_type = agentType;
        if (confirmRestartLive === true) body.confirm_restart_live = true;
        if (account && account.accountId) {
            body.account_id = account.accountId;
            body.account_pinned = account.pinned === true;
        }
        return await this.call('/sessions/respawn', {
            method: 'POST',
            body,
        });
    }

    /**
     * Sessions: Set a session's LABEL - the free-form name a human reads.
     *
     * PATCH /api/v1/sessions/{id}/name. THIS DOES NOT RENAME TMUX. It
     * writes ``sessions.title`` and stops; the tmux name is an internal
     * handle derived from the label once, at creation, and never moved
     * again. Keeping them separate is what stops a rename from moving the
     * field session identity is keyed on.
     *
     * ``session_label.validate_label`` refuses exactly three things:
     * empty after stripping, longer than ``LABEL_MAX_CHARS`` (200), and
     * control characters. Spaces, ``:``, ``.``, quotes, ``$`` and
     * non-ASCII are all legal, because a label is never handed to tmux.
     * Two sessions may carry the SAME label; there is no uniqueness rule
     * and so no collision to report. Callers should pre-validate through
     * ``SessionLabel.validate`` (client/js/session-label.js) rather than
     * carrying their own rule - this docstring previously advertised the
     * old ``^[A-Za-z0-9_-]{1,64}$`` tmux-name charset, and all three
     * rename controls enforced it against a server that had already
     * stopped applying it.
     *
     * On success the server broadcasts ``session.renamed`` over every WS
     * bound to this session id - the caller does NOT need to manually
     * mutate displayed state, just await success and rely on the WS
     * handler in terminal.js to update header text + document.title.
     *
     * @param {string} sessionId - Session id (NOT tmux name).
     * @param {string} newName - The new label. Server is authoritative.
     * @returns {Promise<object>} Updated SessionInfo payload.
     * @throws on 400 (empty, too long, or a control character), 404
     *   (unknown id). No 409 - a label identifies nothing.
     */
    async renameSession(sessionId, newName) {
        return await this.call(
            `/sessions/${encodeURIComponent(sessionId)}/name`,
            {
                method: 'PATCH',
                body: { new_name: newName },
            }
        );
    }

    async setSessionUnread(tmuxName, unread) {
        return await this.call(
            `/sessions/${encodeURIComponent(tmuxName)}/unread`,
            {
                method: 'PATCH',
                body: { unread: !!unread },
            }
        );
    }

    async detachSession(sessionId = null) {
        const q = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
        return await this.call(`/sessions/detach${q}`, {
            method: 'POST'
        });
    }

    async listAttachableSessions() {
        return await this._listingRead('attachable', '/sessions/attachable');
    }

    async listRecentSessions(includeArchived = false) {
        return await this.call(
            includeArchived
                ? '/sessions/recent?include_archived=true'
                : '/sessions/recent'
        );
    }

    async listSessionRecords() {
        return await this._listingRead('records', '/sessions/records');
    }

    async listSessionCompanions() {
        return await this._listingRead('companions', '/sessions/companions');
    }

    async listArchivedSessionRecords() {
        return await this.call('/sessions/records?archived_only=true');
    }

    /* could not be reached */
    async getLocalModels() {
        return await this.call('/providers/local/models');
    }

    async forkSession(sessionName) {
        return await this.call(
            `/sessions/${encodeURIComponent(sessionName)}/fork`,
            { method: 'POST' }
        );
    }

    async restartSession(sessionUuid) {
        return await this.call(
            `/sessions/${encodeURIComponent(sessionUuid)}/restart`,
            { method: 'POST' }
        );
    }

    /* conversation id could not */
    async sleepSession(sessionUuid) {
        return await this.call(
            `/sessions/${encodeURIComponent(sessionUuid)}/sleep`,
            { method: 'POST' }
        );
    }

    /* not asleep */
    async wakeSession(sessionUuid, agentType, account, startFresh) {
        const init = { method: 'POST' };
        const body = {};
        if (agentType) body.agent_type = agentType;
        if (account && account.accountId) {
            body.account_id = account.accountId;
            body.account_pinned = account.pinned === true;
        }
        if (startFresh === true) body.start_fresh = true;
        if (Object.keys(body).length) init.body = body;
        return await this.call(
            `/sessions/${encodeURIComponent(sessionUuid)}/wake`,
            init
        );
    }

    /* not asleep */
    async killAsleepSession(sessionUuid) {
        return await this._leaderSafe((confirmName) => this.call(
            `/sessions/${encodeURIComponent(sessionUuid)}/asleep${confirmName ? '?confirm_name=' + encodeURIComponent(confirmName) : ''}`,
            { method: 'DELETE' }
        ));
    }

    async deleteSessionRecord(sessionUuid) {
        return await this._leaderSafe((confirmName) => this.call(
            `/sessions/records/${encodeURIComponent(sessionUuid)}${confirmName ? '?confirm_name=' + encodeURIComponent(confirmName) : ''}`,
            { method: 'DELETE' }
        ));
    }

    async unarchiveSessionRecord(sessionUuid) {
        return await this.call(
            `/sessions/records/${encodeURIComponent(sessionUuid)}/unarchive`,
            { method: 'POST' }
        );
    }

    /*  hidden  */
    async adoptSession(sessionName, confirmDetach = false, controller = null) {
        const vote = window.TerminalSizeVote;
        const grid = vote && typeof vote.adoptGrid === 'function' ? vote.adoptGrid(controller, document) : {};
        return await this.call('/sessions/adopt', {
            method: 'POST',
            body: {
                session_name: sessionName,
                confirm_detach: confirmDetach,
                ...(grid.cols && grid.rows
                    ? { cols: grid.cols, rows: grid.rows }
                    : {}),
            },
        });
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

    async postSessionToast(sessionId, { kind, title, body } = {}) {
        return await this.call(
            `/sessions/${encodeURIComponent(sessionId)}/toasts`,
            {
                method: 'POST',
                body: { kind, title, body: body || null },
            }
        );
    }

    async getConfigFileTree(root, projectPath = null, opts = {}) {
        const params = new URLSearchParams({ root });
        if (projectPath) params.set('project_path', projectPath);
        if (opts && opts.path) params.set('path', opts.path);
        if (opts && opts.depth != null) params.set('depth', String(opts.depth));
        if (opts && opts.ignored) params.set('ignored', 'true');
        return await this.call(`/config-files/tree?${params.toString()}`);
    }

    async findConfigFiles(root, projectPath, opts) {
        const params = new URLSearchParams({ root, q: opts.q });
        if (projectPath) params.set('project_path', projectPath);
        if (opts.path) params.set('path', opts.path);
        if (opts.ignored) params.set('ignored', 'true');
        return await this.call(`/config-files/find?${params.toString()}`);
    }

    async readConfigFile(root, path, projectPath = null) {
        const params = new URLSearchParams({ root, path });
        if (projectPath) params.set('project_path', projectPath);
        return await this.call(`/config-files/read?${params.toString()}`);
    }

    async writeConfigFile(body) {
        return await this.call('/config-files/write', {
            method: 'POST',
            body,
        });
    }

    async createConfigFile(body) {
        return await this.call('/config-files/create', {
            method: 'POST',
            body,
        });
    }

    // could not

    async listSessionGroups() {
        return await this.call('/session-groups');
    }

    async createSessionGroup(name) {
        return await this.call('/session-groups', { method: 'POST', body: { name } });
    }

    async renameSessionGroup(groupUuid, name) {
        return await this.call(`/session-groups/${encodeURIComponent(groupUuid)}`, {
            method: 'PATCH', body: { name },
        });
    }

    async deleteSessionGroup(groupUuid) {
        return await this.call(`/session-groups/${encodeURIComponent(groupUuid)}`, {
            method: 'DELETE',
        });
    }

    async assignSessionGroup(name, groupUuid) {
        const L = window.SessionSidebarLayouts;
        const isLayout = !!(L && typeof L.isLayoutName === 'function' && L.isLayoutName(name));
        const body = isLayout
            ? { layout_uuid: L.idOf(name), group_uuid: groupUuid }
            : { tmux_name: name, group_uuid: groupUuid };
        return await this.call('/session-groups/assign', { method: 'POST', body });
    }

    async reorderSessionGroups(groupUuids) {
        return await this.call('/session-groups/order', {
            method: 'POST', body: { group_uuids: groupUuids },
        });
    }

    async reorderSessionGroupMembers(groupUuid, sessionUuids) {
        return await this.call(`/session-groups/${encodeURIComponent(groupUuid)}/order`, {
            method: 'POST', body: { session_uuids: sessionUuids },
        });
    }

    async setSessionGroupStyle(groupUuid, style) {
        return await this.call(`/session-groups/${encodeURIComponent(groupUuid)}/style`, {
            method: 'PUT',
            body: {
                colour: style.colour,
                gradient: style.gradient || null,
                animation: style.animation || 'none',
            },
        });
    }

    async setSessionGroupIcon(groupUuid, icon) {
        return await this.call(`/session-groups/${encodeURIComponent(groupUuid)}/icon`, {
            method: 'PUT', body: { icon: icon || null },
        });
    }


    async getCatalogItems() {
        return await this.call('/catalog/items');
    }

    async getCatalogItem(itemId) {
        return await this.call(`/catalog/items/${encodeURIComponent(itemId)}`);
    }

    async getCatalogContents(itemId) {
        return await this.call(`/catalog/contents/${encodeURIComponent(itemId)}`);
    }

    async refreshCatalogIndex() {
        return await this.call('/catalog/index/refresh', { method: 'POST' });
    }

    async catalogOpened() {
        return await this.call('/catalog/refresh', { method: 'POST' });
    }

    async getCatalogInstalled() {
        return await this.call('/catalog/installed');
    }

    async previewCatalogInstall(request) {
        return await this.call('/catalog/install/preview', {
            method: 'POST', body: request, expectedStatuses: [409],
        });
    }

    async installCatalogItem(request) {
        return await this.call('/catalog/install', {
            method: 'POST', body: request, expectedStatuses: [409],
        });
    }

    async uninstallCatalogItem(installId) {
        return await this.call(`/catalog/installed/${encodeURIComponent(installId)}`, {
            method: 'DELETE',
        });
    }

    async patchCatalogInstalled(installId, body) {
        return await this.call(`/catalog/installed/${encodeURIComponent(installId)}`, {
            method: 'PATCH', body, expectedStatuses: [409],
        });
    }

    async updateCatalogInstalled(installId, body) {
        return await this.call(
            `/catalog/installed/${encodeURIComponent(installId)}/update`,
            { method: 'POST', body, expectedStatuses: [409] },
        );
    }

    /* could not be read */
    async getCatalogItemRatings(itemId) {
        return await this.call(`/catalog/items/${encodeURIComponent(itemId)}/ratings`);
    }

    async putCatalogItemRating(itemId, body) {
        return await this.call(`/catalog/items/${encodeURIComponent(itemId)}/rating`, {
            method: 'PUT', body, expectedStatuses: [400, 401, 404, 429],
        });
    }

    async deleteCatalogItemRating(itemId) {
        return await this.call(`/catalog/items/${encodeURIComponent(itemId)}/rating`, {
            method: 'DELETE', expectedStatuses: [400, 401, 404],
        });
    }

    /* could not be read */
    async getCatalogItemInstalls(itemId) {
        return await this.call(`/catalog/items/${encodeURIComponent(itemId)}/installs`);
    }

    async getCatalogInstallCounts(ids) {
        return await this.call('/catalog/install-counts', { method: 'POST', body: { ids } });
    }


    async getCatalogComments(itemId, cursor) {
        const q = cursor ? `?cursor=${encodeURIComponent(cursor)}` : '';
        return await this.call(`/catalog/items/${encodeURIComponent(itemId)}/comments${q}`);
    }

    async getMyCatalogComments(itemId) {
        return await this.call(`/catalog/me/comments?item_id=${encodeURIComponent(itemId)}`, {
            expectedStatuses: [403],
        });
    }

    async postCatalogComment(itemId, body) {
        return await this.call(`/catalog/items/${encodeURIComponent(itemId)}/comments`, {
            method: 'POST', body, expectedStatuses: [400, 403, 404, 429, 502],
        });
    }

    async editCatalogComment(itemId, commentId, body) {
        return await this.call(
            `/catalog/items/${encodeURIComponent(itemId)}/comments/${encodeURIComponent(commentId)}`,
            { method: 'PUT', body, expectedStatuses: [400, 403, 404, 409, 429, 502] },
        );
    }

    async deleteCatalogComment(itemId, commentId) {
        return await this.call(
            `/catalog/items/${encodeURIComponent(itemId)}/comments/${encodeURIComponent(commentId)}`,
            { method: 'DELETE', expectedStatuses: [403, 404, 409, 502] },
        );
    }

    async reportCatalog(body) {
        return await this.call('/catalog/reports', {
            method: 'POST', body, expectedStatuses: [400, 403, 404, 429, 502],
        });
    }

    async getCatalogProfile(handle) {
        return await this.call(`/catalog/profiles/${encodeURIComponent(handle)}`, {
            expectedStatuses: [404],
        });
    }

    async setCatalogMailPreference(body) {
        return await this.call('/catalog/me/mail-preference', {
            method: 'PUT', body, expectedStatuses: [403, 429, 502],
        });
    }

    async getSkillUsage(skill) {
        return await this.call(`/skill-fires/usage?skill=${encodeURIComponent(skill)}`);
    }

    async getSkillAutopsy(skill, days = 30) {
        return await this.call(
            `/skills/${encodeURIComponent(skill)}/autopsy?days=${encodeURIComponent(days)}`,
        );
    }

    async restoreCatalogInstalled(installId, body) {
        return await this.call(
            `/catalog/installed/${encodeURIComponent(installId)}/restore`,
            { method: 'POST', body, expectedStatuses: [409] },
        );
    }

    async setCatalogInstalledFork(installId, forked) {
        return await this.call(
            `/catalog/installed/${encodeURIComponent(installId)}/fork`,
            { method: 'PUT', body: { forked } },
        );
    }

    async getPublishableSkills() {
        return await this.call('/catalog/publish/mine');
    }

    async previewPublish(body) {
        return await this.call('/catalog/publish/preview', {
            method: 'POST', body, expectedStatuses: [400, 404],
        });
    }

    async sendSubmission(body) {
        return await this.call('/catalog/submissions', {
            method: 'POST', body,
            expectedStatuses: [400, 403, 404, 409, 413, 429, 502, 503],
        });
    }

    async sendHeroImage(body) {
        return await this.call('/catalog/submissions/media', {
            method: 'POST', body,
            expectedStatuses: [400, 403, 404, 409, 413, 422, 429, 502, 503],
        });
    }

    async getMySubmissions() {
        return await this.call('/catalog/submissions/mine', { expectedStatuses: [403, 429, 502, 503] });
    }

    async getSubmissionReport(submissionId) {
        return await this.call(`/catalog/submissions/${encodeURIComponent(submissionId)}/report`, {
            expectedStatuses: [403, 404, 429, 502, 503],
        });
    }

    async getPublishAccount() {
        return await this.call('/catalog/handle', { expectedStatuses: [403, 502, 503] });
    }

    async registerCatalogAccount(body) {
        return await this.call('/catalog/account/register', {
            method: 'POST', body,
            expectedStatuses: [400, 403, 409, 429, 502, 503],
        });
    }

    async getCatalogSession() {
        return await this.call('/catalog/auth/session');
    }

    async startCatalogDeviceFlow() {
        return await this.call('/catalog/auth/device/start', {
            method: 'POST', expectedStatuses: [503],
        });
    }

    async pollCatalogDeviceFlow(flowId) {
        return await this.call('/catalog/auth/device/poll', {
            method: 'POST', body: { flow_id: flowId }, expectedStatuses: [428],
        });
    }

    async startCatalogGoogleFlow() {
        return await this.call('/catalog/auth/google/start', {
            method: 'POST', expectedStatuses: [503],
        });
    }

    async pollCatalogGoogleFlow(flowId) {
        return await this.call('/catalog/auth/google/poll', {
            method: 'POST', body: { flow_id: flowId }, expectedStatuses: [428],
        });
    }

    async verifyCatalogGoogleMailboxCode(flowId, code, extra = {}) {
        return await this.call('/catalog/auth/google/mailbox/verify', {
            method: 'POST', body: { flow_id: flowId, code, ...extra },
            expectedStatuses: [400, 403, 410, 429, 503],
        });
    }

    async startCatalogEmailFlow(email) {
        return await this.call('/catalog/auth/email/start', {
            method: 'POST', body: { email },
            expectedStatuses: [400, 403, 410, 429, 503],
        });
    }

    async verifyCatalogEmailCode(flowId, code, extra = {}) {
        return await this.call('/catalog/auth/email/verify', {
            method: 'POST', body: { flow_id: flowId, code, ...extra },
            expectedStatuses: [400, 403, 409, 410, 429, 503],
        });
    }

    async startCatalogWebFlow(body) {
        return await this.call('/catalog/auth/web/start', {
            method: 'POST', body, expectedStatuses: [400, 409, 429, 503],
        });
    }

    async pollCatalogWebFlow(flowId) {
        return await this.call('/catalog/auth/web/poll', {
            method: 'POST', body: { flow_id: flowId },
            expectedStatuses: [400, 403, 410, 429, 502, 503],
        });
    }

    async signOutOfCatalog() {
        return await this.call('/catalog/auth/signout', { method: 'POST' });
    }

    async getCatalogAccountSessions() {
        return await this.call('/catalog/account/sessions', { expectedStatuses: [403, 502, 503] });
    }

    async revokeCatalogAccountSession(sid) {
        return await this.call(`/catalog/account/sessions/${encodeURIComponent(sid)}`, {
            method: 'DELETE', expectedStatuses: [400, 403, 502, 503],
        });
    }

    async revokeOtherCatalogSessions() {
        return await this.call('/catalog/account/sessions/revoke-others', {
            method: 'POST', expectedStatuses: [403, 502, 503],
        });
    }

    async deleteCatalogAccount(confirm) {
        return await this.call('/catalog/account/delete', {
            method: 'POST', body: { confirm },
            expectedStatuses: [400, 403, 404, 429, 502, 503],
        });
    }

    async changeCatalogHandle(handle) {
        return await this.call('/catalog/account/handle', {
            method: 'POST', body: { handle },
            expectedStatuses: [400, 403, 409, 429, 502, 503],
        });
    }

    async setCatalogNews(news) {
        return await this.call('/catalog/account/news', {
            method: 'POST', body: { news },
            expectedStatuses: [403, 429, 502, 503],
        });
    }

    async exportCatalogAccount() {
        return await this.call('/catalog/account/export', { expectedStatuses: [403, 413, 429, 502, 503] });
    }

    async oneShotSkill(sessionId, text) {
        return await this.call(
            `/sessions/${encodeURIComponent(sessionId)}/skills/one-shot`,
            { method: 'POST', body: { text }, expectedStatuses: [409] },
        );
    }

    async getProviderLedger() {
        return await this.call('/provider-ledger');
    }

    async listProviderAccounts() {
        return await this.call('/provider-ledger/accounts');
    }

    /* could not */
    async saveProviderAccount(id, account) {
        return await this.call(`/provider-ledger/accounts/${encodeURIComponent(id)}`, {
            method: 'PUT',
            body: account,
            expectedStatuses: [400, 409, 422]
        });
    }

    /* could not */
    async loginProviderAccount(id) {
        return await this.call(
            `/provider-ledger/accounts/${encodeURIComponent(id)}/login`,
            { method: 'POST', expectedStatuses: [404, 409] }
        );
    }

    async deleteProviderAccount(id) {
        return await this.call(`/provider-ledger/accounts/${encodeURIComponent(id)}`, {
            method: 'DELETE',
            expectedStatuses: [404]
        });
    }
}

window.API = new API();
console.log('[API Module] Exported as window.API:', window.API);
