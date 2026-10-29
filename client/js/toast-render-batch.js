/*  hidden  */
console.log('[ToastRenderBatch Module] Loading...');

(function (global) {
    'use strict';

    var FALLBACK_MS = 32;

    /* could not */
    function schedule(flush) {
        var done = false;
        function run() {
            if (done) return;
            done = true;
            flush();
        }
        var timer = setTimeout(run, FALLBACK_MS);
        try {
            global.requestAnimationFrame(function () {
                clearTimeout(timer);
                run();
            });
        } catch (e) {
            clearTimeout(timer);
            run();
        }
        return {
            cancel: function () {
                if (done) return;
                done = true;
                clearTimeout(timer);
            },
        };
    }

    global.ToastRenderBatch = {
        FALLBACK_MS: FALLBACK_MS,
        schedule: schedule,
    };
}(typeof window !== 'undefined' ? window : globalThis));

console.log('[ToastRenderBatch Module] Exported as window.ToastRenderBatch');
