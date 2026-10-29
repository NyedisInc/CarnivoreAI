/* there is nothing */
(function () {
    'use strict';

    function tr(key, params) {
        var i18n = globalThis.CloudeI18n;
        return i18n && typeof i18n.t === 'function' ? i18n.t(key, params) : key;
    }

    var pickerEl = null;

    var openAnchor = null;

    var onClosed = null;

    var onDocPointer = null;
    var onDocKey = null;

    function activeSession() {
        if (!window.Themes || typeof window.Themes.getActiveSession !== 'function') {
            return null;
        }
        return window.Themes.getActiveSession();
    }

    function close() {
        if (onDocPointer) {
            document.removeEventListener('pointerdown', onDocPointer, true);
            onDocPointer = null;
        }
        if (onDocKey) {
            document.removeEventListener('keydown', onDocKey, true);
            onDocKey = null;
        }
        if (pickerEl) {
            pickerEl.remove();
            pickerEl = null;
        }
        openAnchor = null;
        var closed = onClosed;
        onClosed = null;
        if (typeof closed === 'function') closed();
    }

    function isOpenFor(anchor) {
        return !!pickerEl && !!anchor && openAnchor === anchor;
    }

    function position(el, anchor) {
        if (!window.AnchorPopover) return;
        window.AnchorPopover.place(el, anchor);
    }

    function contextKey(context) {
        if (window.SessionKey) return window.SessionKey.forName(context.sessionName, context.hostKey);
        return (!context.hostKey || context.hostKey === 'local') ? context.sessionName : null;
    }

    function open(anchor, context) {
        close();
        if (!window.Themes || typeof window.Themes.listAll !== 'function') return;

        var session = context ? contextKey(context) : activeSession();
        if (context && !session) return;
        var themes = window.Themes.listAll();
        var activeId = (((context && window.Themes.getSessionManifest)
            ? window.Themes.getSessionManifest(context)
            : window.Themes.getActiveGlobal()) || {}).id;

        pickerEl = document.createElement('div');
        pickerEl.className = 'cloude-session-theme popup-focus';
        pickerEl.setAttribute('role', 'menu');
        pickerEl.setAttribute('aria-label', tr('header.menu.session_theme'));

        var head = document.createElement('div');
        head.className = 'cloude-session-theme__head';
        head.textContent = session
            ? 'theme for ' + session
            : 'theme';
        pickerEl.appendChild(head);

        var list = document.createElement('div');
        list.className = 'cloude-session-theme__list';
        themes.forEach(function (m) {
            var row = document.createElement('button');
            row.type = 'button';
            row.className = 'cloude-session-theme__item';
            row.setAttribute('role', 'menuitemradio');
            var selected = m.id === activeId;
            row.setAttribute('aria-checked', selected ? 'true' : 'false');
            if (selected) row.classList.add('is-active');
            row.textContent = (m.name || m.id).toLowerCase();
            row.addEventListener('click', async function () {
                const openedPicker = pickerEl;
                if (context) {
                    row.disabled = true;
                    const saved = await window.Themes.pinThemeForSession(session, m.id);
                    if (!saved) { row.disabled = false; return; }
                    if (typeof context.onSelected === 'function') context.onSelected(m.id);
                } else window.Themes.applyGlobal(m.id);
                if (pickerEl === openedPicker) close();
            });
            list.appendChild(row);
        });
        pickerEl.appendChild(list);

        document.body.appendChild(pickerEl);
        position(pickerEl, anchor);
        openAnchor = anchor;
        onClosed = context && typeof context.onClose === 'function' ? context.onClose : null;

        onDocPointer = function (e) {
            if (!pickerEl) return;
            if (pickerEl.contains(e.target)) return;
            if (anchor.contains(e.target)) return;
            close();
        };
        onDocKey = function (e) {
            if (e.key === 'Escape') close();
        };
        setTimeout(function () {
            document.addEventListener('pointerdown', onDocPointer, true);
            document.addEventListener('keydown', onDocKey, true);
        }, 0);
    }

    window.SessionThemeMenu = {
        open: open,
        close: close,
        isOpenFor: isOpenFor
    };
})();
