/* could not rogue agents */

console.log('[SessionSidebarReorder Module] Loading...');

(function () {
    const DRAG_SLOP_PX = 4;

    let focusName = null;

    let focusBand = null;


    let wired = false;

    function shellDrawing() {
        const shell = window.CloudeWeb && window.CloudeWeb.sidebarShell;
        return (shell && typeof shell.drew === 'function' && shell.drew(listEl())) ? shell : null;
    }

    function listEl() {
        const sidebar = window.SessionSidebar;
        return (sidebar && sidebar.listEl) || null;
    }

    function rowEls() {
        const list = listEl();
        if (!list) return [];
        return Array.prototype.slice.call(list.querySelectorAll('.session-sidebar-row'));
    }

    function visibleNames() {
        return rowEls().map((el) => el.dataset.name).filter((n) => !!n);
    }

    function isDragging() {
        const d = window.SessionSidebarRowDrag;
        if (d && d.isDragging()) return true;
        const shell = window.CloudeWeb && window.CloudeWeb.sidebarShell;
        return !!(shell && typeof shell.isDragging === 'function' && shell.isDragging());
    }

    function tookClick() {
        const d = window.SessionSidebarRowDrag;
        return !!(d && d.tookClick());
    }

    function setFocusRow(name, band, takeFocus) {
        const shell = shellDrawing();
        if (shell) {
            shell.focus.setFocusRow(name, band, takeFocus);
            return;
        }
        const rows = rowEls();
        if (!rows.length) return;
        let target = null;
        if (band != null) {
            target = rows.find((el) => el.dataset.name === name && el.dataset.band === band) || null;
        }
        if (!target) target = rows.find((el) => el.dataset.name === name) || null;
        if (!target) target = rows[0];
        for (const el of rows) {
            el.setAttribute('tabindex', el === target ? '0' : '-1');
        }
        focusName = target.dataset.name || null;
        focusBand = target.dataset.band || null;
        if (takeFocus) target.focus();
    }

    function afterRender() {
        const list = listEl();
        if (!list) return;
        const shell = shellDrawing();
        if (shell) {
            shell.focus.afterRender();
            return;
        }
        const hadFocus = !!document.activeElement
            && list.contains(document.activeElement);
        setFocusRow(focusName, focusBand, hadFocus);
    }

    function announce(text) {
        const region = document.getElementById('session-sidebar-live');
        if (region) region.textContent = text;
    }

    function repaintKeepingFocus(name, band) {
        focusName = name;
        focusBand = band || null;
        const sidebar = window.SessionSidebar;
        if (sidebar) sidebar.repaint();
        setFocusRow(name, focusBand, true);
    }

    function bandNames(band) {
        return rowEls().filter((el) => el.dataset.band === band)
            .map((el) => el.dataset.name).filter((n) => !!n);
    }

    function ownsOrder(band) {
        const S = window.SessionSidebarStore;
        return !!(band && S && S.isBandOrderKey && S.isBandOrderKey(band));
    }

    function moveRow(name, delta, band) {
        const arrangement = window.SessionSidebarArrangement;
        if (!arrangement) return false;
        if (ownsOrder(band) && arrangement.moveInBand) {
            const next = arrangement.moveInBand(band, name, delta, bandNames(band));
            if (!next) {
                announce(`${name} is already at the ${delta < 0 ? 'top' : 'bottom'} of its group`);
                return false;
            }
            repaintKeepingFocus(name, band);
            const drawn = bandNames(band);
            announce(`${name} moved to position ${drawn.indexOf(name) + 1} of ${drawn.length}`);
            return true;
        }
        const result = arrangement.move(name, delta, visibleNames());
        if (!result) {
            announce(`${name} is already at the ${delta < 0 ? 'top' : 'bottom'} of the list`);
            return false;
        }
        repaintKeepingFocus(name);
        const rows = visibleNames();
        const where = `position ${rows.indexOf(name) + 1} of ${rows.length}`;
        announce(result.crossed
            ? `${name} ${result.pinned ? 'pinned' : 'unpinned'}, now at ${where}`
            : `${name} moved to ${where}`);
        if (!result.crossed && window.SessionSidebarGroupOrder) {
            window.SessionSidebarGroupOrder.commitMemberOrder(name);
        }
        return true;
    }

    function togglePinRow(name) {
        const arrangement = window.SessionSidebarArrangement;
        if (!arrangement) return false;
        const now = arrangement.togglePin(name, visibleNames());
        repaintKeepingFocus(name);
        announce(now ? `${name} pinned to the top` : `${name} unpinned`);
        return now;
    }

    function onKeydown(e) {
        const row = e.target.closest && e.target.closest('.session-sidebar-row');
        if (!row || !row.dataset.name) return;
        const shell = window.CloudeWeb && window.CloudeWeb.sidebarShell;
        if (shell && typeof shell.owns === 'function' && shell.owns(e.target)) return;
        if (e.target !== row) return;
        const name = row.dataset.name;
        const rows = rowEls();
        const idx = rows.indexOf(row);

        if (window.SessionSidebarRename
            && window.SessionSidebarRename.onRowKeydown(e, row)) return;

        if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
            e.preventDefault();
            const step = e.key === 'ArrowDown' ? 1 : -1;
            if (e.altKey) { moveRow(name, step, row.dataset.band); return; }
            const next = rows[idx + step];
            if (next) setFocusRow(next.dataset.name, next.dataset.band, true);
            return;
        }
        if (e.key === 'Home' || e.key === 'End') {
            e.preventDefault();
            const target = e.key === 'Home' ? rows[0] : rows[rows.length - 1];
            if (target) setFocusRow(target.dataset.name, target.dataset.band, true);
            return;
        }
        if (e.key === 'p' || e.key === 'P') {
            e.preventDefault();
            togglePinRow(name);
            return;
        }
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            const sidebar = window.SessionSidebar;
            if (sidebar) sidebar.activateRow(row);
        }
    }

    function onPinClick(e) {
        const btn = e.target.closest && e.target.closest('[data-pin-session]');
        if (!btn) return false;
        e.stopPropagation();
        e.preventDefault();
        togglePinRow(btn.getAttribute('data-pin-session'));
        return true;
    }

    function init() {
        if (wired) return;
        const list = listEl();
        if (!list) return;
        list.addEventListener('keydown', onKeydown);
        if (window.SessionSidebarRowDrag) window.SessionSidebarRowDrag.init();
        wired = true;
    }

    window.SessionSidebarReorder = {
        init, afterRender, moveRow, togglePinRow, onPinClick, isDragging,
        setFocusRow, visibleNames, announce, tookClick, DRAG_SLOP_PX,
        rowEls, listEl, repaintKeepingFocus, bandNames, ownsOrder,
    };
    console.log('[SessionSidebarReorder Module] Exported as window.SessionSidebarReorder');
})();
