
console.log('[SessionRowMenuActions Module] Loading...');

(function () {
    'use strict';

    var navSeq = 0;

    ['session-created', 'popstate', 'hashchange'].forEach(function (evt) {
        window.addEventListener(evt, function () { navSeq += 1; });
    });

    function navToken() { return navSeq; }

    function tr(key) {
        var i18n = globalThis.CloudeI18n;
        return (i18n && typeof i18n.t === 'function') ? i18n.t(key) : key;
    }

    function say(ctx, text) {
        var lp = window.Launchpad;
        if (lp && typeof lp.showError === 'function') { lp.showError(text); return; }
        console.warn('[SessionRowMenuActions]', text);
    }

    function rowElementFor(ctx) {
        if (!ctx || !ctx.name || typeof document.querySelector !== 'function') return null;
        return document.querySelector(
            '.session-sidebar-row[data-name="' + CSS.escape(ctx.name) + '"]');
    }

    /* could not be read */
    async function recordFor(tmuxName) {
        if (!tmuxName || !window.API
            || typeof window.API.listSessionRecords !== 'function') return null;
        var rows;
        try {
            rows = await window.API.listSessionRecords();
        } catch (err) {
            console.error('[SessionRowMenuActions] could not read session records:', err);
            return null;
        }
        if (!Array.isArray(rows)) return null;
        var best = null;
        for (var i = 0; i < rows.length; i++) {
            var r = rows[i];
            if (!r || r.tmux_name !== tmuxName) continue;
            if (r.archived_at) continue;
            if (!best) { best = r; continue; }
            var a = typeof r.tmux_created_epoch === 'number' ? r.tmux_created_epoch : -1;
            var b = typeof best.tmux_created_epoch === 'number'
                ? best.tmux_created_epoch : -1;
            if (a > b) best = r;
        }
        return best;
    }

    async function runRenamePrompt(ctx, rowEl) {
        var prompter = window.TextPromptModal;
        var renameId = ctx.sessionId || (ctx.asleep ? ctx.sessionUuid : '');
        if (!renameId || !prompter || typeof prompter.open !== 'function') {
            say(ctx, 'cannot rename "' + (ctx.label || ctx.name)
                + '": no live session id to send the change to');
            return;
        }
        var nameEl = rowEl && rowEl.querySelector('[data-row-name]');
        var shownName = nameEl ? (nameEl.textContent || '').trim() : '';
        var seed = shownName || ctx.label || ctx.name || '';
        var raw = await prompter.open({
            title: 'rename session', label: 'new session label',
            defaultValue: seed, confirmLabel: 'rename', cancelLabel: 'cancel',
        });
        raw = raw === null ? '' : String(raw).trim();
        if (!raw || raw === seed) return;
        var verdict = (window.SessionLabel && window.SessionLabel.validate)
            ? window.SessionLabel.validate(raw)
            : { ok: false, reason: 'the label rule is unavailable' };
        if (!verdict.ok) { say(ctx, verdict.reason); return; }
        try {
            await window.API.renameSession(renameId, verdict.value);
        } catch (error) {
            console.error('[SessionRowMenuActions] rename failed:', error);
            say(ctx, 'rename failed: '
                + ((error && error.message) || 'the server could not be reached'));
        }
    }

    async function runRename(ctx) {
        var rowEl = rowElementFor(ctx);
        //  hidden 
        var shown = rowEl && (typeof rowEl.checkVisibility === 'function'
            ? rowEl.checkVisibility({ visibilityProperty: true })
            : (typeof rowEl.getClientRects !== 'function' || rowEl.getClientRects().length > 0));
        if (!shown) {
            await runRenamePrompt(ctx, rowEl);
            return;
        }
        if (window.SessionSidebarRename
            && typeof window.SessionSidebarRename.beginEdit === 'function') {
            window.SessionSidebarRename.beginEdit(rowEl);
        }
    }

    var FORK_WAKE_POLL_MS = 250;
    var FORK_WAKE_MAX_POLLS = 120;

    function liveRowFor(uuid) {
        var rows = (window.SessionSidebar && window.SessionSidebar._rows) || [];
        for (var i = 0; i < rows.length; i++) {
            var r = rows[i];
            if (r && !r.asleep && r.session_uuid === uuid && r.session_id) return r;
        }
        return null;
    }

    /*  hidden  */
    async function wakeForSessionId(ctx) {
        var sleeper = window.SessionRowMenuSleep;
        if (!ctx.sessionUuid || !sleeper || typeof sleeper.runWake !== 'function') return null;
        if (!(await sleeper.runWake(ctx))) return null;
        for (var i = 0; i < FORK_WAKE_MAX_POLLS; i++) {
            var live = liveRowFor(ctx.sessionUuid);
            if (live) return live.session_id;
            await new Promise(function (resolve) { setTimeout(resolve, FORK_WAKE_POLL_MS); });
        }
        return null;
    }

    async function runFork(ctx) {
        var picker = window.CloudeWeb && window.CloudeWeb.openForkPicker;
        var sessionId = ctx.asleep ? await wakeForSessionId(ctx) : ctx.sessionId;
        if (!sessionId || typeof picker !== 'function') {
            say(ctx, window.CloudeI18n.t('session.fork_to.unavailable'));
            return;
        }
        picker(sessionId, ctx.label || ctx.name);
    }

    async function runNewInFolder(ctx) {
        var lp = window.Launchpad;
        if (!lp || typeof lp.selectProject !== 'function') {
            say(ctx, 'cannot start a session here: the launcher did not load');
            return;
        }
        var record = await recordFor(ctx.name);
        if (!record) {
            say(ctx, 'CANNOT DETERMINE the folder for "' + (ctx.label || ctx.name)
                + '": no stored record for it could be read, so nothing was started');
            return;
        }
        if (!record.working_dir) {
            say(ctx, '"' + (ctx.label || ctx.name) + '" records no folder, so there is '
                + 'nowhere to start a session. nothing was started');
            return;
        }
        await lp.selectProject({
            name: record.title || ctx.label || ctx.name,
            path: record.working_dir,
        });
    }

    /* could not be read */
    async function projectHomePathFor(ctx) {
        if (ctx.projectId != null && window.API
                && typeof window.API.getProjects === 'function') {
            try {
                var projects = await window.API.getProjects();
                if (Array.isArray(projects)) {
                    for (var i = 0; i < projects.length; i++) {
                        var p = projects[i];
                        if (p && p.id === ctx.projectId && p.path) return p.path;
                    }
                }
            } catch (err) {
                console.error('[SessionRowMenuActions] could not read projects:', err);
            }
        }
        var record = await recordFor(ctx.name);
        return (record && record.working_dir) || null;
    }

    /* cannot be determined own project */
    async function runNewTerminalHere(ctx) {
        var web = window.CloudeWeb && window.CloudeWeb.launchpad;
        if (!web || typeof web.createConsoleSession !== 'function') {
            say(ctx, 'cannot start a terminal: the launcher did not load');
            return;
        }
        var path = await projectHomePathFor(ctx);
        if (!path) {
            say(ctx, 'CANNOT DETERMINE the folder for "' + (ctx.label || ctx.name)
                + '": no project or stored record names one, so no terminal was started');
            return;
        }
        await web.createConsoleSession({ workingDir: path });
    }

    function runSchedule(ctx) {
        var web = window.CloudeWeb;
        if (!ctx.sessionUuid || !web || typeof web.scheduleThis !== 'function') {
            say(ctx, 'cannot schedule: the automations page did not load');
            return;
        }
        web.scheduleThis({ kind: 'session', id: ctx.sessionUuid });
    }

    /* cannot be determined */
    async function runShowPath(ctx) {
        var web = window.CloudeWeb;
        if (!web || typeof web.showPath !== 'function') {
            say(ctx, 'cannot show the path: the popup did not load');
            return;
        }
        var record = await recordFor(ctx.name);
        var path = (record && record.working_dir) || await projectHomePathFor(ctx);
        if (!path) {
            say(ctx, 'CANNOT DETERMINE the folder for "' + (ctx.label || ctx.name)
                + '": no stored record or project names one, so nothing was shown');
            return;
        }
        await web.showPath(path, ctx.label || ctx.name);
    }

    /* no conversation id */
    function runCopySessionId(ctx) {
        var compat = window.CopyCompat;
        if (!ctx.conversationId || !compat || typeof compat.copyText !== 'function') {
            say(ctx, tr('session.menu.copy_session_id.failed'));
            return Promise.resolve(false);
        }
        return compat.copyText(ctx.conversationId).then(function (res) {
            if (!res || !res.ok) say(ctx, tr('session.menu.copy_session_id.failed'));
            return !!(res && res.ok);
        });
    }

    async function runToggleMute(ctx) {
        var menu = window.CloudeWeb && window.CloudeWeb.rowMenu;
        var was = !!ctx.muted;
        var want = !was;
        if (menu) menu.setMuteOverride(ctx.name, want);
        var record = await recordFor(ctx.name);
        if (!record || !record.session_uuid) {
            if (menu) menu.setMuteOverride(ctx.name, was);
            say(ctx, 'CANNOT DETERMINE which stored record "' + (ctx.label || ctx.name)
                + '" belongs to, so its notifications were NOT changed');
            return;
        }
        try {
            var res = await window.API.call(
                '/sessions/records/' + encodeURIComponent(record.session_uuid)
                + '/notifications',
                { method: 'PATCH', body: { muted: want } }
            );
            if (menu && res && typeof res.muted === 'boolean') {
                menu.setMuteOverride(ctx.name, res.muted);
            }
        } catch (error) {
            if (menu) menu.setMuteOverride(ctx.name, was);
            console.error('[SessionRowMenuActions] mute write failed:', error);
            say(ctx, 'could not ' + (want ? 'mute' : 'unmute') + ' "'
                + (ctx.label || ctx.name) + '": '
                + ((error && error.message) || 'the server could not be reached')
                + '. nothing was changed');
        }
        repaintSurface(ctx);
    }

    async function runMarkRead(ctx) {
        try {
            await window.API.setSessionUnread(ctx.name, false);
        } catch (error) {
            console.error('[SessionRowMenuActions] mark read failed:', error);
            say(ctx, tr('session.menu.mark_read.failed'));
        }
        repaintSurface(ctx);
    }

    /* and writes nothing */
    async function runReconnectMcp(ctx) {
        if (!ctx.sessionId) {
            say(ctx, tr('mcp.reconnect_failed'));
            return;
        }
        try {
            await window.API.call('/sessions/' + encodeURIComponent(ctx.sessionId) + '/mcp/reconnect',
                { method: 'POST', body: {} });
        } catch (error) {
            console.error('[SessionRowMenuActions] mcp reconnect failed:', error);
            say(ctx, tr('mcp.reconnect_failed') + ': ' + ((error && error.message) || ''));
        }
    }

    async function runClose(ctx) {
        var actions = window.SessionRowActions;
        if (!actions) {
            console.error('[SessionRowMenuActions] SessionRowActions missing, refusing to act');
            return;
        }
        var clicks = window.SessionSidebarClicks;
        if (!clicks) return;
        var btn = document.createElement('button');
        btn.setAttribute(actions.ATTR_ACTION, actions.ACTION_CLOSE);
        btn.setAttribute(actions.ATTR_NAME, ctx.name);
        await clicks.onRowActionClick(window.SessionSidebar, btn);
    }

    function openChild(ctx, child, token, what) {
        if (navToken() !== token) {
            say(ctx, what + ' was created and left where it is: you moved to another '
                + 'session while it was being made, so nothing was switched');
            return;
        }
        window.dispatchEvent(new CustomEvent('session-created', {
            detail: { session: child },
        }));
    }

    function repaintSurface(ctx) {
        var bar = window.SessionSidebar;
        if (bar && typeof bar.repaint === 'function') {
            bar._lastSig = null;
            bar.repaint();
        }
    }

    async function runRestart(ctx, armedByGesture, busyWork, direct) {
        var rowEl = rowElementFor(ctx);
        if (!rowEl) {
            say(ctx, 'cannot restart "' + (ctx.label || ctx.name)
                + '": its row is no longer on screen');
            return;
        }
        var clicks = window.SessionSidebarClicks;
        if (!clicks || typeof clicks.runRestart !== 'function') return;
        await clicks.runRestart(
            window.SessionSidebar, ctx.name, rowEl, ctx.hostKey,
            false, armedByGesture === true, busyWork === true, direct === true);
    }

    function runMoveToGroup(ctx) {
        var groups = window.SessionSidebarGroupActions;
        if (!groups || typeof groups.openPickerFor !== 'function') return;
        var rowEl = rowElementFor(ctx);
        var anchor = rowEl
            ? rowEl.querySelector('[data-row-menu]')
            : null;
        if (!anchor) {
            say(ctx, 'cannot file "' + (ctx.label || ctx.name)
                + '": its row is no longer on screen');
            return;
        }
        groups.openPickerFor(anchor, ctx.name);
    }

    function runAddTo(ctx) {
        var bridge = window.CloudeWeb && window.CloudeWeb.addToMenu;
        if (!bridge) return;
        var rowEl = rowElementFor(ctx);
        var anchor = rowEl ? rowEl.querySelector('[data-row-menu]') : null;
        if (!anchor) {
            say(ctx, 'cannot file "' + (ctx.label || ctx.name)
                + '": its row is no longer on screen');
            return;
        }
        var opts;
        if (ctx.kind === 'layout') {
            if (typeof bridge.openForLayout === 'function') bridge.openForLayout(anchor, ctx.layoutUuid, opts);
            return;
        }
        if (typeof bridge.openForSession === 'function') {
            bridge.openForSession(anchor, ctx.name, ctx.sessionUuid || null, opts);
        }
    }

    function runSendTo(ctx) {
        var bridge = window.CloudeWeb && window.CloudeWeb.sendTo;
        if (!bridge || !ctx.sessionUuid) return;
        var rowEl = rowElementFor(ctx);
        var anchor = rowEl ? rowEl.querySelector('[data-row-menu]') : null;
        if (!anchor) return;
        bridge.openForSession(anchor, {
            sessionUuid: ctx.sessionUuid,
            name: ctx.label || ctx.name,
            projectName: async function () {
                if (ctx.projectId == null || !window.API || typeof window.API.getProjects !== 'function') return null;
                try {
                    var projects = await window.API.getProjects();
                    var hit = Array.isArray(projects) ? projects.find(function (p) { return p && p.id === ctx.projectId; }) : null;
                    return (hit && hit.name) || null;
                } catch (err) {
                    console.error('[SessionRowMenuActions] could not read projects:', err);
                    return null;
                }
            },
        });
    }

    function runMoveToFolder(ctx) {
        var bridge = window.CloudeWeb && window.CloudeWeb.moveToFolder;
        if (!bridge || !ctx.sessionUuid) {
            say(ctx, window.CloudeI18n.t('session.move.unavailable'));
            return;
        }
        bridge.open({ sessionUuid: ctx.sessionUuid, name: ctx.label || ctx.name });
    }

    async function runRemoveFromGroup(ctx) {
        var groups = window.SessionSidebarGroupActions;
        if (!groups || typeof groups.commitAssignment !== 'function') return;
        await groups.commitAssignment(ctx.name, null);
    }

    async function runToggleKeepAwake(ctx) {
        var web = window.CloudeWeb;
        var store = web && web.autoSleep;
        if (!store || typeof store.setKeepAwake !== 'function') return;
        var kept = store.isKeptAwake(ctx.name);
        if (kept === null) return;
        await store.setKeepAwake(ctx.name, !kept);
    }

    async function run(itemId, ctx, opts) {
        if (!ctx) return;
        var browserRun = ctx.kind === 'browser' && window.SessionSidebarBrowsers
            ? window.SessionSidebarBrowsers.runMenuItem(itemId, ctx) : null;
        if (browserRun) return browserRun;
        var layoutRun = ctx.kind === 'layout' && window.SessionSidebarLayouts
            ? window.SessionSidebarLayouts.runMenuItem(itemId, ctx) : null;
        if (layoutRun) return layoutRun;
        if (itemId === 'rename') return runRename(ctx);
        if (itemId === 'move-to-group') return runMoveToGroup(ctx);
        if (itemId === 'add-to' || itemId === 'add-members') return runAddTo(ctx);
        if (itemId === 'send-to') return runSendTo(ctx);
        if (itemId === 'move-to-folder') return runMoveToFolder(ctx);
        if (itemId === 'remove-from-group') return runRemoveFromGroup(ctx);
        if (itemId === 'restart') return runRestart(ctx);
        if (itemId === 'restart-now') {
            var rowMenu = window.CloudeWeb && window.CloudeWeb.rowMenu;
            if (!rowMenu || !rowMenu.shiftHeld()) return runRestart(ctx);
            return runRestart(ctx, false, false, true);
        }
        if (itemId === 'update-restart') {
            return runRestart(ctx, !!(opts && opts.armedByGesture === true),
                ctx.updateBusy === true);
        }
        if (itemId === 'fork') return runFork(ctx);
        if (itemId === 'new-in-folder') return runNewInFolder(ctx);
        if (itemId === 'new-terminal-here') return runNewTerminalHere(ctx);
        if (itemId === 'show-path') return runShowPath(ctx);
        if (itemId === 'copy-session-id') return runCopySessionId(ctx);
        if (itemId === 'mute') return runToggleMute(ctx);
        if (itemId === 'mark-read') return runMarkRead(ctx);
        if (itemId === 'reconnect-mcp') return runReconnectMcp(ctx);
        if (itemId === 'schedule') return runSchedule(ctx);
        if (itemId === 'keep-awake') return runToggleKeepAwake(ctx);
        var sleeper = window.SessionRowMenuSleep;
        if (itemId === 'close' && ctx.asleep && sleeper) return sleeper.runKillAsleep(ctx);
        if (itemId === 'close') return runClose(ctx);
        if (itemId === 'sleep' && sleeper) return sleeper.runSleep(ctx);
        if (itemId === 'wake' && sleeper) return sleeper.runWake(ctx);
        if (itemId === 'reopen' && sleeper) return sleeper.runReopen(ctx);
        if (itemId === 'archive' && sleeper) return sleeper.runArchive(ctx);
        return runPluginItem(itemId, ctx);
    }

    function runPluginItem(itemId, ctx) {
        var bridge = window.CloudeWeb && window.CloudeWeb.rowMenu;
        if (!bridge || typeof bridge.runPlugin !== 'function') {
            return Promise.resolve(false);
        }
        return bridge.runPlugin(itemId, ctx);
    }

    window.SessionRowMenuActions = {
        run: run,
        navToken: navToken,
        recordFor: recordFor,
        rowElementFor: rowElementFor,
        runRename: runRename,
        runRestart: runRestart,
        runPluginItem: runPluginItem,
        runMoveToGroup: runMoveToGroup,
        runAddTo: runAddTo,
        runSendTo: runSendTo,
        runFork: runFork,
        runNewInFolder: runNewInFolder,
        runNewTerminalHere: runNewTerminalHere,
        runToggleMute: runToggleMute,
        runSchedule: runSchedule,
        runCopySessionId: runCopySessionId,
        runClose: runClose,
        repaintSurface: repaintSurface,
        say: say,
    };
})();

console.log('[SessionRowMenuActions Module] Exported as window.SessionRowMenuActions');
