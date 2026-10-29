// THREE-OUTCOME RULE

export const STATUS = Object.freeze({
    INACTIVE: 'inactive',
    RUNNING: 'running',
    PAUSED: 'paused',
    STATIC: 'static',
    SKIPPED: 'skipped',
    UNAVAILABLE: 'unavailable',
});

const STATUS_ATTR = 'themeEffects';

const MAX_DPR = 2;

const MOBILE_BREAKPOINT = 768;

const MAX_FRAME_GAP_MS = 250;

const SLEEP_SLACK_MS = 8;

export function readVar(name, fallback) {
    try {
        const v = getComputedStyle(document.documentElement)
            .getPropertyValue(name);
        const trimmed = v ? v.trim() : '';
        return trimmed || fallback;
    } catch (_) {
        return fallback;
    }
}

export function rgbTriple(hex, fallback = '128, 128, 128') {
    if (typeof hex !== 'string') return fallback;
    let h = hex.trim().replace(/^#/, '');
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    if (h.length !== 6 || /[^0-9a-fA-F]/.test(h)) return fallback;
    const n = parseInt(h, 16);
    return `${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}`;
}

function backdropHeld() {
    if (document.documentElement.getAttribute('data-calm') !== null) return true;
    const list = document.documentElement.getAttribute('data-anim-off') || '';
    return (' ' + list + ' ').indexOf(' theme-backdrop ') >= 0;
}

function prefersReducedMotion() {
    try {
        return !!(window.matchMedia
            && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch (_) {
        return false;
    }
}

function publishStatus(status) {
    try {
        if (status == null || status === STATUS.INACTIVE) {
            delete document.documentElement.dataset[STATUS_ATTR];
        } else {
            document.documentElement.dataset[STATUS_ATTR] = status;
        }
    } catch (_) {  }
}

export function createEffect(spec) {
    let canvas = null;
    let ctx = null;
    let state = null;
    let env = null;
    let rafId = null;
    let timerId = null;
    let lastFrameAt = 0;
    let prevFrameAt = 0;
    let elapsedMs = 0;
    let resizeHandler = null;
    let visHandler = null;
    let motionQuery = null;
    let motionHandler = null;
    let typeObserver = null;
    let status = STATUS.INACTIVE;
    let reason = null;

    const fps = typeof spec.fps === 'number' ? spec.fps : 30;
    const fpsMobile = typeof spec.fpsMobile === 'number' ? spec.fpsMobile : 15;

    function setStatus(next, why) {
        status = next;
        reason = why || null;
        publishStatus(next);
    }

    function resize() {
        if (!canvas || !ctx) return;
        const width = window.innerWidth;
        const height = window.innerHeight;
        const dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
        canvas.width = Math.floor(width * dpr);
        canvas.height = Math.floor(height * dpr);
        canvas.style.width = width + 'px';
        canvas.style.height = height + 'px';
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.scale(dpr, dpr);
        env = {
            width,
            height,
            dpr,
            isMobile: width < MOBILE_BREAKPOINT,
            readVar,
            rgbTriple,
        };
        const produced = spec.setup(ctx, env);
        if (produced !== undefined) state = produced;
    }

    function scheduleNext(cap) {
        const wait = 1000 / cap - (performance.now() - lastFrameAt) - SLEEP_SLACK_MS;
        if (wait > 0) {
            timerId = setTimeout(() => {
                timerId = null;
                rafId = requestAnimationFrame(tick);
            }, wait);
        } else {
            rafId = requestAnimationFrame(tick);
        }
    }

    function tick(now) {
        rafId = null;
        const cap = env && env.isMobile ? fpsMobile : fps;
        if (now - lastFrameAt < 1000 / cap) {
            scheduleNext(cap);
            return;
        }
        if (prevFrameAt !== 0) {
            elapsedMs += Math.min(now - prevFrameAt, MAX_FRAME_GAP_MS);
        }
        prevFrameAt = now;
        lastFrameAt = now;
        try {
            spec.draw(ctx, env, state, elapsedMs);
        } catch (e) {
            console.warn('ThemeEffects: draw threw for', spec.id, e);
            teardownRuntime();
            setStatus(STATUS.UNAVAILABLE, 'draw threw: ' + (e && e.message));
            return;
        }
        scheduleNext(cap);
    }

    function startLoop() {
        if (rafId != null || timerId != null) return;
        lastFrameAt = 0;
        prevFrameAt = 0;
        rafId = requestAnimationFrame(tick);
        setStatus(STATUS.RUNNING);
    }

    function stopLoop() {
        if (timerId != null) {
            clearTimeout(timerId);
            timerId = null;
        }
        if (rafId != null) {
            cancelAnimationFrame(rafId);
            rafId = null;
        }
    }

    function teardownRuntime() {
        stopLoop();
        if (resizeHandler) {
            window.removeEventListener('resize', resizeHandler);
            resizeHandler = null;
        }
        if (visHandler) {
            document.removeEventListener('visibilitychange', visHandler);
            visHandler = null;
        }
        if (typeObserver) {
            typeObserver.disconnect();
            typeObserver = null;
        }
        if (motionQuery && motionHandler) {
            if (typeof motionQuery.removeEventListener === 'function') {
                motionQuery.removeEventListener('change', motionHandler);
            } else if (typeof motionQuery.removeListener === 'function') {
                motionQuery.removeListener(motionHandler);
            }
        }
        motionQuery = null;
        motionHandler = null;
        if (canvas && canvas.parentNode) canvas.parentNode.removeChild(canvas);
        canvas = null;
        ctx = null;
        state = null;
        env = null;
        prevFrameAt = 0;
        elapsedMs = 0;
    }

    function mountCanvas() {
        let el;
        try {
            el = document.createElement('canvas');
        } catch (e) {
            return 'canvas element creation failed';
        }
        el.id = spec.canvasId || (spec.id + '-effects');
        el.setAttribute('aria-hidden', 'true');
        Object.assign(el.style, {
            position: 'fixed',
            inset: '0',
            width: '100vw',
            // screen.
            height: '100dvh',
            zIndex: '-1',
            pointerEvents: 'none',
            background: spec.background || 'transparent',
        });
        let c = null;
        try {
            document.body.appendChild(el);
            c = el.getContext('2d', { alpha: !spec.background });
        } catch (e) {
            try { if (el.parentNode) el.parentNode.removeChild(el); } catch (_) {}
            return '2d context threw: ' + (e && e.message);
        }
        if (!c) {
            try { if (el.parentNode) el.parentNode.removeChild(el); } catch (_) {}
            return '2d context unavailable';
        }
        canvas = el;
        ctx = c;
        return null;
    }

    function init(_opts) {
        if (canvas) return;
        try {
            if (prefersReducedMotion()) {
                if (typeof spec.staticFrame !== 'function') {
                    setStatus(STATUS.SKIPPED, 'prefers-reduced-motion: reduce');
                    return;
                }
                const failure = mountCanvas();
                if (failure) {
                    setStatus(STATUS.UNAVAILABLE, failure);
                    console.warn('ThemeEffects:', spec.id, 'unavailable:', failure);
                    return;
                }
                resize();
                spec.staticFrame(ctx, env, state, 0);
                resizeHandler = () => {
                    resize();
                    try {
                        spec.staticFrame(ctx, env, state, 0);
                    } catch (e) {
                        console.warn('ThemeEffects: staticFrame threw for', spec.id, e);
                    }
                };
                window.addEventListener('resize', resizeHandler, { passive: true });
                setStatus(STATUS.STATIC, 'prefers-reduced-motion: reduce');
                return;
            }

            const failure = mountCanvas();
            if (failure) {
                setStatus(STATUS.UNAVAILABLE, failure);
                console.warn('ThemeEffects:', spec.id, 'unavailable:', failure);
                return;
            }
            resize();

            resizeHandler = () => {
                try {
                    resize();
                    if (document.hidden || backdropHeld()) {
                        if (typeof spec.staticFrame === 'function') spec.staticFrame(ctx, env, state, 0);
                        else spec.draw(ctx, env, state, elapsedMs);
                    }
                } catch (e) {
                    console.warn('ThemeEffects: resize threw for', spec.id, e);
                    teardownRuntime();
                    setStatus(STATUS.UNAVAILABLE, 'resize threw: ' + (e && e.message));
                }
            };
            window.addEventListener('resize', resizeHandler, { passive: true });

            visHandler = () => {
                if (prefersReducedMotion()) return;
                if (document.hidden || backdropHeld()) {
                    stopLoop();
                    setStatus(STATUS.PAUSED);
                } else {
                    startLoop();
                }
            };
            document.addEventListener('visibilitychange', visHandler);
            if (typeof MutationObserver === 'function') {
                typeObserver = new MutationObserver(visHandler);
                typeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-anim-off', 'data-calm'] });
            }

            try {
                motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
                motionHandler = (e) => {
                    if (e.matches) {
                        stopLoop();
                        setStatus(STATUS.SKIPPED, 'prefers-reduced-motion turned on');
                    } else if (!document.hidden && !backdropHeld()) {
                        startLoop();
                    }
                };
                if (typeof motionQuery.addEventListener === 'function') {
                    motionQuery.addEventListener('change', motionHandler);
                } else if (typeof motionQuery.addListener === 'function') {
                    motionQuery.addListener(motionHandler);
                } else {
                    motionQuery = null;
                    motionHandler = null;
                }
            } catch (_) {
                motionQuery = null;
                motionHandler = null;
            }

            if (document.hidden || backdropHeld()) {
                setStatus(STATUS.PAUSED);
            } else {
                startLoop();
            }
        } catch (e) {
            teardownRuntime();
            setStatus(STATUS.UNAVAILABLE, 'init threw: ' + (e && e.message));
            console.warn('ThemeEffects: init threw for', spec.id, e);
        }
    }

    function destroy() {
        teardownRuntime();
        setStatus(STATUS.INACTIVE);
    }

    function getStatus() {
        return { status, reason };
    }

    return { init, destroy, getStatus };
}
