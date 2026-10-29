/*  hidden  height:1px width:1px */

console.log('[WriteFailureNotice Module] Loading...');

(function () {
    'use strict';

    var FALLBACK_KIND = 'WriteFailed';

    var TITLE = 'that did not save';

    var DEFAULT_SURFACE = 'session list';

    function kindName() {
        var mgr = window.ToastManager;
        return (mgr && mgr.WRITE_FAILED_KIND) || FALLBACK_KIND;
    }

    function freshId() {
        return 'writefail:' + Date.now() + ':'
            + Math.random().toString(36).slice(2, 8);
    }

    function report(text, opts) {
        var body = String(text == null ? '' : text).trim();
        if (!body) return false;
        var mgr = window.ToastManager;
        if (!mgr || typeof mgr.add !== 'function') {
            console.warn('[WriteFailureNotice] no toast surface for:', body);
            return false;
        }
        mgr.add({
            id: freshId(),
            session_id: null,
            kind: kindName(),
            title: (opts && opts.title) || TITLE,
            body: body,
            session_label: (opts && opts.surface) || DEFAULT_SURFACE,
            local: true,
        });
        return true;
    }

    window.WriteFailureNotice = {
        TITLE: TITLE,
        DEFAULT_SURFACE: DEFAULT_SURFACE,
        FALLBACK_KIND: FALLBACK_KIND,
        report: report,
    };

    console.log('[WriteFailureNotice Module] Loaded');
})();
