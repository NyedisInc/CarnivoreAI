
console.log('[AttachmentToast Module] Loading...');

(function () {
    'use strict';

    var THUMB_PX = 88;

    var THUMB_QUALITY = 0.72;

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
        return new Promise(function (resolve) {
            if (!blob || typeof FileReader !== 'function'
                || typeof Image !== 'function'
                || !document || typeof document.createElement !== 'function') {
                resolve(null);
                return;
            }
            var reader = new FileReader();
            reader.onerror = function () { resolve(null); };
            reader.onload = function () {
                var img = new Image();
                img.onerror = function () { resolve(null); };
                img.onload = function () { resolve(drawThumb(img)); };
                img.src = String(reader.result || '');
            };
            try {
                reader.readAsDataURL(blob);
            } catch (err) {
                console.warn('[AttachmentToast] preview unavailable:',
                    err && err.message);
                resolve(null);
            }
        });
    }

    function drawThumb(img) {
        var w = img.naturalWidth || img.width || 0;
        var h = img.naturalHeight || img.height || 0;
        if (!w || !h) return null;
        var scale = Math.min(1, THUMB_PX / Math.max(w, h));
        var canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(w * scale));
        canvas.height = Math.max(1, Math.round(h * scale));
        var ctx = typeof canvas.getContext === 'function'
            ? canvas.getContext('2d') : null;
        if (!ctx) return null;
        try {
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
            return canvas.toDataURL('image/webp', THUMB_QUALITY);
        } catch (err) {
            console.warn('[AttachmentToast] thumbnail draw failed:',
                err && err.message);
            return null;
        }
    }

    function renderThumbs(cardEl, toasts) {
        if (!cardEl || !Array.isArray(toasts)) return;
        var old = cardEl.querySelector('.toast__thumbs');
        if (old) old.remove();
        var strip = document.createElement('div');
        strip.className = 'toast__thumbs';
        for (var i = 0; i < toasts.length; i++) {
            strip.appendChild(thumbRow(toasts[i]));
        }
        cardEl.appendChild(strip);
    }

    function thumbRow(toast) {
        var row = document.createElement('div');
        row.className = 'toast__thumb-row';

        var frame = document.createElement('div');
        frame.className = 'toast__thumb';
        var name = String((toast && toast.attachment_name) || '');
        if (toast && toast.thumb_url) {
            var img = document.createElement('img');
            img.className = 'toast__thumb-img';
            img.setAttribute('alt', name || 'attached image');
            img.setAttribute('src', toast.thumb_url);
            if (toast.full_blob) {
                var btn = document.createElement('button');
                btn.setAttribute('type', 'button');
                btn.className = 'toast__thumb-btn';
                btn.setAttribute('aria-label',
                    catalogText('toast.attachment.open_full', { name: name }));
                btn.appendChild(img);
                btn.addEventListener('click', function (ev) {
                    ev.stopPropagation();
                    var web = window.CloudeWeb;
                    if (web && typeof web.openAttachmentLightbox === 'function') {
                        web.openAttachmentLightbox(toast.full_blob, name, btn);
                    }
                });
                frame.appendChild(btn);
            } else {
                frame.appendChild(img);
            }
        } else {
            var chip = document.createElement('span');
            chip.className = 'toast__thumb-ext';
            chip.setAttribute('aria-hidden', 'true');
            chip.textContent = String((toast && toast.thumb_label)
                || GENERIC_EXT_LABEL.toUpperCase());
            frame.appendChild(chip);
            frame.dataset.noPreview = '1';
        }
        row.appendChild(frame);

        var label = document.createElement('div');
        label.className = 'toast__thumb-name';
        label.textContent = name || '(unnamed file)';
        row.appendChild(label);
        return row;
    }

    function catalogText(key, params) {
        return globalThis.CloudeTr(key, params);
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
        THUMB_PX: THUMB_PX,
        isPromptSubmit: isPromptSubmit,
        thumbSpecFor: thumbSpecFor,
        extensionOf: extensionOf,
        renderThumbs: renderThumbs,
        show: show,
        noteUserInput: noteUserInput,
    };
})();
