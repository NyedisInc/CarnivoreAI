
console.log('[TerminalLayout Module] Loading...');

(function () {
    'use strict';

    const DEBOUNCE_MS = 100;

    /* getElementById('terminal') */
    function createTerminalLayout(deps) {
        const wiring = deps || {};

        function hostElement() {
            const c = wiring.container;
            if (typeof c === 'function') return c() || null;
            if (c) return c;
            if (typeof document === 'undefined'
                || typeof document.getElementById !== 'function') return null;
            return document.getElementById('terminal');
        }

        /** @type {?object} The TerminalController install() was given. */
        let controller = null;
        /** @type {?number} Pending debounce timer id. */
        let timer = null;
        /** @type {?ResizeObserver} Observer on the xterm container. */
        let observer = null;
        /** @type {boolean} Guard so install() is idempotent. */
        let listenersWired = false;
        /** @type {string[]} Every reason seen since the last flush, for logs. */
        let pendingReasons = [];

        let onWindowResize = null;
        /** @type {?function} see `onWindowResize`. */
        let onOrientationChange = null;
        /** @type {?function} see `onWindowResize`. */
        let onViewportResize = null;
        /*  hidden  */
        let onVisibility = null;

        const MAX_FIT_RETRIES = 8;

        const RETRY_MS = 120;

        /** @type {number} Consecutive guard refusals since the last good fit. */
        let retries = 0;

        const transitionWaiters = new WeakMap();

        function flush(reason) {
            timer = null;
            pendingReasons = [];
            if (!controller || !controller.fitAddon || !controller.term) return;

            const metrics = window.TerminalMetrics;
            if (metrics && typeof metrics.guardedFit === 'function') {
                const result = metrics.guardedFit(controller);
                if (!result.fitted && result.reason === 'withdrawn') return;
                if (!result.fitted) {
                    console.warn(
                        `TerminalLayout: fit skipped, reason=${result.reason} source=${reason}`);
                    scheduleRetry(reason);
                    return;
                }
                const width = metrics.enforceWidthFit(controller);
                if (width.changed) {
                    console.warn(
                        `TerminalLayout: grid shrunk to ${width.cols} cols, `
                        + `painted ${width.painted}px in ${width.available}px `
                        + `source=${reason}`);
                }
            } else {
                try {
                    controller.fitAddon.fit();
                } catch (err) {
                    console.warn('TerminalLayout: fit failed', err);
                    return;
                }
            }

            retries = 0;

            const settle = window.TerminalResizeSettle;
            const vote = window.TerminalSizeVote;
            const grid = vote && vote.voteGrid ? vote.voteGrid(controller) : controller.term;
            if (settle && settle.decideResize({
                source: reason,
                cols: grid.cols,
                rows: grid.rows,
                lastCols: controller.lastSentCols,
                lastRows: controller.lastSentRows,
            }) === 'skip_transient') {
                console.log(
                    `[TERM-RESIZE] transient ignored ${grid.cols}x`
                    + `${grid.rows} source=${reason} `
                    + `${window.TerminalMetrics && window.TerminalMetrics.describeCellMetrics
                        ? ' ' + window.TerminalMetrics.describeCellMetrics(controller) : ''} `
                    + `shown=${settle.describeCulprit(
                        hostElement() && hostElement().parentElement)}`);
                return;
            }

            controller.sendResize(reason);
        }

        function scheduleRetry(reason) {
            if (retries >= MAX_FIT_RETRIES) {
                console.warn('TerminalLayout: giving up on fit retries');
                return;
            }
            retries += 1;
            if (timer) clearTimeout(timer);
            timer = setTimeout(() => flush(reason), RETRY_MS * retries);
        }

        function requestFit(reason = 'unknown', opts = {}) {
            pendingReasons.push(reason);
            if (opts.immediate) {
                if (timer) { clearTimeout(timer); timer = null; }
                flush(reason);
                return;
            }
            if (timer) clearTimeout(timer);
            const settle = window.TerminalResizeSettle;
            const waitMs = settle
                ? settle.settleMsFor(reason, DEBOUNCE_MS)
                : DEBOUNCE_MS;
            const arm = (ms) => {
                timer = setTimeout(() => {
                    if (document.body.classList.contains('grid-dragging')) { arm(DEBOUNCE_MS); return; }
                    flush(reason);
                }, ms);
            };
            arm(waitMs);
        }

        /* padding */
        function requestFitAfterTransition(el, propertyName, fallbackMs, reason) {
            if (!el) { requestFit(reason); return; }

            let waiter = transitionWaiters.get(el);
            if (!waiter) {
                waiter = { gen: 0, timer: null, listener: null };
                transitionWaiters.set(el, waiter);
            }
            if (waiter.timer) clearTimeout(waiter.timer);
            if (waiter.listener) el.removeEventListener('transitionend', waiter.listener);

            waiter.gen += 1;
            const myGen = waiter.gen;

            const settle = () => {
                if (waiter.gen !== myGen) return;
                if (waiter.timer) { clearTimeout(waiter.timer); waiter.timer = null; }
                if (waiter.listener) {
                    el.removeEventListener('transitionend', waiter.listener);
                    waiter.listener = null;
                }
                requestFit(reason);
            };

            waiter.listener = (evt) => {
                if (evt.target === el && evt.propertyName === propertyName) settle();
            };
            el.addEventListener('transitionend', waiter.listener);
            waiter.timer = setTimeout(settle, fallbackMs);
        }

        function install(ctl) {
            controller = ctl;
            if (listenersWired) return;
            listenersWired = true;

            onWindowResize = () => requestFit('window.resize');
            onOrientationChange = () => requestFit('orientationchange');
            onViewportResize = () => requestFit('visualViewport.resize');
            window.addEventListener('resize', onWindowResize);
            window.addEventListener('orientationchange', onOrientationChange);
            if (window.visualViewport) {
                window.visualViewport.addEventListener('resize', onViewportResize);
            }
            onVisibility = () => {
                if (controller && window.TerminalSizeVote) {
                    window.TerminalSizeVote.onVisibilityChange(controller, document);
                }
            };
            if (typeof document !== 'undefined' && document.addEventListener) {
                document.addEventListener('visibilitychange', onVisibility);
            }

            const container = hostElement();
            if (container && typeof ResizeObserver !== 'undefined') {
                try {
                    observer = new ResizeObserver(() => requestFit('ResizeObserver'));
                    observer.observe(container);
                } catch (err) {
                    console.warn('TerminalLayout: ResizeObserver setup failed', err);
                }
            }
        }

        function uninstall() {
            if (timer != null) { clearTimeout(timer); timer = null; }
            pendingReasons = [];
            controller = null;
            if (observer) {
                try { observer.disconnect(); } catch (err) {
                    console.warn('TerminalLayout: observer disconnect failed', err);
                }
                observer = null;
            }
            if (!listenersWired) return;
            listenersWired = false;
            if (onWindowResize) window.removeEventListener('resize', onWindowResize);
            if (onOrientationChange) {
                window.removeEventListener('orientationchange', onOrientationChange);
            }
            if (window.visualViewport && onViewportResize) {
                window.visualViewport.removeEventListener('resize', onViewportResize);
            }
            if (onVisibility && typeof document !== 'undefined' && document.removeEventListener) {
                document.removeEventListener('visibilitychange', onVisibility);
            }
            onWindowResize = null;
            onOrientationChange = null;
            onViewportResize = null;
            onVisibility = null;
        }

        return {
            install,
            uninstall,
            requestFit,
            requestFitAfterTransition,
            DEBOUNCE_MS,
            MAX_FIT_RETRIES,
            RETRY_MS,
            get observer() { return observer; },
        };
    }

    const defaultInstance = createTerminalLayout();

    window.TerminalLayout = {
        create: createTerminalLayout,
        install: defaultInstance.install,
        uninstall: defaultInstance.uninstall,
        requestFit: defaultInstance.requestFit,
        requestFitAfterTransition: defaultInstance.requestFitAfterTransition,
        DEBOUNCE_MS,
        MAX_FIT_RETRIES: defaultInstance.MAX_FIT_RETRIES,
        RETRY_MS: defaultInstance.RETRY_MS,
        get observer() { return defaultInstance.observer; },
    };
    console.log('[TerminalLayout Module] Exported as window.TerminalLayout');
})();
