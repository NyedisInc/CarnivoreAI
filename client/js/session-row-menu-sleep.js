
console.log('[SessionRowMenuSleep Module] Loading...');

(function () {
    function tr(key, params) {
        var i18n = globalThis.CloudeI18n;
        return (i18n && typeof i18n.t === 'function') ? i18n.t(key, params) : key;
    }

    function say(ctx, text) {
        var actions = window.SessionRowMenuActions;
        if (actions && typeof actions.say === 'function') { actions.say(ctx, text); return; }
        console.warn('[SessionRowMenuSleep]', text);
    }

    async function refresh() {
        var bar = window.SessionSidebar;
        if (bar && typeof bar._fetchAndRender === 'function') {
            bar._lastSig = null;
            await bar._fetchAndRender();
        }
    }

    function releaseThisTab(ctx) {
        var tc = window.TerminalController;
        var bar = window.SessionSidebar;
        if (!tc || !bar || bar._activeTmuxName !== ctx.name) return;
        tc.sessionActive = false;
        if (typeof tc.stopReconnecting === 'function') tc.stopReconnecting();
        if (tc.ws) {
            tc._intentionalClose = true;
            tc.ws.close();
            tc.ws = null;
        }
        window.dispatchEvent(new CustomEvent('cloude:primary-session-gone', { detail: { tmuxName: ctx.name } }));
    }

    function reasonOf(err) {
        return (err && err.message) || 'the server could not be reached';
    }

    async function runSleep(ctx) {
        var name = ctx.label || ctx.name;
        if (!ctx.sessionUuid) { say(ctx, tr('session.sleep.no_uuid')); return; }
        try {
            var res = await window.API.sleepSession(ctx.sessionUuid);
            if (!res || res.status !== 'asleep') {
                say(ctx, tr('session.sleep.failed', { name: name, reason: (res && res.detail) || '' }));
            } else {
                releaseThisTab(ctx);
            }
        } catch (err) {
            console.error('[SessionRowMenuSleep] sleep failed:', err);
            say(ctx, tr('session.sleep.failed', { name: name, reason: reasonOf(err) }));
        }
        await refresh();
    }

    var WRAPPER_NEEDED = 'wrapper_needed';

    var TRANSCRIPT_MISSING = 'transcript_missing';

    async function offerFresh(name, label, sessionUuid) {
        var ok = await window.App.showConfirmModal(
            tr('session.wake.fresh.title'),
            tr('session.wake.fresh.question', { name: label || name }),
            tr('session.wake.fresh.details'),
            tr('session.wake.fresh.confirm'),
            tr('session.wake.fresh.cancel')
        );
        if (!ok) return null;
        return await window.API.wakeSession(sessionUuid, null, null, true);
    }

    /* could not */
    async function pickAndWake(name, label, sessionUuid) {
        var picker = window.SessionRestartPicker;
        if (!picker || typeof picker.open !== 'function') return null;
        var choice = await picker.open(name, label, null, sessionUuid);
        if (!choice || !choice.agentType) return null;
        return await window.API.wakeSession(sessionUuid, choice.agentType, choice.account);
    }

    async function runWake(ctx) {
        var name = ctx.label || ctx.name;
        var started = false;
        if (!ctx.sessionUuid) { say(ctx, tr('session.wake.no_uuid')); return false; }
        var nav = window.NavigationGeneration
            ? window.NavigationGeneration.begin('wake:' + ctx.name) : null;
        try {
            var res = await window.API.wakeSession(ctx.sessionUuid);
            var picker = window.SessionRestartPicker;
            if (res && res.status === 'refused' && res.code === WRAPPER_NEEDED && picker) {
                var picked = await pickAndWake(ctx.name, name, ctx.sessionUuid);
                if (!picked) {
                    // could not
                    var why = typeof picker.lastError === 'function' ? picker.lastError() : '';
                    if (why) say(ctx, tr('session.wake.failed', { name: name, reason: why }));
                    await refresh();
                    return false;
                }
                res = picked;
            }
            if (res && res.status === 'refused' && res.code === TRANSCRIPT_MISSING) {
                res = (await offerFresh(ctx.name, name, ctx.sessionUuid)) || res;
            }
            started = !!res && res.status === 'started';
            if (!started) {
                say(ctx, tr('session.wake.failed', { name: name, reason: (res && res.detail) || '' }));
            }
        } catch (err) {
            console.error('[SessionRowMenuSleep] wake failed:', err);
            say(ctx, tr('session.wake.failed', { name: name, reason: reasonOf(err) }));
        }
        await refresh();
        if (started && window.WakeFocus) void window.WakeFocus.afterWake(ctx.sessionUuid, nav);
        return started;
    }

    async function runKillAsleep(ctx) {
        var name = ctx.label || ctx.name;
        if (!ctx.sessionUuid) { say(ctx, tr('session.wake.no_uuid')); return false; }
        var ok = await window.App.showConfirmModal(
            tr('session.kill_asleep.title'),
            tr('session.kill_asleep.question', { name: name }),
            tr('session.kill_asleep.details'),
            tr('session.kill_asleep.confirm'),
            tr('session.kill_asleep.cancel'),
            'danger'
        );
        if (!ok) return false;
        var done = false;
        try {
            await window.API.killAsleepSession(ctx.sessionUuid);
            done = true;
        } catch (err) {
            console.error('[SessionRowMenuSleep] kill asleep failed:', err);
            say(ctx, tr('session.kill_asleep.failed', { name: name, reason: reasonOf(err) }));
        }
        await refresh();
        return done;
    }

    async function runReopen(ctx) {
        var name = ctx.label || ctx.name;
        if (!ctx.sessionUuid) { say(ctx, tr('session.wake.no_uuid')); return false; }
        var nav = window.NavigationGeneration
            ? window.NavigationGeneration.begin('reopen:' + ctx.name) : null;
        var started = false;
        try {
            await window.API.restartSession(ctx.sessionUuid);
            started = true;
        } catch (err) {
            console.error('[SessionRowMenuSleep] reopen failed:', err);
            say(ctx, tr('session.reopen.failed', { name: name, reason: reasonOf(err) }));
        }
        await refresh();
        if (started && window.WakeFocus) void window.WakeFocus.afterWake(ctx.sessionUuid, nav);
        return started;
    }

    async function runArchive(ctx) {
        if (!ctx.sessionUuid) { say(ctx, tr('session.archive.failed.no_id')); return false; }
        var done = false;
        try {
            await window.API.deleteSessionRecord(ctx.sessionUuid);
            done = true;
        } catch (err) {
            console.error('[SessionRowMenuSleep] archive failed:', err);
            say(ctx, tr('session.archive.failed', { reason: reasonOf(err) }));
        }
        await refresh();
        return done;
    }

    window.SessionRowMenuSleep = {
        runSleep: runSleep, runWake: runWake, runKillAsleep: runKillAsleep, pickAndWake: pickAndWake, offerFresh: offerFresh,
        runReopen: runReopen, runArchive: runArchive,
        releaseThisTab: releaseThisTab, WRAPPER_NEEDED: WRAPPER_NEEDED,
    };
})();

console.log('[SessionRowMenuSleep Module] Exported as window.SessionRowMenuSleep');
