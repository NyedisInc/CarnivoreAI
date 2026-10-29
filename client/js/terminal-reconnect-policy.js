
console.log('[TerminalReconnectPolicy Module] Loading...');

(function () {
    'use strict';

    var INIT = {
        READY: 'ready',
        AWAITING: 'awaiting_startup_prompt',
        UNKNOWN: 'unknown'
    };

    var RECOVERY = {
        AUTH: 'refresh_auth',
        BY_NAME: 're_resolve_by_name',
        OUTAGE: 'wait_for_server',
        RETRY: 'retry_same_id',
        NONE: 'none'
    };

    var BACKOFF_BASE_MS = 1000;

    var BACKOFF_CEILING_MS = 16000;

    function initOutcome(signals) {
        var s = signals || {};
        if (s.bytesSeen) return INIT.READY;
        if (s.socketOpened && s.startupGate === INIT.AWAITING) return INIT.AWAITING;
        return INIT.UNKNOWN;
    }

    function consumesBudget(signals) {
        var s = signals || {};
        if (s.outcome === INIT.READY) return false;
        if (s.outcome === INIT.AWAITING) return false;
        return s.socketOpened !== true;
    }

    function backoffMs(attemptsSinceProgress) {
        var n = (typeof attemptsSinceProgress === 'number' && attemptsSinceProgress > 0)
            ? attemptsSinceProgress : 1;
        return Math.min(BACKOFF_BASE_MS * Math.pow(2, n - 1), BACKOFF_CEILING_MS);
    }

    function recoveryFor(signals) {
        var s = signals || {};
        if (s.intentional) return RECOVERY.NONE;
        if (s.code === 4404) {
            return s.byNameAlreadyTried ? RECOVERY.RETRY : RECOVERY.BY_NAME;
        }
        if ((s.code === 4401 || s.socketOpened === false) && !s.authProbeAlreadyTried) {
            return RECOVERY.AUTH;
        }
        if (s.outageCodeKnown) return RECOVERY.OUTAGE;
        return RECOVERY.RETRY;
    }

    window.TerminalReconnectPolicy = {
        INIT: INIT,
        RECOVERY: RECOVERY,
        BACKOFF_BASE_MS: BACKOFF_BASE_MS,
        BACKOFF_CEILING_MS: BACKOFF_CEILING_MS,
        initOutcome: initOutcome,
        consumesBudget: consumesBudget,
        backoffMs: backoffMs,
        recoveryFor: recoveryFor
    };
})();

console.log('[TerminalReconnectPolicy Module] Exported as window.TerminalReconnectPolicy');
