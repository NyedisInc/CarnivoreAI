(function (global) {
    'use strict';

    var SIZE_TIMEOUT_MS = 2000;
    var FRAME_TIMEOUT_MS = 250;
    var FRAME_COUNT = 2;

    function nextFrameOrTimeout(ms) {
        return new Promise(function (resolve) {
            var settled = false;
            function done(painted) {
                if (settled) return;
                settled = true;
                resolve(painted);
            }
            var timer = setTimeout(function () { done(false); }, ms);
            try {
                global.requestAnimationFrame(function () {
                    clearTimeout(timer);
                    done(true);
                });
            } catch (e) {
                clearTimeout(timer);
                done(false);
            }
        });
    }

    async function waitForLayout(container, opts) {
        var o = opts || {};
        var sizeTimeout = typeof o.sizeTimeoutMs === 'number' ? o.sizeTimeoutMs : SIZE_TIMEOUT_MS;
        var frameTimeout = typeof o.frameTimeoutMs === 'number' ? o.frameTimeoutMs : FRAME_TIMEOUT_MS;
        var frames = typeof o.frames === 'number' ? o.frames : FRAME_COUNT;
        var now = typeof o.now === 'function' ? o.now : function () { return Date.now(); };

        var started = now();
        var timedOut = false;

        var sized = hasBox(container);
        while (!sized) {
            if (now() - started > sizeTimeout) {
                timedOut = true;
                break;
            }
            await new Promise(function (r) { setTimeout(r, 16); });
            sized = hasBox(container);
        }

        var framesPainted = 0;
        for (var i = 0; i < frames; i++) {
            var painted = await nextFrameOrTimeout(frameTimeout);
            if (painted) framesPainted++;
            else timedOut = true;
        }

        return {
            sized: sized,
            framesPainted: framesPainted,
            timedOut: timedOut,
            waitedMs: now() - started
        };
    }

    async function settleFrames(frames, timeoutMs) {
        var n = typeof frames === 'number' ? frames : FRAME_COUNT;
        var ms = typeof timeoutMs === 'number' ? timeoutMs : FRAME_TIMEOUT_MS;
        var painted = 0;
        for (var i = 0; i < n; i++) {
            if (await nextFrameOrTimeout(ms)) painted++;
        }
        return painted;
    }

    /* display:none getElementById('terminal') */
    function hasBox(el) {
        if (!el) return false;
        return (el.offsetWidth | 0) > 0 && (el.offsetHeight | 0) > 0;
    }

    global.TerminalLayoutWait = {
        waitForLayout: waitForLayout,
        settleFrames: settleFrames,
        nextFrameOrTimeout: nextFrameOrTimeout,
        hasBox: hasBox,
        SIZE_TIMEOUT_MS: SIZE_TIMEOUT_MS,
        FRAME_TIMEOUT_MS: FRAME_TIMEOUT_MS,
        FRAME_COUNT: FRAME_COUNT
    };
}(typeof window !== 'undefined' ? window : globalThis));
