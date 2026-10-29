
console.log('[SessionSidebarBrowsers Module] Loading...');

(function () {
    /** @type {string} */
    const PREFIX = 'browser:';

    function tr(key, params) {
        const i18n = globalThis.CloudeI18n;
        return (i18n && typeof i18n.t === 'function') ? i18n.t(key, params) : key;
    }

    function bridge() {
        const web = window.CloudeWeb;
        return (web && web.browsers && typeof web.browsers.list === 'function') ? web.browsers : null;
    }

    function isBrowserName(name) {
        return typeof name === 'string' && name.indexOf(PREFIX) === 0;
    }

    function idOf(name) { return isBrowserName(name) ? name.slice(PREFIX.length) : ''; }

    function rows() {
        const b = bridge();
        if (!b) return [];
        const pageRows = (typeof b.pages === 'function' ? b.pages() : []).map((page) => ({
            name: PREFIX + page.id,
            kind: 'browser',
            browser_id: page.id,
            page: true,
            section: typeof page.section === 'string' && page.section ? page.section : null,
            label: page.title,
            url: null,
            status: 'page',
            created_at_epoch: Number(page.opened_at) || 0,
            last_work_at: null,
            project_id: null,
            project_name: null,
            working_dir: null,
        }));
        return b.list().map((info) => ({
            name: PREFIX + info.id,
            kind: 'browser',
            browser_id: info.id,
            label: info.label,
            url: info.url,
            status: info.state,
            created_at_epoch: Date.parse(info.created_at) / 1000 || 0,
            last_work_at: null,
            project_id: null,
            project_name: null,
            working_dir: null,
        })).concat(pageRows);
    }

    function activate(ctrl, name) {
        if (!isBrowserName(name)) return false;
        const b = bridge();
        if (b) b.open(idOf(name));
        if (ctrl && typeof ctrl._closeAfterSwitch === 'function') ctrl._closeAfterSwitch();
        return true;
    }

    function rename(id, label) {
        const b = bridge();
        if (!b) return Promise.reject(new Error('the browser module is not loaded'));
        return b.rename(id, label);
    }

    async function close(ctx) {
        const b = bridge();
        if (!b) return;
        if (ctx.isPage || ctx.isFile) {
            try {
                await b.close(idOf(ctx.name));
            } catch (err) {
                console.error('SessionSidebarBrowsers: close page failed:', err);
                alert(tr('browser.close_failed', { detail: (err && err.message) || String(err) }));
            }
            return;
        }
        const app = window.App;
        const ok = (app && typeof app.showConfirmModal === 'function')
            ? await app.showConfirmModal(tr('browser.close.confirm'), ctx.label || ctx.name,
                tr('browser.close.detail'), tr('browser.menu.close'), undefined, 'danger')
            : window.confirm(tr('browser.close.confirm'));
        if (!ok) return;
        try {
            await b.close(idOf(ctx.name));
        } catch (err) {
            console.error('SessionSidebarBrowsers: close failed:', err);
            alert(tr('browser.close_failed', { detail: (err && err.message) || String(err) }));
        }
    }

    function runMenuItem(itemId, ctx) {
        if (itemId === 'close') return close(ctx);
        if (itemId === 'popout') {
            const b = bridge();
            return b && typeof b.popOut === 'function' ? b.popOut(idOf(ctx.name)) : Promise.resolve();
        }
        if (itemId === 'pin') {
            const reorder = window.SessionSidebarReorder;
            if (reorder && typeof reorder.togglePinRow === 'function') reorder.togglePinRow(ctx.name);
            return Promise.resolve();
        }
        return null;
    }

    function onKeyClick(keyEl) {
        const rowEl = keyEl.closest('.session-sidebar-row');
        if (!rowEl) return Promise.resolve();
        const name = rowEl.getAttribute('data-name') || '';
        if (keyEl.getAttribute('data-browser-row-action') === 'close') {
            const menu = window.CloudeWeb && window.CloudeWeb.rowMenu;
            const trigger = rowEl.querySelector('[data-row-menu]');
            const ctx = (menu && typeof menu.contextFromTrigger === 'function' && menu.contextFromTrigger(trigger))
                || { name, label: '', isPage: false };
            return runMenuItem('close', ctx) || Promise.resolve();
        }
        return runMenuItem('popout', { name }) || Promise.resolve();
    }

    window.SessionSidebarBrowsers = {
        isBrowserName, rows, activate, rename, runMenuItem, onKeyClick,
    };
    console.log('[SessionSidebarBrowsers Module] Exported as window.SessionSidebarBrowsers');
})();
