
console.log('[TerminalKeyBar Module] Loading...');

(function (global) {
    'use strict';

    var BAR_ID = 'terminal-key-bar';

    var HOST_ID = 'terminal-screen';

    var ROWS_KEY = 'cloude.keybar.rows';

    var SWIPE_PX = 20;

    var FLICK_SPEED = 0.5;

    var SEQUENCE_FOR = {
        esc: 'ESC',
        tab: 'TAB',
        up: 'UP',
        down: 'DOWN',
        left: 'LEFT',
        right: 'RIGHT',
        shifttab: 'SHIFT_TAB',
        enter: 'ENTER',
        undo: 'UNDO',
        stash: 'STASH'
    };

    var GLYPHS = {
        enter: '<path d="M16 4v6a2 2 0 0 1-2 2H4M7.5 8.5L4 12l3.5 3.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
        undo: '<path d="M7 4.5L3.5 8 7 11.5M3.5 8H12a4 4 0 0 1 0 8H8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
        up: '<path d="M10 15V5M5 10l5-5 5 5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
        down: '<path d="M10 5v10M5 10l5 5 5-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
        left: '<path d="M15 10H5M10 5l-5 5 5 5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
        right: '<path d="M5 10h10M10 5l5 5-5 5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
        paste: '<path d="M6.5 4.5h-1a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-10a1 1 0 0 0-1-1h-1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>'
            + '<rect x="6.5" y="2.8" width="7" height="3.4" rx="1" stroke="currentColor" stroke-width="1.5"/>',
        agent: '<rect x="3.5" y="5" width="13" height="10.5" rx="2.6" stroke="currentColor" stroke-width="1.5"/>'
            + '<path d="M10 2.6v2.4M2.6 9.2v2.6M17.4 9.2v2.6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>'
            + '<circle cx="10" cy="2" r="1.05" fill="currentColor"/>'
            + '<circle cx="7.4" cy="9.4" r="1.15" fill="currentColor"/>'
            + '<circle cx="12.6" cy="9.4" r="1.15" fill="currentColor"/>'
            + '<path d="M7.6 12.6h4.8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>'
            + '<rect x="7.5" y="2.5" width="5" height="3" rx="1" stroke="currentColor" stroke-width="1.5"/>'
    };

    var barEl = null;

    var rowEls = [];

    var rowsOpen = false;

    var warnedNoCatalog = false;

    function accessor() {
        var i18n = global.CloudeI18n;
        if (i18n && typeof i18n.t === 'function') {
            return function (key, params) { return i18n.t(key, params); };
        }
        var parsing = typeof document !== 'undefined' && document.readyState === 'loading';
        if (!warnedNoCatalog && !parsing) {
            warnedNoCatalog = true;
            console.error(
                '[TerminalKeyBar] no string layer on globalThis.CloudeI18n; '
                + 'rendering catalog keys. Is client/js/i18n/boot.js loaded?');
        }
        return function (key) { return key; };
    }

    /* does not exist yet */
    function labels() {
        var shared = global.CloudeLabels;
        if (shared && typeof shared.terminalKeyBarLabels === 'function') {
            return shared.terminalKeyBarLabels(accessor());
        }
        return { label: accessor()('terminal.keybar.label'), keys: [] };
    }

    function sharedIcon(name) {
        var web = global.CloudeWeb;
        var svg = web && typeof web.iconSvg === 'function' ? web.iconSvg(name, 20) : '';
        if (svg) return svg;
        var glyphs = global.CloudeGlyphs;
        return glyphs && typeof glyphs.glyphSvg === 'function' ? glyphs.glyphSvg(name, 20) : '';
    }

    function buildKey(entry) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'terminal-key-bar__key';
        btn.dataset.keyBarAction = entry.action;
        btn.setAttribute('aria-label', entry.hint);
        if (!entry.quiet) btn.setAttribute('title', entry.hint);
        if (entry.action === 'paste') btn.setAttribute('aria-haspopup', 'menu');
        if (entry.glyph && GLYPHS[entry.glyph]) {
            btn.innerHTML = '<svg width="20" height="20" viewBox="0 0 20 20"'
                + ' fill="none" aria-hidden="true">'
                + GLYPHS[entry.glyph] + '</svg>';
        } else if (entry.glyph && sharedIcon(entry.glyph)) {
            btn.innerHTML = sharedIcon(entry.glyph);
        } else {
            btn.textContent = entry.text || '';
        }
        return btn;
    }

    function paint() {
        if (!barEl) return;
        var copy = labels();
        barEl.setAttribute('aria-label', copy.label);
        barEl.textContent = '';
        rowEls = [1, 2].map(function (n) {
            var row = document.createElement('div');
            row.className = 'terminal-key-bar__row';
            row.dataset.row = String(n);
            barEl.appendChild(row);
            return row;
        });
        copy.keys.forEach(function (entry) {
            rowEls[entry.row === 2 ? 1 : 0].appendChild(buildKey(entry));
        });
        applyOpen();
    }

    function activeName() {
        var bar = global.SessionSidebar;
        return (bar && bar._activeTmuxName) || null;
    }

    /* failed to load */
    function call(owner, method, args) {
        if (!owner || typeof owner[method] !== 'function') {
            console.warn('[TerminalKeyBar] destination unavailable:', method);
            return false;
        }
        owner[method].apply(owner, args || []);
        return true;
    }

    var DESTINATIONS = {
        search: function () { return call(global.CloudeWeb, 'toggleTerminalSearch'); },
        notes: function () { return call(global.CloudeWeb, 'toggleSessionNotes'); },
        files: function (anchor) {
            return call(global.ConfigEditorLoader, 'toggleWhenReady', [anchor]);
        },
        theme: function (anchor) { return call(global.SessionThemeMenu, 'open', [anchor]); },
        sleep: function () {
            var name = activeName();
            var members = global.SessionSidebarGroupMembership;
            if (!name) return false;
            return call(global.SessionRowMenuSleep, 'runSleep', [{
                name: name,
                label: name,
                sessionUuid: members && members.uuidOfName ? members.uuidOfName(name) : null
            }]);
        },
        coffee: function () {
            var name = activeName();
            var store = global.CloudeWeb && global.CloudeWeb.autoSleep;
            if (!name || !store) return false;
            var on = store.isKeptAwake(name);
            if (on === null) return false;
            store.setKeepAwake(name, !on);
            return true;
        }
    };

    function syncCoffee() {
        var btn = rowEls[1] && rowEls[1].children
            ? Array.prototype.filter.call(rowEls[1].children, function (c) {
                return c.dataset.keyBarAction === 'coffee';
            })[0]
            : null;
        var store = global.CloudeWeb && global.CloudeWeb.autoSleep;
        var name = activeName();
        if (!btn || !store || !name) return;
        var on = store.isKeptAwake(name);
        if (on === null) { btn.removeAttribute('aria-pressed'); return; }
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    }

    /* failed to load */
    function press(action, anchor) {
        if (action === 'slash') {
            var modal = global.SlashCommandsModal;
            if (!modal || typeof modal.open !== 'function') {
                console.warn('[TerminalKeyBar] no slash command modal to open');
                return false;
            }
            modal.open();
            return true;
        }

        if (action === 'paste') {
            var tools = global.TerminalToolsMenu;
            if (!tools || typeof tools.toggle !== 'function') {
                console.warn('[TerminalKeyBar] terminal tools menu unavailable');
                return false;
            }
            tools.toggle(anchor || null);
            return true;
        }

        if (DESTINATIONS[action]) return DESTINATIONS[action](anchor || null);

        var name = SEQUENCE_FOR[action];
        if (!name) {
            console.warn('[TerminalKeyBar] unknown key', action);
            return false;
        }
        var keys = global.DPad;
        if (!keys || typeof keys.sendKey !== 'function') {
            console.warn('[TerminalKeyBar] no key sender for', action);
            return false;
        }
        keys.sendKey(name);
        return true;
    }

    function storedOpen() {
        try { return global.localStorage.getItem(ROWS_KEY) === '2'; } catch (err) { return false; }
    }

    function applyOpen() {
        if (!barEl) return;
        barEl.dataset.open = rowsOpen ? '1' : '0';
        if (rowEls[1]) rowEls[1].inert = !rowsOpen;
        if (rowsOpen) syncCoffee();
    }

    function setOpen(next, persist) {
        next = !!next;
        if (next === rowsOpen) return;
        rowsOpen = next;
        applyOpen();
        if (persist) {
            try { global.localStorage.setItem(ROWS_KEY, rowsOpen ? '2' : '1'); } catch (err) {  }
        }
    }

    function wireSwipe() {
        var drag = null;
        var swallowClick = false;
        function decide(dy, dx) {
            if (Math.abs(dy) < Math.abs(dx)) return false;
            drag.done = true;
            swallowClick = true;
            setOpen(dy < 0, true);
            return true;
        }
        barEl.addEventListener('pointerdown', function (e) {
            swallowClick = false;
            drag = { id: e.pointerId, x: e.clientX, y: e.clientY, t: Date.now(), done: false };
        });
        barEl.addEventListener('pointermove', function (e) {
            if (!drag || drag.done || e.pointerId !== drag.id) return;
            var dy = e.clientY - drag.y;
            if (Math.abs(dy) >= SWIPE_PX) decide(dy, e.clientX - drag.x);
        });
        function end(e) {
            if (drag && !drag.done && e.pointerId === drag.id) {
                var dy = e.clientY - drag.y;
                var dt = Math.max(1, Date.now() - drag.t);
                if (Math.abs(dy) >= 8 && Math.abs(dy) / dt >= FLICK_SPEED) decide(dy, e.clientX - drag.x);
            }
            drag = null;
        }
        barEl.addEventListener('pointerup', end);
        barEl.addEventListener('pointercancel', function () { drag = null; });
        barEl.addEventListener('click', function (e) {
            if (!swallowClick) return;
            swallowClick = false;
            e.stopImmediatePropagation();
            e.preventDefault();
        }, true);
    }

    function mount() {
        if (barEl) return barEl;
        if (typeof document === 'undefined' || !document.getElementById) return null;
        var host = document.getElementById(HOST_ID);
        if (!host) return null;
        barEl = document.createElement('div');
        barEl.id = BAR_ID;
        barEl.setAttribute('role', 'group');
        rowsOpen = storedOpen();
        host.appendChild(barEl);
        paint();
        wireSwipe();
        barEl.addEventListener('click', function (event) {
            var btn = event.target && event.target.closest
                ? event.target.closest('[data-key-bar-action]') : null;
            if (!btn || !barEl.contains(btn)) return;
            event.preventDefault();
            press(btn.dataset.keyBarAction, btn);
        });
        return barEl;
    }

    global.TerminalKeyBar = {
        mount: mount,
        paint: paint,
        press: press,
        setOpen: setOpen,
        isOpen: function () { return rowsOpen; },
        BAR_ID: BAR_ID,
        GLYPHS: GLYPHS,
        SEQUENCE_FOR: SEQUENCE_FOR,
        element: function () { return barEl; }
    };

    mount();

    if (typeof document !== 'undefined' && document.addEventListener) {
        document.addEventListener('DOMContentLoaded', paint);
    }
    if (global.addEventListener) {
        global.addEventListener('cloude:auto-sleep-changed', syncCoffee);
        global.addEventListener('cloude:locale-changed', paint);
        global.addEventListener('carnivore:locale-changed', paint);
    }
}(typeof window !== 'undefined' ? window : globalThis));

console.log('[TerminalKeyBar Module] Exported as window.TerminalKeyBar');
