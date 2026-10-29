
console.log('[SessionSidebarGroupActions Module] Loading...');

(function () {
    let openMenu = null;

    let wired = false;

    function tr(key, params) {
        const i18n = globalThis.CloudeI18n;
        return (i18n && typeof i18n.t === 'function') ? i18n.t(key, params) : key;
    }

    function announce(text) {
        const reorder = window.SessionSidebarReorder;
        if (reorder && reorder.announce) reorder.announce(text);
    }

    function announceFailure(text) {
        announce(text);
        const notice = window.WriteFailureNotice;
        if (notice && typeof notice.report === 'function') notice.report(text);
    }

    function store() {
        const G = window.SessionSidebarGroupStore;
        return (G && G.isUsable()) ? G : null;
    }

    function esc(value) {
        return window.SessionSidebarRowControls.escHtml(value);
    }

    async function refresh() {
        const G = window.SessionSidebarGroupStore;
        if (!G) return;
        try {
            G.apply(await window.API.listSessionGroups());
        } catch (err) {
            G.markUnavailable(err && err.message ? err.message : String(err));
        }
        repaint();
    }

    function repaint() {
        const sidebar = window.SessionSidebar;
        if (sidebar && typeof sidebar.repaint === 'function') sidebar.repaint();
    }

    function applyAndRepaint(body) {
        const G = window.SessionSidebarGroupStore;
        if (G) G.apply(body);
        repaint();
    }

    async function commitAssignment(name, groupUuid) {
        const G = window.SessionSidebarGroupStore;
        if (G) G.setOptimistic(name, groupUuid);
        repaint();
        try {
            applyAndRepaint(await window.API.assignSessionGroup(name, groupUuid));
        } catch (err) {
            const reason = err && err.message ? err.message : String(err);
            await refresh();
            announceFailure(`could not move ${name}: ${reason}`);
            return false;
        }
        // own project
        // rogue agents
        const label = groupUuid
            ? (store() ? store().labelFor(store().bandKeyFor(groupUuid)) : 'a group')
            : 'its project or rogue agents';
        announce(`${name} moved to ${label}`);
        return true;
    }

    function closeMenu() {
        if (window.CloudeWeb && window.CloudeWeb.addToMenu) window.CloudeWeb.addToMenu.close();
        if (openMenu && openMenu.parentNode) openMenu.parentNode.removeChild(openMenu);
        openMenu = null;
    }

    /* <button> */
    function showMenu(anchor, entries, ariaLabel) {
        closeMenu();
        const menu = document.createElement('div');
        menu.className = 'session-sidebar-group-menu popup-focus';
        menu.setAttribute('role', 'menu');
        menu.setAttribute('aria-label', ariaLabel);
        const withIcons = entries.some((entry) => entry.icon);
        const Icons = window.SessionRowMenuIcons;
        menu.innerHTML = entries.map((entry, index) => (
            (entry.separatorBefore ? '<div class="session-sidebar-group-menu__sep" role="separator"></div>' : '')
            + `<button type="button" role="menuitem" `
            + `class="session-sidebar-group-menu__item`
            + `${entry.current ? ' session-sidebar-group-menu__item--current' : ''}`
            + `${withIcons ? ' session-sidebar-group-menu__item--with-icon' : ''}" `
            + `data-menu-index="${index}"`
            + `${entry.branch ? ' aria-haspopup="menu"' : ''}`
            + `${entry.current ? ' aria-checked="true" role="menuitemradio"' : ''}>`
            + (withIcons
                ? `<span class="session-sidebar-group-menu__icon">`
                    + `${(entry.icon && Icons) ? Icons.svg(entry.icon) : ''}</span>`
                : '')
            + `<span class="session-sidebar-group-menu__label">${esc(entry.label)}</span>`
            + (entry.branch
                ? '<span class="session-sidebar-group-menu__chevron">'
                  + '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" '
                  + 'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" '
                  + 'stroke-linejoin="round" aria-hidden="true" focusable="false" '
                  + 'data-icon="chevron-right"><path d="m7.5 4.5 8 7.5-8 7.5"/></svg></span>'
                : '')
            + `</button>`
        )).join('');
        const box = anchor.getBoundingClientRect();
        menu.style.position = 'fixed';
        menu.style.top = `${Math.round(box.bottom + 2)}px`;
        menu.style.left = `${Math.round(box.left)}px`;
        document.body.appendChild(menu);
        openMenu = menu;
        menu.addEventListener('click', (e) => {
            const btn = e.target.closest && e.target.closest('[data-menu-index]');
            if (!btn) return;
            e.preventDefault();
            e.stopPropagation();
            const entry = entries[Number(btn.getAttribute('data-menu-index'))];
            if (entry && entry.branch) {
                if (entry.onPick) entry.onPick(btn, menu);
                return;
            }
            closeMenu();
            if (entry && entry.onPick) entry.onPick();
        });
        if (entries.some((entry) => entry.branch)) {
            Array.prototype.forEach.call(menu.querySelectorAll('[data-menu-index]'), (btn) => {
                const entry = entries[Number(btn.getAttribute('data-menu-index'))];
                if (entry && entry.branch) {
                    btn.addEventListener('pointerenter', () => entry.onPick(btn, menu));
                } else {
                    btn.addEventListener('pointerenter', () => {
                        if (window.CloudeWeb && window.CloudeWeb.addToMenu) window.CloudeWeb.addToMenu.close();
                    });
                }
            });
        }
        const first = menu.querySelector('button');
        if (first) first.focus();
    }

    /* could not */
    function rowMenuItemHtml(name) {
        const G = store();
        if (!G) return '';
        const uuid = G.groupOf(name);
        const group = uuid ? G.groupByUuid(uuid) : null;
        const title = group ? 'move to another group' : 'add to a group';
        const label = group ? `Move ${name} to another group` : `Add ${name} to a group`;
        return (
            '<button type="button" class="session-row-menu-group" '
            + `data-group-pick="${esc(name)}" `
            + `title="${esc(title)}" aria-label="${esc(label)}" `
            + 'aria-haspopup="menu">'
            + '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" '
            + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
            + 'stroke-linejoin="round" aria-hidden="true">'
            + '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 '
            + '2-2h5l2 3h9a2 2 0 0 1 2 2z"/>'
            + '</svg>'
            + '</button>'
        );
    }

    function openPickerFor(anchor, name) {
        const G = store();
        if (!G) {
            announceFailure('groups are unavailable, so this agent cannot be filed');
            return;
        }
        const currentUuid = G.groupOf(name);
        const entries = G.current().groups.map((group) => ({
            label: group.name,
            current: group.group_uuid === currentUuid,
            onPick: () => commitAssignment(name, group.group_uuid),
        }));
        entries.push({
            label: 'other (no group)',
            current: currentUuid === null,
            onPick: () => commitAssignment(name, null),
        });
        entries.push({
            label: 'new group...',
            current: false,
            onPick: () => createGroupThenAssign(name),
        });
        showMenu(anchor, entries, `Move ${name} to a group`);
    }

    async function createGroupThenAssign(name) {
        const raw = await window.TextPromptModal.open({
            title: tr('sidebar.group.new.title'),
            label: tr('sidebar.group.new.label'),
            placeholder: tr('sidebar.group.new.placeholder'),
            confirmLabel: tr('sidebar.group.new.create'),
            cancelLabel: tr('sidebar.group.new.cancel'),
        });
        if (raw === null) return;
        try {
            const body = await window.API.createSessionGroup(raw);
            applyAndRepaint(body);
            const made = (body.groups || []).find((g) => g.name === String(raw).trim()
                || g.name === raw.split(/\s+/).filter(Boolean).join(' '));
            if (name && made) await commitAssignment(name, made.group_uuid);
            else announce(`group ${raw} created`);
        } catch (err) {
            announceFailure(`could not create the group: ${err && err.message ? err.message : err}`);
        }
    }

    function openGroupMenu(anchor, groupUuid) {
        const G = store();
        if (!G) return;
        const group = G.groupByUuid(groupUuid);
        if (!group) return;
        const order = G.current().groups.map((g) => g.group_uuid);
        const at = order.indexOf(groupUuid);
        const entries = [
            { label: 'rename', icon: 'rename', id: 'rename-group', onPick: () => renameGroup(groupUuid, anchor) },
            {
                label: 'add',
                icon: 'add',
                id: 'add-members',
                branch: true,
                onPick: (itemEl, panelEl) => {
                    const bridge = window.CloudeWeb && window.CloudeWeb.addToMenu;
                    if (bridge && typeof bridge.openForGroup === 'function') {
                        bridge.openForGroup(itemEl || anchor, groupUuid, { parentEl: panelEl, onFinish: closeMenu });
                    }
                },
            },
            {
                label: tr('sidebar.group.colour.menu'),
                icon: 'colour',
                id: 'colour',
                onPick: () => window.SessionSidebarGroupColour
                    && window.SessionSidebarGroupColour.open(anchor, groupUuid),
            },
            {
                label: tr('sidebar.group.icon.menu'),
                icon: 'group-icon',
                id: 'group-icon',
                onPick: () => window.SessionSidebarGroupIcon
                    && window.SessionSidebarGroupIcon.open(anchor, groupUuid),
            },
            {
                label: tr('sidebar.heading.sleep'),
                icon: 'sleep',
                id: 'sleep',
                onPick: () => window.SessionSidebarHeadingActions.sleepGroup(groupUuid),
            },
            {
                label: 'move up',
                icon: 'move-up',
                id: 'move-up',
                onPick: () => moveGroup(groupUuid, -1),
            },
            {
                label: 'move down',
                icon: 'move-down',
                id: 'move-down',
                onPick: () => moveGroup(groupUuid, 1),
            },
            {
                // own project rogue agents
                label: `remove (${group.members.length} `
                    + `${group.members.length === 1
                        ? 'agent moves to its project or rogue agents'
                        : 'agents move to their project or rogue agents'})`,
                icon: 'close',
                id: 'delete-group',
                onPick: () => deleteGroup(groupUuid),
            },
        ];
        const up = entries.findIndex((entry) => entry.icon === 'move-up');
        if (at === order.length - 1) entries.splice(up + 1, 1);
        if (at === 0) entries.splice(up, 1);
        showMenu(anchor, entries, `Actions for the ${group.name} group`);
    }

    function renameGroup(groupUuid, anchor) {
        const G = store();
        const group = G && G.groupByUuid(groupUuid);
        if (!group) return;
        const R = window.SessionSidebarRename;
        if (!R || R.openHeadingEditor(anchor, {
            seed: group.name,
            ariaLabel: `Rename group ${group.name}`,
            save: (value) => window.API.renameSessionGroup(groupUuid, value),
            successText: (value) => `group renamed to ${value}`,
            afterSuccess: (body) => applyAndRepaint(body),
        }) === null) announceFailure('could not open the rename editor');
    }

    /* own project rogue agents */
    async function deleteGroup(groupUuid) {
        const G = store();
        const group = G && G.groupByUuid(groupUuid);
        if (!group) return;
        const count = group.members.length;
        const noun = count === 1 ? 'agent' : 'agents';
        const ok = await window.App.showConfirmModal(
            tr('sidebar.group.remove.title'),
            tr('sidebar.group.remove.message', { name: group.name }),
            tr('sidebar.group.remove.detail', { count }),
            tr('sidebar.group.remove.confirm'),
            tr('sidebar.group.remove.cancel'),
            'danger',
        );
        if (!ok) return;
        try {
            const body = await window.API.deleteSessionGroup(groupUuid);
            applyAndRepaint(body);
            announce(`group ${group.name} removed, ${body.freed} ${noun} `
                + 'filed under their project or rogue agents');
        } catch (err) {
            announceFailure(`could not remove: ${err && err.message ? err.message : err}`);
        }
    }

    async function moveGroup(groupUuid, delta) {
        const G = store();
        if (!G) return;
        const order = G.current().groups.map((g) => g.group_uuid);
        const at = order.indexOf(groupUuid);
        const to = at + (delta < 0 ? -1 : 1);
        if (at === -1 || to < 0 || to >= order.length) return;
        const next = order.slice();
        next[at] = order[to];
        next[to] = groupUuid;
        try {
            applyAndRepaint(await window.API.reorderSessionGroups(next));
            announce(`group moved to position ${to + 1} of ${order.length}`);
        } catch (err) {
            await refresh();
            announceFailure(`could not reorder: ${err && err.message ? err.message : err}`);
        }
    }

    function init() {
        if (wired) return;
        const CC = () => window.SessionSidebarChromeClicks;
        const shellOwns = (target) => !!(CC() && CC().shellOwns && CC().shellOwns(target));
        document.addEventListener('click', (e) => {
            const groupMenu = !shellOwns(e.target) && e.target.closest && e.target.closest('[data-group-menu]');
            if (groupMenu) {
                e.preventDefault();
                e.stopPropagation();
                openGroupMenu(groupMenu, groupMenu.getAttribute('data-group-menu'));
                return;
            }
            const picker = e.target.closest && e.target.closest('[data-group-pick]');
            if (picker) {
                e.preventDefault();
                e.stopPropagation();
                openPickerFor(picker, picker.getAttribute('data-group-pick'));
                return;
            }
            if (openMenu && !openMenu.contains(e.target)) {
                const cascadeHost = document.getElementById('add-to-cascade-menu');
                if (!(cascadeHost && cascadeHost.contains(e.target))) closeMenu();
            }
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && openMenu) {
                closeMenu();
                return;
            }
            const row = e.target.closest && e.target.closest('.session-sidebar-row');
            if (row && e.key === 'g' && !e.altKey && !e.metaKey && !e.ctrlKey) {
                e.preventDefault();
                openPickerFor(row, row.dataset.name);
                return;
            }
            const header = e.target.closest && e.target.closest('[data-group-toggle]');
            if (header && e.key === 'F2' && !shellOwns(e.target)) {
                const G = window.SessionSidebarGroupStore;
                const uuid = G && G.groupUuidOf(header.getAttribute('data-group-toggle'));
                if (uuid) {
                    e.preventDefault();
                    renameGroup(uuid, header);
                }
            }
        });
        wired = true;
    }

    window.SessionSidebarGroupActions = {
        init, refresh, commitAssignment, openPickerFor, openGroupMenu,
        renameGroup, deleteGroup, moveGroup, createGroupThenAssign,
        closeMenu, rowMenuItemHtml,
        showMenu, announce, repaint,
    };
    console.log('[SessionSidebarGroupActions Module] Exported as window.SessionSidebarGroupActions');
})();
