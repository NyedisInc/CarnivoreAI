
console.log('[TerminalHeaderRename Module] Loading...');

(function () {
    'use strict';

    function tr(key, params) {
        var i18n = globalThis.CloudeI18n;
        return i18n && typeof i18n.t === 'function' ? i18n.t(key, params) : key;
    }

    function enterHeaderRename(controller) {
        const titleEl = document.getElementById('header-title-text');
        if (!titleEl) return;
        if (titleEl.style.display === 'none') return;

        const seed = (window.SessionLabel && window.SessionLabel.seedFromElement)
            ? window.SessionLabel.seedFromElement(titleEl) : '';
        if (!seed) return;

        const input = document.createElement('input');
        input.type = 'text';
        input.id = 'header-rename-input';
        input.className = 'header-rename-input';
        input.value = seed;
        input.setAttribute('maxlength',
            String((window.SessionLabel && window.SessionLabel.LABEL_MAX_CHARS) || 200));
        input.spellcheck = false;
        input.autocomplete = 'off';
        input.setAttribute('aria-label', tr('session.rename.input.aria'));

        const err = document.createElement('span');
        err.id = 'header-rename-error';
        err.className = 'header-rename-error';
        err.style.display = 'none';

        titleEl.style.display = 'none';
        const pencilEl = document.getElementById('header-rename-pencil');
        if (pencilEl) pencilEl.style.display = 'none';

        titleEl.insertAdjacentElement('afterend', input);
        input.insertAdjacentElement('afterend', err);

        let settled = false;

        const cleanup = () => {
            try {
                if (input.parentNode) input.parentNode.removeChild(input);
            } catch (_) {  }
            try {
                if (err.parentNode) err.parentNode.removeChild(err);
            } catch (_) {  }
            titleEl.style.display = '';
            if (pencilEl) pencilEl.style.display = '';
        };

        const cancel = () => {
            if (settled) return;
            settled = true;
            cleanup();
        };

        const save = async () => {
            if (settled) return;
            const raw = (input.value || '').trim();
            if (!raw || raw === seed) {
                cancel();
                return;
            }
            const verdict = (window.SessionLabel && window.SessionLabel.validate)
                ? window.SessionLabel.validate(raw)
                : { ok: false, reason: 'the label rule is unavailable' };
            if (!verdict.ok) {
                err.textContent = verdict.reason;
                err.style.display = '';
                input.focus();
                input.select();
                return;
            }
            const sid = controller ? controller._sessionId() : null;
            if (!sid) {
                err.textContent = tr('session.rename.no_active');
                err.style.display = '';
                return;
            }
            settled = true;
            try {
                await window.API.renameSession(sid, verdict.value);
                cleanup();
            } catch (e) {
                settled = false;
                let msg = (e && e.message) ? e.message : 'Rename failed';
                if (/409/.test(msg) || /already in use/i.test(msg)) {
                    msg = 'Name already in use';
                } else if (/400/.test(msg) || /Invalid session name/i.test(msg)) {
                    msg = 'Invalid name';
                } else if (/404/.test(msg)) {
                    msg = 'Session not found';
                }
                err.textContent = msg;
                err.style.display = '';
                input.focus();
                input.select();
            }
        };

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                save();
            } else if (e.key === 'Escape') {
                e.preventDefault();
                cancel();
            }
        });
        input.addEventListener('blur', () => {
            save();
        });

        setTimeout(() => { input.focus(); input.select(); }, 0);
    }

    function exitHeaderRename(newName) {
        const input = document.getElementById('header-rename-input');
        const err = document.getElementById('header-rename-error');
        const titleEl = document.getElementById('header-title-text');
        const pencilEl = document.getElementById('header-rename-pencil');
        if (input && input.parentNode) {
            try { input.parentNode.removeChild(input); } catch (_) {  }
        }
        if (err && err.parentNode) {
            try { err.parentNode.removeChild(err); } catch (_) {  }
        }
        if (titleEl) {
            titleEl.style.display = '';
            if (newName) {
                if (window.HeaderTitleFit) {
                    window.HeaderTitleFit.setTitle(newName);
                } else {
                    titleEl.textContent = newName;
                }
            }
        }
        if (pencilEl) pencilEl.style.display = '';
    }

    window.TerminalHeaderRename = {
        enter: enterHeaderRename,
        exit: exitHeaderRename
    };
})();

console.log('[TerminalHeaderRename Module] Exported as window.TerminalHeaderRename');
