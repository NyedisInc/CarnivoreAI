
console.log('[AttachmentToast Module] Loading...');

(function () {
    'use strict';

    var MAX_EXT_CHARS = 4;

    var GENERIC_EXT_LABEL = 'file';

    function isPromptSubmit(data) {
        if (typeof data !== 'string' || data === '') return false;
        if (window.TerminalInputKind
            && typeof window.TerminalInputKind.isMouseReport === 'function'
            && window.TerminalInputKind.isMouseReport(data)) {
            return false;
        }
        return data.split('\x1b\r').join('').indexOf('\r') !== -1;
    }

    function thumbSpecFor(filename, mimeType) {
        var mime = String(mimeType == null ? '' : mimeType).toLowerCase();
        var ext = extensionOf(filename);
        var fromMime = mime.indexOf('/') !== -1
            ? mime.split('/')[1].split('+')[0].split(';')[0]
            : '';
        var label = ext || fromMime || GENERIC_EXT_LABEL;
        if (label.length > MAX_EXT_CHARS) label = GENERIC_EXT_LABEL;
        return {
            image: mime.indexOf('image/') === 0 || isImageExtension(ext),
            label: label.toUpperCase(),
        };
    }

    function extensionOf(filename) {
        var name = String(filename == null ? '' : filename);
        var dot = name.lastIndexOf('.');
        if (dot <= 0 || dot === name.length - 1) return '';
        return name.slice(dot + 1).toLowerCase();
    }

    function isImageExtension(ext) {
        return ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'avif']
            .indexOf(String(ext)) !== -1;
    }

    function previewDataUrl(blob) {
        var web = window.CloudeWeb;
        if (!blob || !web || typeof web.attachmentPreviewDataUrl !== 'function') {
            return Promise.resolve(null);
        }
        return web.attachmentPreviewDataUrl(blob);
    }

    function headerSessionLabel() {
        var el = document.getElementById('header-title-text');
        if (!el || !window.SessionLabel
            || typeof window.SessionLabel.seedFromElement !== 'function') {
            return '';
        }
        return window.SessionLabel.seedFromElement(el);
    }

    function show(term, opts) {
        var o = opts || {};
        var mgr = window.ToastManager;
        if (!mgr || typeof mgr.add !== 'function') return Promise.resolve();
        var sessionId = (term && typeof term._sessionId === 'function')
            ? term._sessionId() : null;
        var spec = thumbSpecFor(o.filename, o.blob && o.blob.type);
        var id = 'attach:' + (sessionId || 'none') + ':' + Date.now()
            + ':' + Math.random().toString(36).slice(2, 8);
        var record = {
            id: id,
            session_id: sessionId,
            kind: mgr.ATTACHMENT_KIND,
            title: 'attached',
            body: null,
            local: true,
            attachment_name: o.filename || '',
            thumb_label: spec.label,
            thumb_url: null,
            full_blob: spec.image ? (o.blob || null) : null,
            session_label: o.sessionLabel || headerSessionLabel() || null,
        };
        mgr.add(record);

        if (!spec.image) return Promise.resolve();
        return previewDataUrl(o.blob).then(function (url) {
            if (!url) return;
            if (typeof mgr.updateLocal !== 'function') return;
            mgr.updateLocal(id, { thumb_url: url });
        });
    }

    function noteUserInput(sessionId, data) {
        var mgr = window.ToastManager;
        if (!sessionId || !isPromptSubmit(data)) return 0;
        if (!mgr || typeof mgr.dismissKindForSession !== 'function') return 0;
        return mgr.dismissKindForSession(mgr.ATTACHMENT_KIND, sessionId);
    }

    window.AttachmentToast = {
        isPromptSubmit: isPromptSubmit,
        thumbSpecFor: thumbSpecFor,
        extensionOf: extensionOf,
        show: show,
        noteUserInput: noteUserInput,
    };
})();
