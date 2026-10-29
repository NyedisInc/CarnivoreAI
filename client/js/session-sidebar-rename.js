
console.log('[SessionSidebarRename Module] Loading...');

(function () {
    function validateLabel(raw) {
        if (window.SessionLabel && window.SessionLabel.validate) {
            return window.SessionLabel.validate(raw);
        }
        return { ok: false, reason: 'the label rule is unavailable' };
    }

    let current = null;

    function listEl() {
        const sidebar = window.SessionSidebar;
        return (sidebar && sidebar.listEl) || null;
    }

    function announce(text) {
        const region = document.getElementById('session-sidebar-live');
        if (region) region.textContent = text;
    }

    function isEditing() {
        if (current !== null) return true;
        const shell = window.CloudeWeb && window.CloudeWeb.sidebarShell;
        return !!(shell && typeof shell.isEditing === 'function' && shell.isEditing());
    }

    function onListClick(e) {
        if (!isEditing()) return false;
        const inside = e.target.closest && e.target.closest('.session-sidebar-rename-edit');
        if (!inside) return false;
        e.stopPropagation();
        return true;
    }

    function onRowKeydown(e, rowEl) {
        if (e.key !== 'F2') return false;
        e.preventDefault();
        beginEdit(rowEl);
        return true;
    }

    /*  hidden  */
    function openEditor(o) {
        if (isEditing()) return false;
        o.hostEl.setAttribute('data-editing', '1');
        o.nameEl.hidden = true;

        const wrap = document.createElement('span');
        wrap.className = 'session-sidebar-rename-edit';
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'oc-field session-sidebar-rename-input';
        input.value = o.seed;
        input.setAttribute('aria-label', o.ariaLabel || `Rename ${o.seed}`);
        input.setAttribute(
            'maxlength',
            String((window.SessionLabel && window.SessionLabel.LABEL_MAX_CHARS) || 200)
        );
        const err = document.createElement('span');
        err.className = 'session-sidebar-rename-error';
        err.hidden = true;
        err.setAttribute('role', 'alert');
        wrap.appendChild(input);
        wrap.appendChild(err);
        o.nameEl.insertAdjacentElement('afterend', wrap);

        const ctx = {
            hostEl: o.hostEl,
            nameEl: o.nameEl,
            wrap,
            input,
            err,
            seed: o.seed,
            save: o.save,
            successText: o.successText,
            afterSuccess: o.afterSuccess,
            settled: false,
        };
        current = ctx;
        input.addEventListener('keydown', (e) => onEditKeydown(e, ctx));
        input.addEventListener('keyup', (e) => {
            e.stopPropagation();
            if (e.key === ' ') e.preventDefault();
        });
        input.addEventListener('blur', () => { commit(ctx); });
        input.focus();
        input.select();
        announce(`editing the name of ${o.seed}. Enter to save, Escape to cancel.`);
        return true;
    }

    function beginEdit(rowEl) {
        const shell = window.CloudeWeb && window.CloudeWeb.sidebarShell;
        if (shell && typeof shell.owns === 'function' && shell.owns(rowEl)
            && typeof shell.beginRowRename === 'function') {
            return shell.beginRowRename(rowEl);
        }
        if (isEditing()) return false;
        const state = rowEl.getAttribute('data-rename-state');
        const name = rowEl.dataset.name;
        const sessionId = rowEl.dataset.sessionId
            || (rowEl.dataset.asleep ? rowEl.dataset.sessionUuid : '') || rowEl.dataset.browserId
            || rowEl.dataset.layoutUuid || null;
        if (state !== 'renameable' || !sessionId || !name) {
            const nameEl = rowEl.querySelector('[data-row-name]');
            const why = (nameEl && nameEl.getAttribute('data-name-note'))
                || 'this session cannot be renamed';
            announce(why);
            rowEl.setAttribute('data-rename-refused', '1');
            return false;
        }
        const nameEl = rowEl.querySelector('[data-row-name]');
        if (!nameEl) return false;

        // something else
        //  hidden  display:none
        const seed = (nameEl.textContent || '').trim();

        return openEditor({
            hostEl: rowEl,
            nameEl,
            seed,
            ariaLabel: `Rename ${seed}`,
            save: (value) => {
                const B = window.SessionSidebarBrowsers;
                const L = window.SessionSidebarLayouts;
                if (B && B.isBrowserName(name)) return B.rename(sessionId, value);
                if (L && L.isLayoutName(name)) return L.rename(sessionId, value);
                return window.API.renameSession(sessionId, value);
            },
            afterSuccess: async () => {
                const sidebar = window.SessionSidebar;
                if (sidebar) {
                    sidebar._lastSig = null;
                    await sidebar._fetchAndRender();
                }
            },
        });
    }

    /* Escape cancels */
    function onEditKeydown(e, ctx) {
        e.stopPropagation();
        if (e.key === 'Enter') {
            e.preventDefault();
            commit(ctx);
            return;
        }
        if (e.key === 'Escape') {
            e.preventDefault();
            cancel(ctx);
        }
    }

    function teardown(ctx) {
        ctx.settled = true;
        current = null;
        try { if (ctx.wrap.parentNode) ctx.wrap.parentNode.removeChild(ctx.wrap); } catch (_) {  }
        ctx.nameEl.hidden = false;
        ctx.hostEl.removeAttribute('data-editing');
    }

    function cancel(ctx) {
        if (ctx.settled) return;
        teardown(ctx);
        announce(`rename canceled, ${ctx.seed} unchanged`);
    }

    async function commit(ctx) {
        if (ctx.settled) return;
        const raw = (ctx.input.value || '').trim();
        if (!raw || raw === ctx.seed) { cancel(ctx); return; }
        const verdict = validateLabel(raw);
        if (!verdict.ok) {
            showError(ctx, verdict.reason);
            return;
        }
        ctx.settled = true;
        let result;
        try {
            result = await ctx.save(verdict.value);
        } catch (err) {
            ctx.settled = false;
            const detail = (err && (err.message || err.detail)) || 'the server refused it';
            showError(ctx, `rename failed: ${detail}`);
            announce(`rename failed, ${ctx.seed} is unchanged: ${detail}`);
            return;
        }
        teardown(ctx);
        announce(ctx.successText ? ctx.successText(verdict.value) : `renamed ${ctx.seed} to ${verdict.value}`);
        if (ctx.afterSuccess) await ctx.afterSuccess(result, verdict.value);
    }

    function showError(ctx, text) {
        ctx.err.textContent = text;
        ctx.err.hidden = false;
        ctx.input.focus();
        ctx.input.select();
    }

    function afterRender() {
        if (current === null) return;
        const list = listEl();
        if (list && list.contains(current.wrap)) return;
        current = null;
    }

    /* could not */
    function openHeadingEditor(anchor, o) {
        const PH = window.SessionSidebarProjectHeader;
        const found = PH ? PH.headingElementsFor(anchor) : {};
        const hostRow = found.headerBtn && found.headerBtn.closest('.session-sidebar-group__headerrow');
        const labelEl = found.labelEl;
        if (!hostRow || !labelEl) return null;
        return openEditor(Object.assign({ hostEl: hostRow, nameEl: labelEl }, o));
    }

    window.SessionSidebarRename = {
        afterRender, onListClick, onRowKeydown, beginEdit, isEditing, validateLabel, openEditor,
        openHeadingEditor,
    };
    console.log('[SessionSidebarRename Module] Exported as window.SessionSidebarRename');
})();
