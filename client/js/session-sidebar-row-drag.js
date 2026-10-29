/* rogue agents */

console.log('[SessionSidebarRowDrag Module] Loading...');

(function () {
    function R() { return window.SessionSidebarReorder || null; }

    const TOUCH_EXTRA_SLOP_PX = 10;

    function slop(pointerType) {
        const r = R();
        const base = (r && r.DRAG_SLOP_PX) || 4;
        return pointerType === 'touch' ? base + TOUCH_EXTRA_SLOP_PX : base;
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
        const r = R();
        return r ? r.visibleNames() : [];
    }

    function repaintKeepingFocus(name) {
        const r = R();
        if (r) r.repaintKeepingFocus(name);
    }

    function announce(text) {
        const r = R();
        if (r) r.announce(text);
    }

    let drag = null;

    let claimedClick = false;

    let wired = false;

    function isDragging() { return !!drag && drag.active; }

    function onPointerDown(e) {
        claimedClick = false;
        if (drag) return;
        if (typeof e.button === 'number' && e.button !== 0) return;
        const grip = e.target.closest && e.target.closest('[data-grip-session]');
        const row = grip
            ? grip.closest('.session-sidebar-row')
            : (e.target.closest && e.target.closest('.session-sidebar-row'));
        if (!row || !row.dataset.name) return;
        const shell = window.CloudeWeb && window.CloudeWeb.sidebarShell;
        if (shell && typeof shell.owns === 'function' && shell.owns(e.target)) return;
        if (row.dataset.band === 'layouts') return;
        if (!grip) {
            if (e.target.closest('button, input, textarea, select, a, [contenteditable]')) return;
            if (e.pointerType === 'touch') return;
        } else {
            e.preventDefault();
            e.stopPropagation();
        }
        drag = {
            name: row.dataset.name,
            band: row.dataset.band || null,
            bandMoved: false,
            startX: e.clientX,
            startY: e.clientY,
            claimedClick: false,
            active: false,
            crossed: undefined,
            group: undefined,
            groupChanged: false,
            pointerId: e.pointerId,
            pointerType: e.pointerType,
        };
        const handle = grip || row;
        if (handle.setPointerCapture) {
            try { handle.setPointerCapture(e.pointerId); } catch (_) {  }
        }
    }

    function onPointerMove(e) {
        if (!drag) return;
        if (handOff(e)) return;
        if (!drag.active) {
            if (Math.abs(e.clientY - drag.startY) < slop(drag.pointerType)) return;
            drag.active = true;
            drag.claimedClick = true;
            if (e.cancelable) e.preventDefault();
            const sel = window.getSelection && window.getSelection();
            if (sel && sel.removeAllRanges) sel.removeAllRanges();
            const list = listEl();
            if (list) list.classList.add('session-sidebar-list--dragging');
            const sidebar = window.SessionSidebar;
            if (sidebar) sidebar.setDragging(true);
        }
        const arrangement = window.SessionSidebarArrangement;
        if (!arrangement) return;
        const G = window.SessionSidebarGroupStore;
        const overKey = window.SessionSidebarDropTarget.bandKeyAt(e.clientY);
        if (overKey !== null && overKey === drag.band && reorderInBand(e.clientY)) return;
        if (overKey !== null && G && !G.isFilingBand(overKey)) return;
        const rows = rowEls();
        let beforeName = null;
        for (const el of rows) {
            if (el.dataset.name === drag.name) continue;
            const box = el.getBoundingClientRect();
            if (e.clientY < box.top + box.height / 2) {
                beforeName = el.dataset.name;
                break;
            }
        }
        const intent = (overKey !== null && G)
            ? G.bandIntent(overKey)
            : { pinned: arrangement.isPinned(drag.name), group: undefined };

        if (G && intent.group !== undefined) {
            const before = G.setOptimistic(drag.name, intent.group);
            if (before !== intent.group) drag.groupChanged = true;
            drag.group = intent.group;
        }

        const result = arrangement.placeAt(
            drag.name, intent.pinned, beforeName, visibleNames(),
        );
        if (!result) {
            if (drag.groupChanged) repaintKeepingFocus(drag.name);
            return;
        }
        if (result.crossed) drag.crossed = result.pinned;
        repaintKeepingFocus(drag.name);
    }

    function handOff(e) {
        if (drag.pointerType === 'touch') return false;
        const web = window.CloudeWeb;
        const list = listEl();
        if (!list || !web || !web.tabDrag) return false;
        const box = list.getBoundingClientRect();
        const dx = Math.abs(e.clientX - drag.startX);
        const sideways = !drag.active && dx >= slop(drag.pointerType) && dx > Math.abs(e.clientY - drag.startY);
        if (!sideways && e.clientX >= box.left && e.clientX <= box.right) return false;
        const taken = web.tabDrag.begin({
            name: drag.name,
            pointerId: drag.pointerId,
            pointerType: drag.pointerType,
            clientX: e.clientX,
            clientY: e.clientY,
        });
        if (!taken) return false;
        drag.claimedClick = true;
        onPointerUp(e);
        return true;
    }

    function reorderInBand(clientY) {
        const r = R();
        const arrangement = window.SessionSidebarArrangement;
        if (!r || !arrangement || !arrangement.placeInBand || !r.ownsOrder(drag.band)) return false;
        const inBand = rowEls().filter((el) => el.dataset.band === drag.band);
        const names = inBand.map((el) => el.dataset.name);
        if (names.indexOf(drag.name) === -1) return false;
        let beforeName = null;
        for (const el of inBand) {
            if (el.dataset.name === drag.name) continue;
            const box = el.getBoundingClientRect();
            if (clientY < box.top + box.height / 2) {
                beforeName = el.dataset.name;
                break;
            }
        }
        if (arrangement.placeInBand(drag.band, drag.name, beforeName, names)) {
            drag.bandMoved = true;
            r.repaintKeepingFocus(drag.name, drag.band);
        }
        return true;
    }

    function onPointerUp(e) {
        if (!drag) return;
        const wasActive = drag.active;
        claimedClick = drag.claimedClick;
        const name = drag.name;
        const crossed = drag.crossed;
        const group = drag.group;
        const groupChanged = drag.groupChanged;
        const band = drag.band;
        const bandMoved = drag.bandMoved;
        drag = null;
        const list = listEl();
        if (list) list.classList.remove('session-sidebar-list--dragging');
        const sidebar = window.SessionSidebar;
        if (sidebar) sidebar.setDragging(false);
        if (!wasActive) return;
        const r = R();
        if (bandMoved && !groupChanged && crossed === undefined && r) {
            const drawn = r.bandNames(band);
            announce(`${name} moved to position ${drawn.indexOf(name) + 1} of ${drawn.length}`);
            return;
        }
        const rows = visibleNames();
        const where = `position ${rows.indexOf(name) + 1} of ${rows.length}`;
        const actions = window.SessionSidebarGroupActions;
        if (groupChanged && actions) {
            actions.commitAssignment(name, group === undefined ? null : group);
            return;
        }
        announce(crossed === undefined
            ? `${name} moved to ${where}`
            : `${name} ${crossed ? 'pinned' : 'unpinned'}, now at ${where}`);
        if (crossed === undefined && window.SessionSidebarGroupOrder) {
            window.SessionSidebarGroupOrder.commitMemberOrder(name);
        }
    }

    function tookClick() {
        const was = claimedClick;
        claimedClick = false;
        return was;
    }

    function init() {
        if (wired) return;
        const list = listEl();
        if (!list) return;
        list.addEventListener('pointerdown', onPointerDown);
        document.addEventListener('pointermove', onPointerMove);
        document.addEventListener('pointerup', onPointerUp);
        document.addEventListener('pointercancel', onPointerUp);
        wired = true;
    }

    window.SessionSidebarRowDrag = {
        init, isDragging, tookClick, slop, TOUCH_EXTRA_SLOP_PX,
    };
})();

console.log('[SessionSidebarRowDrag Module] Exported as window.SessionSidebarRowDrag');
