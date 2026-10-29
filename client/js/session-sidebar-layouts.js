/*  hidden  */

console.log('[SessionSidebarLayouts Module] Loading...');

(function () {
    /** @type {string} */
    const PREFIX = 'layout:';

    function tr(key, params) {
        const i18n = globalThis.CloudeI18n;
        return (i18n && typeof i18n.t === 'function') ? i18n.t(key, params) : key;
    }

    function bridge() {
        const web = window.CloudeWeb;
        return (web && web.layouts && typeof web.layouts.list === 'function') ? web.layouts : null;
    }

    function isOpenLayout(r) {
        const page = window.CloudeWeb && window.CloudeWeb.layoutPage;
        const current = (page && typeof page.current === 'function') ? page.current() : null;
        return !!(current && current.uuid === r.layout_uuid);
    }

    function isLayoutName(name) {
        return typeof name === 'string' && name.indexOf(PREFIX) === 0;
    }

    function idOf(name) { return isLayoutName(name) ? name.slice(PREFIX.length) : ''; }

    function memberRows(layout, allRows) {
        const byUuid = new Map();
        for (const r of (Array.isArray(allRows) ? allRows : [])) {
            if (r && r.session_uuid) byUuid.set(r.session_uuid, r);
        }
        const members = Array.isArray(layout.members) ? layout.members : [];
        return members.map((m) => byUuid.get(m.session_uuid)).filter(Boolean);
    }

    function rows(allRows) {
        const b = bridge();
        if (!b) return [];
        return b.list().map((L) => {
            const members = memberRows(L, allRows);
            return {
                name: PREFIX + L.layout_uuid,
                kind: 'layout',
                layout_uuid: L.layout_uuid,
                label: L.name,
                colour: L.colour, gradient: L.gradient, animation: L.animation,
                member_count: Array.isArray(L.members) ? L.members.length : 0,
                member_names: members.map((r) => (window.SessionLabel
                    ? (window.SessionLabel.resolve(r) || r.name) : (r.label || r.name))),
                _members: members,
                created_at_epoch: Date.parse(L.created_at) / 1000 || 0,
                last_work_at: null,
                project_id: null,
                project_name: null,
                working_dir: null,
            };
        });
    }

    function isExpanded(uuid) {
        const Q = window.SessionSidebarSearch;
        if (Q && typeof Q.filterActive === 'function' && Q.filterActive()) return true;
        const A = window.SessionSidebarArrangement;
        return !!(A && typeof A.isCollapsed === 'function' && A.isCollapsed(PREFIX + uuid));
    }

    function expandToggleHtml(attr, uuid, expanded) {
        const G = window.SessionSidebarGroups;
        const chevron = G && typeof G.chevronHtml === 'function' ? G.chevronHtml() : '';
        const bodyId = `session-sidebar-layout-body-${attr(uuid)}`;
        const verb = expanded ? tr('layout.row.collapse') : tr('layout.row.expand');
        return (
            '<button type="button" class="session-sidebar-layout__toggle" '
            + `data-group-toggle="${PREFIX}${attr(uuid)}" `
            + `aria-expanded="${expanded ? 'true' : 'false'}" aria-controls="${bodyId}" `
            + `title="${attr(verb)}" aria-label="${attr(verb)}">${chevron}</button>`
        );
    }

    function memberUuids() {
        const b = bridge();
        const out = new Set();
        for (const L of (b ? b.list() : [])) {
            for (const m of (Array.isArray(L.members) ? L.members : [])) if (m && m.session_uuid) out.add(m.session_uuid);
        }
        return out;
    }

    function memberBody(r, band) {
        if (band !== 'layouts') return null;
        const expanded = isExpanded(r.layout_uuid);
        return {
            bodyId: `session-sidebar-layout-body-${r.layout_uuid}`,
            uuid: r.layout_uuid,
            band: PREFIX + r.layout_uuid,
            members: expanded && Array.isArray(r._members) ? r._members : [],
        };
    }

    function iconHtml(attr) {
        const glyphs = globalThis.CloudeGlyphs;
        const svg = (glyphs && typeof glyphs.glyphSvg === 'function') ? glyphs.glyphSvg('grid', 14) : '';
        const label = tr('layout.row.icon_label');
        return svg
            ? `<span class="session-sidebar-row-provider" aria-hidden="true" title="${attr(label)}">${svg}</span>`
            : '';
    }

    function lightHtml(r, collapsed) {
        const H = window.SessionSidebarProjectHeader;
        if (H && typeof H.ledHtml === 'function') return H.ledHtml(r._members || [], collapsed, true);
        const S = window.SessionStatusSummary;
        return (S && typeof S.summaryHtml === 'function') ? S.summaryHtml(r._members || []) : '';
    }

    function membersLabel(r) {
        return tr('layout.row.members', { count: r.member_count || 0 });
    }

    function menuContext(r, band) {
        const G = window.SessionSidebarGroupStore;
        let groupUuid = (G && typeof G.groupUuidOf === 'function') ? G.groupUuidOf(band || '') : null;
        const groupRecord = (groupUuid && typeof G.groupByUuid === 'function') ? G.groupByUuid(groupUuid) : null;
        if (groupUuid && !groupRecord) groupUuid = null;
        return {
            name: r.name,
            label: r.label || '',
            layoutUuid: r.layout_uuid,
            sessionId: null,
            sessionUuid: null,
            projectId: null,
            surface: 'sidebar',
            kind: 'layout',
            owned: true,
            status: 'unknown',
            unread: false,
            asleep: false,
            restartable: false,
            pluginItems: '',
            groupable: true,
            groupUuid: groupUuid || '',
            renameable: true,
            renameReason: '',
            forkable: false,
            forkReason: '',
            muted: false,
        };
    }

    function rowHtml(r, density, band) {
        const C = window.SessionSidebarRowControls;
        if (!C) return '';
        const esc = C.escHtml;
        const attr = C.escAttr;
        const name = attr(r.name);
        const rowMenu = window.CloudeWeb && window.CloudeWeb.rowMenu;
        const menu = rowMenu ? rowMenu.triggerHtml(menuContext(r, band)) : '';
        const active = isOpenLayout(r);
        const expandable = band === 'layouts';
        const expanded = expandable && isExpanded(r.layout_uuid);
        const toggle = expandable ? expandToggleHtml(attr, r.layout_uuid, expanded) : '';
        const lightCollapsed = !expandable || !expanded;
        const G = window.SessionSidebarGroupColour;
        const colourAttrs = G ? G.layoutRowAttrs(r) : '';
        return (
            `<div class="session-sidebar-row" data-name="${name}"${colourAttrs}`
            + (band ? ` data-band="${attr(band)}" id="session-sidebar-row__${name}__${attr(band)}"` : '')
            + ` data-kind="layout" data-layout-uuid="${attr(r.layout_uuid)}" `
            + `data-active="${active ? '1' : '0'}" data-pinned="${r.is_pinned ? '1' : '0'}" `
            + 'data-rename-state="renameable" draggable="true" '
            + `role="option" aria-selected="${active ? 'true' : 'false'}" tabindex="-1">`
            + '<div class="session-sidebar-row-main">'
            + lightHtml(r, lightCollapsed)
            + toggle
            + iconHtml(attr)
            + `<span class="session-sidebar-row-name" data-row-name="${name}">${esc(r.label || r.name)}${G ? G.layoutFxHtml(r, r.label || r.name) : ''}</span>`
            + `<span class="session-sidebar-row-subtitle">${esc(membersLabel(r))}</span>`
            + C.pinButtonHtml(r.name, !!r.is_pinned)
            + menu
            + '</div></div>'
        );
    }

    function activate(ctrl, name) {
        if (!isLayoutName(name)) return false;
        const page = window.CloudeWeb && window.CloudeWeb.layoutPage;
        if (page && typeof page.openLayout === 'function') {
            page.openLayout(idOf(name));
        } else {
            window.location.assign(`/layout/${encodeURIComponent(idOf(name))}`);
        }
        return true;
    }

    function rename(uuid, name) {
        const b = bridge();
        if (!b) return Promise.reject(new Error('the layouts module is not loaded'));
        return b.rename(uuid, name);
    }

    async function remove(ctx) {
        const b = bridge();
        if (!b) return;
        const app = window.App;
        const ok = (app && typeof app.showConfirmModal === 'function')
            ? await app.showConfirmModal(
                tr('layout.remove.title'),
                tr('layout.remove.message', { name: ctx.label || ctx.name }),
                tr('layout.remove.detail'),
                tr('layout.remove.confirm'),
                undefined,
                'danger',
            )
            : window.confirm(tr('layout.remove.message', { name: ctx.label || ctx.name }));
        if (!ok) return;
        try {
            await b.delete(idOf(ctx.name));
        } catch (err) {
            console.error('SessionSidebarLayouts: remove failed:', err);
            const detail = (err && err.message) || String(err);
            alert(tr('layout.remove.failed', { reason: detail }));
        }
    }

    function blueprintsEnabled() {
        const web = window.CloudeWeb;
        return !!(web && web.blueprints && typeof web.blueprints.fromLayout === 'function');
    }

    async function saveAsBlueprint(ctx) {
        const web = window.CloudeWeb;
        if (!web || !web.blueprints || typeof web.blueprints.fromLayout !== 'function') return;
        const prompter = window.TextPromptModal;
        const defaultName = ctx.label || ctx.name || '';
        const name = (prompter && typeof prompter.open === 'function')
            ? await prompter.open({
                title: tr('blueprint.from_layout.title'),
                label: tr('blueprint.name.label'),
                defaultValue: defaultName,
                confirmLabel: tr('blueprint.save'),
                cancelLabel: tr('blueprint.cancel'),
            })
            : defaultName;
        if (name === null || name === undefined) return;
        const trimmed = String(name).trim();
        const result = await web.blueprints.fromLayout(idOf(ctx.name), trimmed || undefined);
        if (result.ok) {
            const ga = window.SessionSidebarGroupActions;
            if (ga && typeof ga.announce === 'function') ga.announce(tr('blueprint.saved', { name: result.name }));
        } else {
            alert(tr('blueprint.save_failed', { reason: result.reason }));
        }
    }

    function openColourPicker(ctx) {
        const colour = window.SessionSidebarGroupColour;
        const actions = window.SessionRowMenuActions;
        if (!colour || !actions || typeof actions.rowElementFor !== 'function') return;
        const rowEl = actions.rowElementFor(ctx);
        const anchor = rowEl ? rowEl.querySelector('[data-row-menu]') : null;
        if (!anchor) return;
        colour.openFor(anchor, 'layout', idOf(ctx.name));
    }

    function loadBlueprint(ctx) {
        const web = window.CloudeWeb;
        if (!web) return;
        const actions = window.SessionRowMenuActions;
        const rowEl = actions && typeof actions.rowElementFor === 'function' ? actions.rowElementFor(ctx) : null;
        const anchor = rowEl ? rowEl.querySelector('[data-row-menu]') : null;
        if (anchor && typeof web.openBlueprintPicker === 'function') {
            web.openBlueprintPicker(anchor);
        } else if (typeof web.openBlueprintsScreen === 'function') {
            web.openBlueprintsScreen();
        }
    }

    function runMenuItem(itemId, ctx) {
        if (itemId === 'close') return remove(ctx);
        if (itemId === 'pin') {
            const reorder = window.SessionSidebarReorder;
            if (reorder && typeof reorder.togglePinRow === 'function') reorder.togglePinRow(ctx.name);
            return Promise.resolve();
        }
        if (itemId === 'colour') {
            openColourPicker(ctx);
            return Promise.resolve();
        }
        if (itemId === 'save-blueprint') return saveAsBlueprint(ctx);
        if (itemId === 'load-blueprint') return Promise.resolve(loadBlueprint(ctx));
        return null;
    }

    let draggingUuid = null;

    function currentOrder() {
        const b = bridge();
        return b ? b.list().map((L) => L.layout_uuid) : [];
    }

    let wired = false;
    function wireDrag() {
        if (wired) return;
        wired = true;
        document.addEventListener('dragstart', (e) => {
            const row = e.target.closest && e.target.closest('[data-kind="layout"]');
            if (!row) return;
            draggingUuid = row.dataset.layoutUuid || null;
            if (e.dataTransfer) {
                e.dataTransfer.effectAllowed = 'move';
                try { e.dataTransfer.setData('text/plain', draggingUuid || ''); } catch (err) {  }
            }
        });
        document.addEventListener('dragover', (e) => {
            if (!draggingUuid) return;
            if (e.target.closest && e.target.closest('[data-kind="layout"]')) e.preventDefault();
        });
        document.addEventListener('drop', async (e) => {
            if (!draggingUuid) return;
            const target = e.target.closest && e.target.closest('[data-kind="layout"]');
            draggingUuid = null;
            if (!target) return;
            e.preventDefault();
            const overUuid = target.dataset.layoutUuid;
            const dragged = e.dataTransfer ? e.dataTransfer.getData('text/plain') : null;
            const moving = dragged || null;
            if (!moving || !overUuid || moving === overUuid) return;
            const box = target.getBoundingClientRect();
            const before = e.clientY < box.top + box.height / 2;
            const order = currentOrder().filter((u) => u !== moving);
            const at = order.indexOf(overUuid);
            const insertAt = before ? at : at + 1;
            order.splice(insertAt < 0 ? order.length : insertAt, 0, moving);
            const b = bridge();
            if (b && typeof b.reorder === 'function') {
                try {
                    await b.reorder(order);
                } catch (err) {
                    console.error('SessionSidebarLayouts: reorder failed:', err);
                }
            }
        });
        document.addEventListener('dragend', () => { draggingUuid = null; });
    }
    wireDrag();

    function bandRows(allRows) {
        const b = bridge();
        if (!b) return null;
        const byName = new Map();
        for (const r of (Array.isArray(allRows) ? allRows : [])) {
            if (r && r.kind === 'layout') byName.set(r.name, r);
        }
        const list = b.list()
            .map((L) => byName.get(PREFIX + L.layout_uuid))
            .filter(Boolean);
        if (!list.length) return null;
        return { label: tr('layout.section.heading'), rows: list };
    }

    window.SessionSidebarLayouts = {
        isLayoutName, idOf, rows, memberUuids, rowHtml, memberBody, activate, rename, runMenuItem, blueprintsEnabled, bandRows,
    };
    console.log('[SessionSidebarLayouts Module] Exported as window.SessionSidebarLayouts');
})();
