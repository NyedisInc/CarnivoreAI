/*  hidden  display: none */
(function (global) {
    'use strict';

    var CLAWD_ROWS = [' ▐▛███▛█ ', '▝▜██████▀', ' ▝▝   ▝▝ '];
    var WIDTH = 9;
    var HEIGHT = 3;
    var COLOUR_PROBE = [1, 0, 1];
    var VIEW_SCAN = 12;
    var THROTTLE_MS = 250;
    var SAFE_NAME_RE = /^[A-Za-z0-9_][A-Za-z0-9_.-]{0,95}$/;
    var SPRITE_EXTENSIONS = ['.svg', '.png', '.webp', '.gif', '.jpg', '.jpeg', '.avif'];

    /** @type {WeakMap<object, object>} per terminal client -> its state. */
    var states = new WeakMap();

    function matchAt(buffer, line, col) {
        var colour = null;
        for (var r = 0; r < HEIGHT; r++) {
            var l = buffer.getLine(line + r);
            if (!l) return false;
            if (l.translateToString(false).substr(col, WIDTH) !== CLAWD_ROWS[r]) return false;
            var cell = l.getCell(col + COLOUR_PROBE[r]);
            if (!cell || cell.getFgColorMode() === 0) return false;
            var key = cell.getFgColorMode() + ':' + cell.getFgColor();
            if (colour === null) colour = key;
            else if (colour !== key) return false;
        }
        return true;
    }

    function findClawd(buffer) {
        var top = buffer.viewportY || 0;
        var last = Math.min(buffer.length - HEIGHT, top + VIEW_SCAN);
        for (var y = top; y <= last; y++) {
            var mid = buffer.getLine(y + 1);
            if (!mid) continue;
            var text = mid.translateToString(false);
            for (var c = text.indexOf(CLAWD_ROWS[1]); c !== -1; c = text.indexOf(CLAWD_ROWS[1], c + 1)) {
                if (matchAt(buffer, y, c)) return { line: y, col: c };
            }
        }
        return null;
    }

    function mascotUrlFor(manifest) {
        var name = manifest && manifest.mascot;
        if (typeof name !== 'string' || !SAFE_NAME_RE.test(name) || name.indexOf('..') !== -1) return null;
        var lower = name.toLowerCase();
        if (!SPRITE_EXTENSIONS.some(function (e) { return lower.slice(-e.length) === e; })) return null;
        var base = manifest.source === 'user' ? '/themes/' : '/static/css/themes/';
        return base + encodeURIComponent(manifest.id) + '/' + encodeURIComponent(name);
    }

    function backingFor(manifest) {
        var parse = global.TerminalBackgroundOpacity && global.TerminalBackgroundOpacity.parseCssColorChannels;
        var ch = parse && manifest && manifest.xterm ? parse(manifest.xterm.background) : null;
        return ch ? 'rgb(' + ch.r + ', ' + ch.g + ', ' + ch.b + ')' : null;
    }

    function altText() {
        var i18n = global.CloudeI18n;
        return i18n && typeof i18n.t === 'function' ? i18n.t('terminal.mascot.alt') : '';
    }

    function removeOverlay(st) {
        var o = st.overlay;
        st.overlay = null;
        if (o && o.el && o.el.parentNode) o.el.parentNode.removeChild(o.el);
    }

    function onScreen(st, o) {
        var row = o.line - (st.term.buffer.active.viewportY || 0);
        return row >= 0 && row + HEIGHT <= st.term.rows;
    }

    function position(st) {
        var o = st.overlay;
        var term = st.term;
        var row = o.line - (term.buffer.active.viewportY || 0);
        o.el.style.left = (o.col / term.cols * 100) + '%';
        o.el.style.top = (row / term.rows * 100) + '%';
        o.el.style.width = (WIDTH / term.cols * 100) + '%';
        o.el.style.height = (HEIGHT / term.rows * 100) + '%';
    }

    function place(st, hit) {
        var screen = st.term.element && st.term.element.querySelector('.xterm-screen');
        if (!screen) return;
        var el = global.document.createElement('div');
        el.className = 'terminal-mascot';
        el.style.backgroundImage = 'url("' + st.url + '")';
        if (st.backing) el.style.backgroundColor = st.backing;
        el.setAttribute('role', 'img');
        el.setAttribute('aria-label', altText());
        screen.appendChild(el);
        st.overlay = { el: el, line: hit.line, col: hit.col };
        position(st);
    }

    function tick(st) {
        try {
            var buf = st.term.buffer.active;
            var o = st.overlay;
            if (o && (!o.el.isConnected || !onScreen(st, o) || !matchAt(buf, o.line, o.col))) {
                removeOverlay(st);
                o = null;
            }
            if (o) { position(st); return; }
            var hit = findClawd(buf);
            if (hit) place(st, hit);
        } catch (e) {
            removeOverlay(st);
        }
    }

    function schedule(st) {
        if (st.timer) return;
        st.timer = setTimeout(function () { st.timer = null; tick(st); }, THROTTLE_MS);
    }

    function teardown(st) {
        if (st.timer) clearTimeout(st.timer);
        st.timer = null;
        removeOverlay(st);
        st.listeners.forEach(function (l) {
            try { l.dispose(); } catch (_) {  }
        });
        st.listeners = [];
    }

    function sync(client, manifest) {
        var term = client && client.term;
        var st = states.get(client);
        var url = term ? mascotUrlFor(manifest) : null;
        var backing = url ? backingFor(manifest) : null;
        if (st && (!url || st.term !== term || st.url !== url || st.backing !== backing)) {
            teardown(st);
            states.delete(client);
            st = null;
        }
        if (!url || typeof term.onWriteParsed !== 'function') return;
        if (!st) {
            st = { term: term, url: url, backing: backing, overlay: null, timer: null, listeners: [] };
            st.listeners.push(term.onWriteParsed(function () { schedule(st); }));
            var now = function () { tick(st); };
            if (typeof term.onScroll === 'function') st.listeners.push(term.onScroll(now));
            if (typeof term.onResize === 'function') st.listeners.push(term.onResize(now));
            if (term.buffer && typeof term.buffer.onBufferChange === 'function') {
                st.listeners.push(term.buffer.onBufferChange(now));
            }
            states.set(client, st);
        }
        schedule(st);
    }

    global.TerminalMascot = {
        sync: sync, findClawd: findClawd, mascotUrlFor: mascotUrlFor, CLAWD_ROWS: CLAWD_ROWS
    };
    console.log('[TerminalMascot Module] Exported as window.TerminalMascot');
}(typeof window !== 'undefined' ? window : globalThis));
