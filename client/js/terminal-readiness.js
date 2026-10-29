
console.log('[TerminalReadiness Module] Loading...');

(function (global) {
    'use strict';

    var BOUND_MS = 500;

    var RETRY_MS = 16;

    async function measure(controller, opts) {
        var o = opts || {};
        var bound = typeof o.boundMs === 'number' ? o.boundMs : BOUND_MS;
        var gap = typeof o.retryMs === 'number' ? o.retryMs : RETRY_MS;
        var now = typeof o.now === 'function' ? o.now : function () { return Date.now(); };
        var started = now();
        var attempts = 0;
        var reason = 'no-metrics';

        var metrics = global.TerminalMetrics;
        if (!metrics || typeof metrics.guardedFit !== 'function') {
            try {
                if (controller && controller.fitAddon
                    && typeof controller.fitAddon.fit === 'function') {
                    controller.fitAddon.fit();
                    return { fitted: true, reason: 'unguarded', attempts: 1,
                        waitedMs: now() - started };
                }
            } catch (err) {
                console.warn('TerminalReadiness: unguarded fit failed', err);
            }
            return { fitted: false, reason: reason, attempts: 0,
                waitedMs: now() - started };
        }

        for (;;) {
            attempts += 1;
            var verdict = metrics.guardedFit(controller);
            if (verdict.fitted) {
                return { fitted: true, reason: verdict.reason, attempts: attempts,
                    waitedMs: now() - started };
            }
            reason = verdict.reason;
            if (now() - started >= bound) break;
            await sleep(gap);
        }

        console.warn('TerminalReadiness: no trustworthy measurement inside the bound,'
            + ' connecting with the grid we have', { reason: reason,
                attempts: attempts, boundMs: bound });
        return { fitted: false, reason: reason, attempts: attempts,
            waitedMs: now() - started };
    }

    function sleep(ms) {
        return new Promise(function (r) { setTimeout(r, ms); });
    }

    var prepaintLayouts = new WeakMap();

    function layoutState(controller, container) {
        var doc = global.document;
        var term = controller && controller.term;
        var fonts = doc && doc.fonts;
        if (!term || !container || !container.isConnected || !fonts
            || fonts.status !== 'loaded' || !fonts.ready || doc.visibilityState !== 'visible'
            || !Number.isFinite(controller._connGen) || !controller._sessionId
            || !global.getComputedStyle || !container.getBoundingClientRect) return null;
        var session = controller._sessionId();
        var box = container.getBoundingClientRect();
        if (!session || !(box.width > 0 && box.height > 0)
            || !(container.clientWidth > 0 && container.clientHeight > 0)) return null;
        var style = global.getComputedStyle(container);
        if (style.visibility !== 'visible' || style.display === 'none') return null;
        var options = term.options || {};
        return {
            term: term, container: container, fonts: fonts, ready: fonts.ready,
            connection: controller._connGen, session: session, nav: controller._navToken,
            navigation: global.NavigationGeneration?.current(),
            geometry: JSON.stringify([
                box.x, box.y, box.width, box.height, container.clientWidth, container.clientHeight,
                global.devicePixelRatio, style.font, style.padding, style.borderWidth,
                style.boxSizing, options.fontFamily, options.fontSize, options.fontWeight,
                options.fontWeightBold, options.lineHeight, options.letterSpacing,
                options.customGlyphs, options.scrollback, term.cols, term.rows,
            ]),
        };
    }

    function recordPrepaint(controller, verdict, frames, connection) {
        prepaintLayouts.delete(controller);
        if (!verdict || !verdict.fitted || verdict.reason !== 'ok'
            || frames !== 2 || connection !== controller._connGen) return;
        var container = global.document && global.document.getElementById('terminal');
        var state = layoutState(controller, container);
        if (state) prepaintLayouts.set(controller, state);
    }

    function consumePrepaint(controller, container) {
        if (!controller) return false;
        var previous = prepaintLayouts.get(controller);
        prepaintLayouts.delete(controller);
        if (!previous) return false;
        var current = layoutState(controller, container);
        return !!current && Object.keys(previous).every(function (key) {
            return previous[key] === current[key];
        });
    }

    async function waitForContainer(container, controller) {
        if (consumePrepaint(controller, container)) {
            return { fonts: 'ready', sized: true, timedOut: false };
        }
        var fonts = 'unavailable';
        if (global.TerminalMetrics && global.TerminalMetrics.waitForFonts) {
            await global.TerminalMetrics.waitForFonts();
            fonts = 'ready';
        } else if (global.document && global.document.fonts
                && global.document.fonts.ready) {
            try {
                await global.document.fonts.ready;
                fonts = 'ready';
            } catch (err) {
                console.warn('TerminalReadiness: document.fonts.ready rejected', err);
                fonts = 'timed_out';
            }
        }
        var r = global.TerminalLayoutWait
            ? await global.TerminalLayoutWait.waitForLayout(container)
            : null;
        if (r && r.timedOut) {
            console.warn('Terminal: layout wait timed out, connecting anyway', r);
        }
        return { fonts: fonts, sized: !!(r && r.sized), timedOut: !!(r && r.timedOut) };
    }


    var XTERM_LOAD_TIMEOUT_MS = 10000;
    var XTERM_POLL_MS = 50;

    /* something else */
    function xtermLoaded(shadowed) {
        var missing = [];
        if (typeof global.Terminal === 'undefined'
            || (shadowed !== undefined && global.Terminal === shadowed)) {
            missing.push('Terminal');
        }
        if (typeof global.FitAddon === 'undefined'
            || typeof global.FitAddon.FitAddon === 'undefined') missing.push('FitAddon');
        if (typeof global.WebglAddon === 'undefined'
            || typeof global.WebglAddon.WebglAddon === 'undefined') missing.push('WebglAddon');
        if (typeof global.Unicode11Addon === 'undefined'
            || typeof global.Unicode11Addon.Unicode11Addon === 'undefined') {
            missing.push('Unicode11Addon');
        }
        return { loaded: missing.length === 0, missing: missing };
    }

    async function waitForXterm(shadowed, opts) {
        var o = opts || {};
        var timeout = typeof o.timeoutMs === 'number' ? o.timeoutMs : XTERM_LOAD_TIMEOUT_MS;
        var poll = typeof o.pollMs === 'number' ? o.pollMs : XTERM_POLL_MS;
        var now = typeof o.now === 'function' ? o.now : function () { return Date.now(); };
        var started = now();
        var status = xtermLoaded(shadowed);
        while (!status.loaded) {
            if (now() - started >= timeout) {
                console.error('Terminal: xterm.js failed to load', { missing: status.missing });
                throw new Error('xterm.js failed to load: ' + status.missing.join(', '));
            }
            await sleep(poll);
            status = xtermLoaded(shadowed);
        }
        console.log('Terminal: xterm.js loaded in ' + (now() - started) + 'ms');
    }

    global.TerminalReadiness = {
        BOUND_MS: BOUND_MS,
        RETRY_MS: RETRY_MS,
        XTERM_LOAD_TIMEOUT_MS: XTERM_LOAD_TIMEOUT_MS,
        XTERM_POLL_MS: XTERM_POLL_MS,
        measure: measure,
        recordPrepaint: recordPrepaint,
        waitForContainer: waitForContainer,
        xtermLoaded: xtermLoaded,
        waitForXterm: waitForXterm
    };
}(typeof window !== 'undefined' ? window : globalThis));

console.log('[TerminalReadiness Module] Exported as window.TerminalReadiness');
