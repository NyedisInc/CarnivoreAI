
console.log('[SessionSidebarGroupIcon Module] Loading...');

(function () {
    const MOUNT_ID = 'group-icon-picker-mount';

    const MARK_SIZE = 12;

    /** @type {HTMLElement|null} */
    let openPopup = null;
    /** @type {boolean} */
    let wired = false;

    function tr(key, params) {
        const i18n = globalThis.CloudeI18n;
        return (i18n && typeof i18n.t === 'function') ? i18n.t(key, params) : key;
    }

    function groupFor(groupUuid) {
        const G = window.SessionSidebarGroupStore;
        return (G && G.isUsable() && groupUuid) ? G.groupByUuid(groupUuid) : null;
    }

    function iconOf(groupUuid) {
        const group = groupFor(groupUuid);
        return group && typeof group.icon === 'string' && group.icon ? group.icon : null;
    }

    function markHtml(iconId) {
        if (!iconId) return '';
        const glyphs = globalThis.CloudeGlyphs;
        const svg = (glyphs && typeof glyphs.iconSvg === 'function') ? glyphs.iconSvg(iconId, MARK_SIZE) : '';
        return svg
            ? `<span class="session-sidebar-group__icon" data-group-icon="${iconId.replace(/[^a-z0-9-]/g, '')}" aria-hidden="true">${svg}</span>`
            : '';
    }

    function headingMark(groupUuid) {
        return groupUuid ? markHtml(iconOf(groupUuid)) : '';
    }

    function close() {
        const web = window.CloudeWeb;
        if (web && web.iconPicker) web.iconPicker.unmount(MOUNT_ID);
        if (openPopup && openPopup.parentNode) openPopup.parentNode.removeChild(openPopup);
        openPopup = null;
    }

    async function setIcon(groupUuid, iconId) {
        const G = window.SessionSidebarGroupStore;
        const actions = window.SessionSidebarGroupActions;
        try {
            const body = await window.API.setSessionGroupIcon(groupUuid, iconId);
            if (G) G.apply(body);
            if (actions) actions.repaint();
            return true;
        } catch (err) {
            if (actions) await actions.refresh();
            const reason = err && err.message ? err.message : String(err);
            const notice = window.WriteFailureNotice;
            if (notice && typeof notice.report === 'function') {
                notice.report(tr('sidebar.group.icon.failed', { reason }));
            }
            return false;
        }
    }

    function open(anchor, groupUuid) {
        close();
        const group = groupFor(groupUuid);
        if (!group) return;
        const web = window.CloudeWeb;
        if (!web || !web.iconPicker) {
            const notice = window.WriteFailureNotice;
            if (notice && typeof notice.report === 'function') notice.report(tr('sidebar.group.icon.unavailable'));
            return;
        }
        const el = document.createElement('div');
        el.className = 'group-icon-picker popup-focus';
        el.setAttribute('role', 'dialog');
        el.setAttribute('aria-label', tr('sidebar.group.icon.title_named', { name: group.name }));
        el.dataset.groupUuid = groupUuid;
        const colours = window.SessionSidebarGroupColour ? window.SessionSidebarGroupColour.COLOURS : [];
        const hue = colours.includes(group.colour) ? ` style="--icon-hue: var(--drawer-hue-${group.colour})"` : '';
        el.innerHTML = `<div class="group-colour-picker__title">${tr('sidebar.group.icon.title')}</div>`
            + `<div class="group-icon-picker__body" id="${MOUNT_ID}"${hue}></div>`;
        const box = anchor.getBoundingClientRect();
        el.style.top = `${Math.round(box.bottom + 2)}px`;
        document.body.appendChild(el);
        openPopup = el;
        web.iconPicker.mount(MOUNT_ID, {
            value: iconOf(groupUuid),
            onChange: (id) => { void setIcon(groupUuid, id); queueMicrotask(close); },
            onCancel: close,
            autofocus: true,
        });
        const left = Math.min(box.left, window.innerWidth - el.offsetWidth - 8);
        el.style.left = `${Math.max(8, Math.round(left))}px`;
        const bottomGap = window.innerHeight - (box.bottom + 2 + el.offsetHeight) - 8;
        if (bottomGap < 0) el.style.top = `${Math.max(8, Math.round(box.bottom + 2 + bottomGap))}px`;
        wire();
    }

    function wire() {
        if (wired) return;
        document.addEventListener('mousedown', (e) => {
            if (openPopup && !openPopup.contains(e.target)) close();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && openPopup) close();
        });
        wired = true;
    }

    window.SessionSidebarGroupIcon = { iconOf, markHtml, headingMark, open, close, setIcon, MOUNT_ID };
    console.log('[SessionSidebarGroupIcon Module] Exported as window.SessionSidebarGroupIcon');
})();
