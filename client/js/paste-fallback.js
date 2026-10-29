
console.log('[PasteFallback Module] Loading...');

(function () {
    'use strict';

    function tr(key, params) {
        var i18n = globalThis.CloudeI18n;
        return i18n && typeof i18n.t === 'function' ? i18n.t(key, params) : key;
    }

    var OVERLAY_Z = 10002;

    var overlayEl = null;

    var inputEl = null;

    var releaseTrap = function () {};

    function isOpen() {
        return overlayEl !== null;
    }

    function close() {
        releaseTrap();
        releaseTrap = function () {};
        if (overlayEl) {
            overlayEl.remove();
            overlayEl = null;
        }
        inputEl = null;
    }

    function report(message, kind) {
        if (window.FabMenu && typeof window.FabMenu.notify === 'function') {
            window.FabMenu.notify(message, kind);
        }
    }

    function buildButton(id, label, variant, onClick) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.setAttribute('id', id);
        btn.className = 'paste-fallback__btn paste-fallback__btn--' + variant;
        btn.textContent = label;
        btn.addEventListener('click', function (e) {
            e.stopPropagation();
            onClick();
        });
        return btn;
    }

    function buildInput() {
        var ta = document.createElement('textarea');
        ta.setAttribute('id', 'pasteFallbackInput');
        ta.className = 'paste-fallback__input';
        ta.setAttribute('rows', '4');
        ta.setAttribute('autocapitalize', 'off');
        ta.setAttribute('autocorrect', 'off');
        ta.setAttribute('autocomplete', 'off');
        ta.setAttribute('spellcheck', 'false');
        ta.setAttribute('aria-label', tr('paste_fallback.target.aria'));
        return ta;
    }

    function firstFile(e) {
        var items = (e && e.clipboardData && e.clipboardData.items) || [];
        for (var i = 0; i < items.length; i++) {
            var type = items[i].type || '';
            var isFile = items[i].kind === 'file' || type.indexOf('image/') === 0;
            if (!isFile) continue;
            var blob = typeof items[i].getAsFile === 'function'
                ? items[i].getAsFile()
                : null;
            if (blob) return { blob: blob, name: blob.name || '' };
        }
        return null;
    }

    function open(term, inject, ticket) {
        if (!term || typeof inject !== 'function') return null;
        close();
        if (window.FabMenu && typeof window.FabMenu.dismissNotice === 'function') {
            window.FabMenu.dismissNotice();
        }

        overlayEl = document.createElement('div');
        overlayEl.className = 'paste-fallback';
        overlayEl.setAttribute('id', 'pasteFallback');
        overlayEl.setAttribute('role', 'dialog');
        overlayEl.setAttribute('aria-modal', 'true');
        overlayEl.setAttribute('aria-label', tr('paste_fallback.title'));
        overlayEl.style.zIndex = String(OVERLAY_Z);

        var panel = document.createElement('div');
        panel.className = 'paste-fallback__panel';

        var title = document.createElement('h2');
        title.className = 'paste-fallback__title';
        title.textContent = tr('paste_fallback.title');
        panel.appendChild(title);

        var hint = document.createElement('p');
        hint.className = 'paste-fallback__hint';
        hint.textContent = tr('paste_fallback.hint');
        panel.appendChild(hint);

        inputEl = buildInput();
        panel.appendChild(inputEl);

        var actions = document.createElement('div');
        actions.className = 'paste-fallback__actions';
        actions.appendChild(
            buildButton('pasteFallbackCancel', 'cancel', 'ghost', close));
        actions.appendChild(
            buildButton('pasteFallbackInsert', 'insert', 'primary', function () {
                submit(term, inject, ticket);
            }));
        panel.appendChild(actions);

        overlayEl.appendChild(panel);
        document.body.appendChild(overlayEl);

        inputEl.addEventListener('paste', function (e) {
            var picked = firstFile(e);
            if (!picked) return;
            if (typeof e.preventDefault === 'function') e.preventDefault();
            close();
            term._uploadAndInjectFile(picked.blob, picked.name, ticket);
        });

        if (window.ModalStack && typeof window.ModalStack.trap === 'function') {
            releaseTrap = window.ModalStack.trap(overlayEl, { onEscape: close });
        }

        focusInput();
        return overlayEl;
    }

    function focusInput() {
        if (!inputEl) return;
        try {
            inputEl.focus({ preventScroll: true });
            if (typeof inputEl.setSelectionRange === 'function') {
                inputEl.setSelectionRange(0, 0);
            }
        } catch (err) {
            console.warn('PasteFallback: could not focus the paste field', err);
        }
    }

    function submit(term, inject, ticket) {
        var text = inputEl ? String(inputEl.value || '') : '';
        if (!text) {
            report('nothing to paste - the box is empty', 'info');
            focusInput();
            return;
        }
        close();
        inject(term, text, ticket);
    }

    window.PasteFallback = {
        open: open,
        close: close,
        isOpen: isOpen,
        OVERLAY_Z: OVERLAY_Z
    };
})();

console.log('[PasteFallback Module] Exported as window.PasteFallback');
