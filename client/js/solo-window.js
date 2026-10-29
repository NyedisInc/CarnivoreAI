(function () {
    'use strict';

    var DIGITS = /^\d{1,15}$/;

    function parseSolo(search) {
        var params;
        try {
            params = new URLSearchParams(String(search || ''));
        } catch (e) {
            return null;
        }
        var keys = Array.from(params.keys());
        if (keys.length !== 1 || keys[0] !== 'solo') return null;
        var value = params.get('solo');
        return DIGITS.test(value) ? value : null;
    }

    var row = parseSolo(typeof location === 'undefined' ? '' : location.search);
    if (row !== null && typeof document !== 'undefined') document.documentElement.setAttribute('data-solo', row);

    var boundId = '';
    var ended = false;
    var busy = false;
    var again = false;
    var booted = false;
    var pendingRow = null;
    var stopListing = null;
    var shown = 'null';

    function active() {
        return row !== null;
    }

    function rowId() {
        return row;
    }

    function tr(key, params) {
        var i18n = typeof window !== 'undefined' ? window.CloudeI18n : null;
        return i18n && typeof i18n.t === 'function' ? i18n.t(key, params) : key;
    }

    function bridgeWith(name) {
        var bridge = typeof window !== 'undefined' ? window.carnivoreDesktop : null;
        if (!bridge || !Array.isArray(bridge.capabilities) || bridge.capabilities.indexOf(name) === -1) return null;
        return typeof bridge[name] === 'function' ? bridge : null;
    }

    function findRow(rows, id) {
        if (!Array.isArray(rows)) return null;
        for (var i = 0; i < rows.length; i++) {
            if (rows[i] && String(rows[i].session_row_id) === String(id)) return rows[i];
        }
        return null;
    }

    function pushed(name) {
        var push = globalThis.ListingPush;
        return push && typeof push.rows === 'function' ? push.rows(name) : null;
    }

    function readList() {
        var live = pushed('list');
        if (live) return Promise.resolve(live);
        if (!window.API || typeof window.API.listSessions !== 'function') return Promise.resolve(null);
        return window.API.listSessions().then(function (rows) { return rows; }, function () { return null; });
    }

    function nameOf(info) {
        var inner = (info && info.session) || {};
        return String(inner.label || info.label || info.tmux_session || inner.name || '');
    }

    function setTitle(info) {
        var name = nameOf(info);
        document.title = name ? tr('solo.window.title', { name: name }) : tr('solo.window.title_untitled');
    }

    function panel(state, extra) {
        var web = window.CloudeWeb;
        if (!web) return;
        var props = state === null ? null : Object.assign({ kind: state }, extra || {});
        var key = JSON.stringify(props);
        if (key === shown) return;
        shown = key;
        if (props === null) {
            if (typeof web.hideSoloPanel === 'function') web.hideSoloPanel();
        } else if (typeof web.showSoloPanel === 'function') {
            web.showSoloPanel(props);
        }
    }

    /* navigation generation */
    function bind(info, rebind) {
        var sesId = info.session.id;
        var NG = window.NavigationGeneration;
        var nav = NG ? (rebind ? NG.begin('solo:' + row) : NG.current()) : null;
        return window.API.getSession(sesId, { includeScrollback: true, parallelHistory: true, scrollbackLines: window.CloudeTerminal.SCROLLBACK_ROWS }).then(function (full) {
            if (NG && !NG.keep(nav, 'solo bind')) return;
            if (!full || ended) return;
            boundId = sesId;
            panel(null);
            return window.App.returnToExistingTerminal(full);
        });
    }

    function panelFor(id) {
        var records = pushed('records');
        var record = null;
        if (Array.isArray(records)) {
            for (var i = 0; i < records.length; i++) {
                if (records[i] && String(records[i].id) === String(id)) { record = records[i]; break; }
            }
        }
        if (!record) return { state: 'looking', record: null };
        if (record.asleep) return { state: 'asleep', record: record };
        return { state: record.lifecycle === 'stopped' ? 'gone' : 'looking', record: record };
    }

    function resolve() {
        if (row === null || ended) return Promise.resolve();
        if (busy) { again = true; return Promise.resolve(); }
        busy = true;
        return readList().then(function (rows) {
            var info = findRow(rows, row);
            if (info && info.session && info.session.id) {
                setTitle(info);
                if (info.session.id !== boundId) return bind(info, boundId !== '');
                return undefined;
            }
            if (rows === null) return undefined;
            var need = panelFor(row);
            panel(need.state, {
                name: boundId ? document.title : '',
                sessionUuid: need.record ? need.record.session_uuid : '',
                agentType: need.record ? need.record.agent_type || '' : '',
            });
            return undefined;
        }).catch(function (err) {
            console.warn('[SoloWindow] resolve failed', err && err.message);
        }).then(function () {
            busy = false;
            if (again) { again = false; return resolve(); }
            return undefined;
        });
    }

    function onBoot(app) {
        booted = true;
        if (row === null) {
            if (pendingRow !== null) setTimeout(flushPending, 0);
            return false;
        }
        app.showLaunchpad = function () {  };
        if (window.AppBootComplete) window.AppBootComplete.announce();
        panel('looking');
        var push = globalThis.ListingPush;
        if (push && typeof push.onChange === 'function' && !stopListing) {
            stopListing = push.onChange(function () { resolve(); });
        }
        resolve();
        return true;
    }

    function onDestroyed(event) {
        if (row === null) return;
        event.stopImmediatePropagation();
        ended = true;
        panel('ended');
    }

    function showRowInMain(id) {
        var NG = window.NavigationGeneration;
        return readList().then(function (rows) {
            var info = findRow(rows, id);
            if (!info || !info.session) return undefined;
            var nav = NG ? NG.begin('show-row:' + id) : null;
            return window.API.getSession(info.session.id, { includeScrollback: true, parallelHistory: true, scrollbackLines: window.CloudeTerminal.SCROLLBACK_ROWS }).then(function (full) {
                if (NG && !NG.keep(nav, 'show row')) return undefined;
                return full ? window.App.returnToExistingTerminal(full) : undefined;
            });
        }).catch(function (err) {
            console.warn('[SoloWindow] show row failed', err && err.message);
        });
    }

    function flushPending() {
        var id = pendingRow;
        pendingRow = null;
        if (id !== null) showRowInMain(id);
    }

    function onMessage(event) {
        var data = event && event.data;
        if (row !== null || event.source !== window || event.origin !== location.origin) return;
        if (!data || data.type !== 'carnivore.show-row' || !DIGITS.test(String(data.row_id))) return;
        if (booted) showRowInMain(String(data.row_id));
        else pendingRow = String(data.row_id);
    }

    function focusIfOpen(sesId) {
        var bridge = bridgeWith('focusSessionWindow');
        if (!bridge || row !== null) return Promise.resolve(false);
        var info = null;
        var rows = pushed('list') || [];
        for (var i = 0; i < rows.length; i++) {
            if (rows[i] && rows[i].session && rows[i].session.id === sesId) { info = rows[i]; break; }
        }
        if (!info || info.session_row_id === null || info.session_row_id === undefined) return Promise.resolve(false);
        return Promise.resolve(bridge.focusSessionWindow(String(info.session_row_id))).then(function (took) { return !!took; }, function () { return false; });
    }

    function forwardToMain(info) {
        var bridge = bridgeWith('showInMain');
        var id = info && info.session_row_id;
        if (bridge && id !== null && id !== undefined) bridge.showInMain(String(id));
        else console.warn('[SoloWindow] no way to show that session in the main window');
        return true;
    }

    if (typeof window !== 'undefined') {
        window.addEventListener('session-destroyed', onDestroyed);
        window.addEventListener('message', onMessage);
    }

    var api = {
        active: active,
        rowId: rowId,
        parseSolo: parseSolo,
        findRow: findRow,
        onBoot: onBoot,
        focusIfOpen: focusIfOpen,
        forwardToMain: forwardToMain,
    };
    if (typeof window !== 'undefined') window.SoloWindow = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
}());
