
console.log('[Auth Module] Loading...');

const REFRESH_LOCK_NAME = 'carnivore-auth-refresh';

const REFRESH_LOCK_WAIT_MS = 20000;

class Auth {
    constructor() {
        this.tokenKey = 'claude_tunnel_token';
        this.refreshKey = 'claude_refresh_token';
        this.authScreen = null;
        this.errorElement = null;
        this.infoElement = null;
        this.loginButton = null;
        this.totpInput = null;
        this._entryGen = 0;
        this._firstRunEntry = null;
    }

    init() {
        this.authScreen = document.getElementById('auth-screen');
        this.renderAuthUI();
    }

    t(key) {
        const i18n = globalThis.CloudeI18n;
        return i18n && typeof i18n.t === 'function' ? i18n.t(key) : key;
    }

    renderAuthUI() {
        this.authScreen.innerHTML = `
            <div class="auth-container hidden">
                <div class="auth-head">
                    <img class="auth-wordmark" src="/static/img/carnivore/carnivore-wordmark.png"
                         srcset="/static/img/carnivore/carnivore-wordmark@2x.png 2x" alt="" />
                    <div class="auth-prompt">${this.t('auth.totp_prompt.heading')}</div>
                </div>
                <div class="auth-body">
                    <div class="auth-description">${this.t('auth.totp_prompt.description')}</div>

                    <div class="auth-input-group">
                        <label class="auth-input-label" for="totp-input">${this.t('auth.totp_prompt.label')}</label>
                        <input
                            type="text"
                            id="totp-input"
                            class="auth-input"
                            placeholder="000000"
                            maxlength="6"
                            autocomplete="off"
                            inputmode="numeric"
                            pattern="[0-9]*"
                        />
                    </div>

                    <button class="modal-btn modal-btn-confirm auth-button" id="login-btn">${this.t('auth.totp_prompt.submit')}</button>

                    <div id="auth-error" class="auth-error hidden"></div>
                    <div id="auth-info" class="auth-info hidden"></div>
                </div>
            </div>
        `;

        this.totpInput = document.getElementById('totp-input');
        this.loginButton = document.getElementById('login-btn');
        this.errorElement = document.getElementById('auth-error');
        this.infoElement = document.getElementById('auth-info');

        this.loginButton.addEventListener('click', () => this.handleLogin());
        this.totpInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.handleLogin();
            }
        });

        this.totpInput.addEventListener('input', (e) => {
            e.target.value = e.target.value.replace(/[^0-9]/g, '');

            if (e.target.value.length === 6) {
                this.handleLogin();
            }
        });
    }

    async resolveEntry() {
        const gen = ++this._entryGen;
        const container = document.querySelector('#auth-screen .auth-container');
        if (container) container.classList.add('hidden');
        let entry = 'totp';
        try {
            const surface = window.CarnivoreFirstRun;
            if (surface) entry = await surface.probe();
        } catch (error) {
            console.warn('Auth: entry probe failed, showing the sign-in form', error);
        }
        const authScreen = document.getElementById('auth-screen');
        if (gen !== this._entryGen || !authScreen || !authScreen.classList.contains('active')) return;
        if (entry === 'joined' && (await this._desktopLocalLogin(gen))) return;
        if (gen !== this._entryGen || !authScreen.classList.contains('active')) return;
        if ((entry === 'first-run' || entry === 'remote' || entry === 'joined') && window.CarnivoreFirstRun) {
            try {
                authScreen.classList.remove('active');
                document.getElementById('first-run-screen').classList.add('active');
                if (this._firstRunEntry !== entry) {
                    window.CarnivoreFirstRun.mount('first-run-screen', entry);
                    this._firstRunEntry = entry;
                }
                return;
            } catch (error) {
                console.warn('Auth: first-run mount failed, showing the sign-in form', error);
            }
        }
        this.showLoginForm();
    }

    async _desktopLocalLogin(gen) {
        const bridge = window.carnivoreDesktop;
        if (!bridge || typeof bridge.localLogin !== 'function') return false;
        let tokens = null;
        try {
            tokens = await bridge.localLogin();
        } catch (error) {
            console.warn('Auth: local login failed, showing the joined panel', error);
        }
        if (!tokens || gen !== this._entryGen) return false;
        this.acceptLogin(tokens);
        this.finishFirstRun();
        return true;
    }

    showLoginForm() {
        this._unmountFirstRun();
        const firstRun = document.getElementById('first-run-screen');
        if (firstRun) firstRun.classList.remove('active');
        const authScreen = document.getElementById('auth-screen');
        if (authScreen) authScreen.classList.add('active');
        const container = document.querySelector('#auth-screen .auth-container');
        if (container) container.classList.remove('hidden');
        if (this.totpInput) this.totpInput.focus();
        this._watchClipboard();
        this.tryClipboardCode();
    }

    _watchClipboard() {
        if (this._clipboardWatched) return;
        this._clipboardWatched = true;
        window.addEventListener('focus', () => this.tryClipboardCode());
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') this.tryClipboardCode();
        });
    }

    async tryClipboardCode() {
        const container = document.querySelector('#auth-screen .auth-container');
        const screen = document.getElementById('auth-screen');
        if (!this.totpInput || !screen || !screen.classList.contains('active')) return;
        if (!container || container.classList.contains('hidden')) return;
        if (this._submitting || this._clipboardReading || this.totpInput.value !== '') return;
        if (!window.isSecureContext || !navigator.clipboard || !navigator.clipboard.readText) return;
        this._clipboardReading = true;
        try {
            const perm = navigator.permissions && await navigator.permissions.query({ name: 'clipboard-read' }).catch(() => null);
            if (perm && perm.state === 'denied') return;
            const text = await navigator.clipboard.readText();
            const code = String(text).trim().replace(/^(\d{3})[ -]?(\d{3})$/, '$1$2');
            if (!/^\d{6}$/.test(code) || code === this._clipboardTried) return;
            if (this._submitting || this.totpInput.value !== '') return;
            this._clipboardTried = code;
            this.totpInput.value = code;
            await this.handleLogin({ silent: true });
        } catch (err) {
        } finally {
            this._clipboardReading = false;
        }
    }

    _unmountFirstRun() {
        this._firstRunEntry = null;
        if (window.CarnivoreFirstRun) window.CarnivoreFirstRun.unmount();
    }

    acceptLogin(resp) {
        this.setToken(resp.access_token || resp.token);
        if (resp.refresh_token) {
            this.setRefreshToken(resp.refresh_token);
        }
    }

    finishFirstRun() {
        this._unmountFirstRun();
        const firstRun = document.getElementById('first-run-screen');
        if (firstRun) firstRun.classList.remove('active');
        window.dispatchEvent(new CustomEvent('authenticated'));
    }

    async handleLogin(opts = {}) {
        const silent = opts.silent === true;
        if (this._submitting) {
            return;
        }
        this._submitting = true;

        const totpCode = this.totpInput.value.trim();

        if (totpCode.length !== 6) {
            this.showError(this.t('auth.totp_prompt.error_length'));
            this._submitting = false;
            return;
        }

        if (!/^\d{6}$/.test(totpCode)) {
            this.showError(this.t('auth.totp_prompt.error_digits'));
            this._submitting = false;
            return;
        }

        this.loginButton.disabled = true;
        this.loginButton.textContent = this.t('auth.totp_prompt.verifying');
        this.hideError();
        this.hideInfo();

        try {
            const response = await window.API.verifyTOTP(totpCode);

            const access = response.access_token || response.token;
            this.setToken(access);
            if (response.refresh_token) {
                this.setRefreshToken(response.refresh_token);
            }

            console.log('Auth: Login successful');
            this.totpInput.value = '';
            window.dispatchEvent(new CustomEvent('authenticated'));

        } catch (error) {
            console.error('Auth: Login failed:', error);
            if (silent) {
                this.totpInput.value = '';
                this.totpInput.focus();
                return;
            }
            const errorMsg = error?.reason === 'code_reused'
                ? this.t('auth.totp_prompt.error_reused')
                : (typeof error?.message === 'string' && error.message) || this.t('auth.totp_prompt.error_failed');
            this.showError(errorMsg);
            this.totpInput.value = '';
            this.totpInput.focus();
        } finally {
            this.loginButton.disabled = false;
            this.loginButton.textContent = this.t('auth.totp_prompt.submit');
            this._submitting = false;
        }
    }

    showError(message) {
        this.errorElement.textContent = message;
        this.errorElement.classList.remove('hidden');
    }

    hideError() {
        this.errorElement.classList.add('hidden');
    }

    hideInfo() {
        this.infoElement.classList.add('hidden');
    }

    getToken() {
        return localStorage.getItem(this.tokenKey);
    }

    setToken(token) {
        localStorage.setItem(this.tokenKey, token);
    }

    clearToken(opts = {}) {
        localStorage.removeItem(this.tokenKey);
        if (!opts.accessOnly) {
            localStorage.removeItem(this.refreshKey);
        }
    }

    getRefreshToken() {
        return localStorage.getItem(this.refreshKey);
    }

    setRefreshToken(token) {
        if (token) {
            localStorage.setItem(this.refreshKey, token);
        }
    }

    async refresh() {
        const refreshToken = this.getRefreshToken();
        if (!refreshToken) {
            console.warn('Auth: refresh() called with no stored refresh token');
            return false;
        }
        const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined;
        if (!locks || typeof locks.request !== 'function') return this._rotate(refreshToken);
        const abort = new AbortController();
        const timer = setTimeout(() => abort.abort(), REFRESH_LOCK_WAIT_MS);
        try {
            return await locks.request(REFRESH_LOCK_NAME, { signal: abort.signal }, () => {
                clearTimeout(timer);
                return this._rotate(refreshToken);
            });
        } catch (e) {
            if (e && e.name === 'AbortError') {
                console.warn('Auth: refresh lock wait timed out (preserving tokens)');
                return 'network-error';
            }
            throw e;
        } finally {
            clearTimeout(timer);
        }
    }

    async _rotate(refreshToken) {
        const current = this.getRefreshToken();
        if (current !== refreshToken) {
            return !!(current && this.getToken());
        }

        let response;
        try {
            response = await fetch(`${window.API.baseURL}/auth/refresh`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: refreshToken })
            });
        } catch (e) {
            console.warn('Auth: refresh network error (preserving refresh token)', e);
            return 'network-error';
        }

        if (!response.ok) {
            if (response.status >= 500 || response.status === 408 || response.status === 429) {
                console.warn('Auth: refresh got a transient status (preserving refresh token)', response.status);
                return 'network-error';
            }
            console.warn('Auth: refresh failed with status', response.status);
            return false;
        }

        try {
            const data = await response.json();
            const access = data.access_token || data.token;
            if (!access) {
                console.warn('Auth: refresh response missing access_token');
                return false;
            }
            this.setToken(access);
            if (data.refresh_token) {
                this.setRefreshToken(data.refresh_token);
            }
            console.log('Auth: refreshed tokens');
            return true;
        } catch (e) {
            console.error('Auth: refresh response parse failed', e);
            return false;
        }
    }

    isAuthenticated() {
        return !!this.getToken();
    }

    logout() {
        console.log('Auth: Logging out');
        const refreshToken = this.getRefreshToken();
        if (refreshToken) {
            fetch(`${window.API.baseURL}/auth/logout`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: refreshToken })
            }).catch((e) => console.warn('Auth: logout revoke failed', e));
        }
        this.clearToken();
        window.dispatchEvent(new CustomEvent('logged-out'));
    }

    async verifyToken() {
        try {
            await window.API.checkAuthStatus();
            return true;
        } catch (error) {
            console.error('Auth: Token verification failed:', error);
            return false;
        }
    }
}

window.Auth = new Auth();
console.log('[Auth Module] Exported as window.Auth:', window.Auth);
