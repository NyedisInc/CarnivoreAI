
const SERVER_RESTART_WATCH_DEFAULTS = Object.freeze({
    healthPath: '/health',
    firstDelayMs: 500,
    maxDelayMs: 5000,
    backoffFactor: 1.6,
    ceilingMs: 120000,
    probeTimeoutMs: 4000,
    offlineRecheckMs: 1000,
});

/* header present */
const RESTART_EXCLUDED_CLOSE_CODES = Object.freeze([4400, 4401, 4404]);

const SERVER_RESTART_RESULT = Object.freeze({
    UP: 'up',
    ABORTED: 'aborted',
    TIMEOUT: 'timeout',
});

const SERVER_RESTART_STATUS = Object.freeze({
    WAITING: 'No answer from server, retrying...',
    OFFLINE: 'No network connection, waiting...',
    BACK: 'Server reachable, restoring session...',
    UNREACHABLE: 'Cannot reach server',
});

class ServerRestartWatch {
    constructor(options = {}) {
        const cfg = Object.assign({}, SERVER_RESTART_WATCH_DEFAULTS, options || {});

        this.healthPath = cfg.healthPath;
        this.firstDelayMs = cfg.firstDelayMs;
        this.maxDelayMs = cfg.maxDelayMs;
        this.backoffFactor = cfg.backoffFactor;
        this.ceilingMs = cfg.ceilingMs;
        this.probeTimeoutMs = cfg.probeTimeoutMs;
        this.offlineRecheckMs = cfg.offlineRecheckMs;

        const g = (typeof globalThis !== 'undefined') ? globalThis : {};
        this._fetch = cfg.fetchImpl
            || (typeof g.fetch === 'function' ? g.fetch.bind(g) : null);
        this._setTimeout = cfg.setTimeoutImpl || ((fn, ms) => setTimeout(fn, ms));
        this._clearTimeout = cfg.clearTimeoutImpl || ((id) => clearTimeout(id));
        this._now = cfg.nowImpl || (() => Date.now());
        this._isOnline = cfg.onlineImpl || (() => {
            const nav = (typeof g.navigator !== 'undefined') ? g.navigator : null;
            return !(nav && nav.onLine === false);
        });
        this._origin = (typeof cfg.origin === 'string')
            ? cfg.origin
            : ((typeof window !== 'undefined' && window.location && window.location.origin)
                ? window.location.origin : '');

        this.active = false;
    }

    static isOutageCloseCode(closeCode) {
        if (typeof closeCode !== 'number') return false;
        return RESTART_EXCLUDED_CLOSE_CODES.indexOf(closeCode) === -1;
    }

    isClientOffline() {
        try {
            return this._isOnline() === false;
        } catch (err) {
            console.debug('[RestartWatch] online check failed:', err && err.message);
            return false;
        }
    }

    healthUrl() {
        return `${this._origin}${this.healthPath}`;
    }

    async probe() {
        if (typeof this._fetch !== 'function') return false;

        let controller = null;
        let timer = null;
        const g = (typeof globalThis !== 'undefined') ? globalThis : {};
        if (typeof g.AbortController === 'function') {
            controller = new g.AbortController();
            timer = this._setTimeout(() => {
                try {
                    controller.abort();
                } catch (err) {
                    console.debug('[RestartWatch] probe abort failed:', err && err.message);
                }
            }, this.probeTimeoutMs);
        }

        try {
            const init = { method: 'GET', cache: 'no-store' };
            if (controller) init.signal = controller.signal;
            const res = await this._fetch(this.healthUrl(), init);
            return !!(res && res.ok);
        } catch (err) {
            console.debug('[RestartWatch] health probe failed:',
                err && (err.name || 'Error'), err && err.message);
            return false;
        } finally {
            if (timer !== null && timer !== undefined) this._clearTimeout(timer);
        }
    }

    async waitForServer(hooks = {}) {
        const shouldAbort = (hooks && typeof hooks.shouldAbort === 'function')
            ? hooks.shouldAbort : () => false;
        const onAttempt = (hooks && typeof hooks.onAttempt === 'function')
            ? hooks.onAttempt : () => {};

        const startedAt = this._now();
        let delay = this.firstDelayMs;
        let attempt = 0;
        let offlineMs = 0;

        this.active = true;
        try {
            for (;;) {
                if (shouldAbort()) return SERVER_RESTART_RESULT.ABORTED;

                const offline = this.isClientOffline();
                attempt += 1;
                onAttempt({
                    attempt,
                    elapsedMs: (this._now() - startedAt) - offlineMs,
                    clientOffline: offline,
                });

                if (offline) {
                    await this._sleep(this.offlineRecheckMs);
                    offlineMs += this.offlineRecheckMs;
                    continue;
                }

                if (await this.probe()) return SERVER_RESTART_RESULT.UP;
                if (shouldAbort()) return SERVER_RESTART_RESULT.ABORTED;

                if (((this._now() - startedAt) - offlineMs) + delay >= this.ceilingMs) {
                    return SERVER_RESTART_RESULT.TIMEOUT;
                }

                await this._sleep(delay);
                delay = Math.min(Math.round(delay * this.backoffFactor), this.maxDelayMs);
            }
        } finally {
            this.active = false;
        }
    }

    _sleep(ms) {
        return new Promise((resolve) => { this._setTimeout(resolve, ms); });
    }
}

ServerRestartWatch.DEFAULTS = SERVER_RESTART_WATCH_DEFAULTS;
ServerRestartWatch.EXCLUDED_CLOSE_CODES = RESTART_EXCLUDED_CLOSE_CODES;
ServerRestartWatch.RESULT = SERVER_RESTART_RESULT;
ServerRestartWatch.STATUS = SERVER_RESTART_STATUS;

window.ServerRestartWatch = ServerRestartWatch;
console.log('[ServerRestartWatch Module] Exported as window.ServerRestartWatch');
