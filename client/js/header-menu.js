
(function () {
console.log('[HeaderMenu Module] Loading...');

const HEADER_MENU_CONTROL_IDS = [
    'logoutBtn',
    'settingsBtn',
    'headerMasterAllBtn'
];

/* the drawer toggle */
const HEADER_TOOL_CONTROL_IDS = [
    'configEditorBtn',
    'sessionNotesBtn',
];

const HEADER_SESSION_CONTROL_IDS = [
    'headerSessionThemeBtn',
    'headerDetachBtn',
    'headerSizeMasterBtn',
    'headerComponentsBtn',
];

const FOLD_QUERY = '(max-width: 768px)';

const HEADER_MENU_ROW_LABEL_KEYS = {
    headerSessionThemeBtn: 'header.menu.theme',
    logoutBtn: 'header.menu.logout',
    settingsBtn: 'header.menu.settings',
    headerDetachBtn: 'header.menu.pause',
    sessionNotesBtn: 'header.notes.label',
    headerSizeMasterBtn: 'header.menu.master',
    headerMasterAllBtn: 'header.menu.master_all',
};

function catalogText(key) {
    const i18n = globalThis.CloudeI18n;
    return i18n && typeof i18n.t === 'function' ? i18n.t(key) : key;
}

function foldOrder() {
    return HEADER_SESSION_CONTROL_IDS
        .concat(HEADER_TOOL_CONTROL_IDS)
        .concat(HEADER_MENU_CONTROL_IDS);
}

class HeaderMenu {
    constructor() {
        /** @type {Element|null} */ this.controls = null;
        /** @type {Element|null} */ this.toggle = null;
        /** @type {Element|null} */ this.panel = null;
        /** @type {boolean} */ this.isOpen = false;
        /** @type {boolean} */ this.isFolded = false;
        /** @type {MediaQueryList|null} */ this._foldQuery = null;
        /** @type {boolean} True while the phone tab strip owns the page's top bar (below 1024, issue #1551). */
        this._stripOwnsBar = false;
    }

    init() {
        if (this.panel) return;
        this.controls = document.querySelector('.header .controls');
        if (!this.controls) {
            console.warn('[HeaderMenu] no .header .controls, skipping');
            return;
        }

        this._buildChrome();
        this._buildSessionRows();
        this._buildMasterAllRow();
        this._wireEvents();
        this._wireFoldQuery();
        this.applyLayout();
        console.log('[HeaderMenu] initialized');
    }

    _buildChrome() {
        const toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.id = 'header-menu-toggle';
        toggle.className = 'btn-icon header-menu-toggle';
        toggle.setAttribute('data-tooltip', '');
        toggle.setAttribute('aria-label', catalogText('header.menu.more_actions'));
        toggle.setAttribute('aria-haspopup', 'true');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.setAttribute('aria-controls', 'header-menu-panel');
        toggle.innerHTML = window.KebabIcon.svg(window.KebabIcon.DEFAULT_SIZE);

        const panel = document.createElement('div');
        panel.id = 'header-menu-panel';
        panel.className = 'header-menu-panel popup-focus';
        panel.setAttribute('role', 'menu');
        panel.setAttribute('aria-label', catalogText('header.menu.more_actions'));
        panel.setAttribute('data-tooltip-off', '');
        panel.hidden = true;

        this.controls.appendChild(toggle);
        this.controls.appendChild(panel);
        this.toggle = toggle;
        this.panel = panel;
    }

    _wireEvents() {
        this.toggle.addEventListener('click', (e) => {
            e.stopPropagation();
            this.isOpen ? this.close() : this.open();
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isOpen) {
                this.close();
                this.toggle.focus();
            }
        });

        window.DismissGuard.onOutsideDismiss(this.panel, () => this.close(), {
            trigger: this.toggle,
            isOpen: () => this.isOpen
        });

        this.panel.addEventListener('click', (e) => {
            if (e.target === this.panel) return;
            this.close();
        });
    }

    _wireFoldQuery() {
        if (typeof window.matchMedia !== 'function') return;
        this._foldQuery = window.matchMedia(FOLD_QUERY);
        if (typeof this._foldQuery.addEventListener === 'function') {
            this._foldQuery.addEventListener('change', () => this.applyLayout());
        }
    }

    /* there is nothing */
    _buildSessionRows() {
        const t = catalogText;
        const shared = globalThis.CloudeLabels;
        const labels = shared && typeof shared.headerActionLabels === 'function'
            ? shared.headerActionLabels(t)
            : {
                components: { label: t('header.components'), hint: t('header.components_hint') },
                pause: { label: t('header.pause'), hint: t('header.pause_hint') },
            };

        const theme = document.createElement('button');
        theme.type = 'button';
        theme.id = 'headerSessionThemeBtn';
        theme.className = 'btn-icon';
        theme.setAttribute('aria-label', catalogText('header.menu.session_theme'));
        theme.setAttribute('title', catalogText('header.menu.session_theme'));
        theme.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none">' +
            '<path d="M8 1.75a6.25 6.25 0 1 0 0 12.5c.69 0 1.25-.56 1.25-1.25 0-.32-.13-.62-.34-.84a1.19 1.19 0 0 1 .84-2.03h1.44A3.06 3.06 0 0 0 14.25 7 6.25 6.25 0 0 0 8 1.75Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>' +
            '<circle cx="5.25" cy="6" r="0.9" fill="currentColor"/>' +
            '<circle cx="8" cy="4.5" r="0.9" fill="currentColor"/>' +
            '<circle cx="10.75" cy="6" r="0.9" fill="currentColor"/>' +
            '</svg>';
        theme.addEventListener('click', () => {
            if (window.SessionThemeMenu) window.SessionThemeMenu.open(this.toggle);
        });

        const detach = document.createElement('button');
        detach.type = 'button';
        detach.id = 'headerDetachBtn';
        detach.className = 'btn-icon';
        detach.setAttribute('aria-label', labels.pause.hint);
        detach.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none">' +
            '<path d="M5.75 3.5V12.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>' +
            '<path d="M10.25 3.5V12.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>' +
            '</svg>';
        detach.addEventListener('click', () => {
            const ctl = window.TerminalController;
            if (ctl && typeof ctl.detachSession === 'function') ctl.detachSession();
        });

        const copy = labels.components;

        const components = document.createElement('button');
        components.type = 'button';
        components.id = 'headerComponentsBtn';
        components.className = 'btn-icon';
        components.setAttribute('aria-label', copy.hint);
        components.setAttribute('title', copy.label);
        components.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none">' +
            '<rect x="2.25" y="2.25" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.5"/>' +
            '<rect x="8.75" y="2.25" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.5"/>' +
            '<rect x="2.25" y="8.75" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.5"/>' +
            '<rect x="8.75" y="8.75" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.5"/>' +
            '</svg>';
        components.addEventListener('click', () => {
            const host = globalThis.CloudeWeb;
            if (!host || typeof host.openTerminalComponents !== 'function') {
                console.warn('[HeaderMenu] the compiled bundle is not loaded');
                return;
            }
            if (typeof host.terminalComponentsOpen === 'function' && host.terminalComponentsOpen()) {
                host.closeTerminalComponents();
                return;
            }
            host.openTerminalComponents(this.toggle);
        });

        const sizeMaster = this._buildSizeMasterRow();

        this.controls.appendChild(theme);
        this.controls.appendChild(detach);
        this.controls.appendChild(sizeMaster);
        this.controls.appendChild(components);
    }

    _buildSizeMasterRow() {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.id = 'headerSizeMasterBtn';
        btn.className = 'btn-icon';
        btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none">' +
            '<path d="M2.5 11.5 1.75 5 5 8l3-5.25L11 8l3.25-3-.75 6.5z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>' +
            '<path d="M2.5 13.75h11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>' +
            '</svg>';
        btn.addEventListener('click', () => {
            void this._toggleSizeMaster(btn);
        });
        window.addEventListener('cloude:size-master', (event) => {
            const detail = event && event.detail;
            if (!detail || detail.sessionId !== this._currentSessionId()) return;
            this._refreshSizeMasterRow(btn);
        });
        this._refreshSizeMasterRow(btn);
        return btn;
    }

    _currentSessionId() {
        const ctl = window.TerminalController;
        if (!ctl || typeof ctl._sessionId !== 'function') return null;
        const id = ctl._sessionId();
        return id && id.trim() ? id.trim() : null;
    }

    async _toggleSizeMaster(btn) {
        if (btn.disabled) return;
        const sessionId = this._currentSessionId();
        const web = globalThis.CloudeWeb;
        if (!sessionId || !web || typeof web.claimSizeMaster !== 'function') {
            console.warn('[HeaderMenu] size master: no session or the compiled bundle is not loaded');
            return;
        }
        btn.disabled = true;
        try {
            const holder = web.sizeMasterHolder(sessionId);
            const mine = holder && holder === web.sizeMasterClientId();
            if (mine) await web.releaseSizeMaster(sessionId);
            else await web.claimSizeMaster(sessionId);
        } catch (err) {
            console.error('[HeaderMenu] size master change failed:', err);
        } finally {
            btn.disabled = false;
            this._refreshSizeMasterRow(btn);
        }
    }

    _refreshSizeMasterRow(btn) {
        const sessionId = this._currentSessionId();
        const web = globalThis.CloudeWeb;
        const holder = sessionId && web && typeof web.sizeMasterHolder === 'function'
            ? web.sizeMasterHolder(sessionId) : null;
        const mine = !!(holder && web && holder === web.sizeMasterClientId());
        const role = !sessionId ? 'none' : (holder ? (mine ? 'master' : 'watcher') : 'none');
        const label = catalogText('terminal.size_master.' + role);
        btn.setAttribute('aria-label', label);
        btn.setAttribute('data-tooltip', label);
        btn.setAttribute('aria-pressed', mine ? 'true' : 'false');
        btn.setAttribute('data-size-master', role);
        btn.disabled = !sessionId;
    }

    _buildMasterAllRow() {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.id = 'headerMasterAllBtn';
        btn.className = 'btn-icon';
        btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none">' +
            '<path d="M2.5 11.5 1.75 5 5 8l3-5.25L11 8l3.25-3-.75 6.5z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>' +
            '<path d="M2.5 13.75h11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>' +
            '</svg>';
        const refresh = () => this._refreshMasterAllRow(btn);
        btn.addEventListener('click', () => {
            const web = globalThis.CloudeWeb;
            if (!web || typeof web.setMasterAll !== 'function') {
                console.warn('[HeaderMenu] master all: the compiled bundle is not loaded');
                return;
            }
            web.setMasterAll(!web.masterAllEnabled());
            refresh();
        });
        window.addEventListener('cloude:master-all', refresh);
        refresh();
        this.controls.appendChild(btn);
    }

    _refreshMasterAllRow(btn) {
        const web = globalThis.CloudeWeb;
        const on = !!(web && typeof web.masterAllEnabled === 'function' && web.masterAllEnabled());
        const label = catalogText('header.master_all');
        btn.setAttribute('aria-label', label);
        btn.setAttribute('data-tooltip', label);
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    }

    applyLayout() {
        const shouldFold = this._stripOwnsBar || (this._foldQuery ? this._foldQuery.matches : true);
        if (shouldFold === this.isFolded) return;
        if (shouldFold) this._fold();
        else this._unfold();
    }

    setStripOwnsBar(on) {
        this._stripOwnsBar = !!on;
        if (this.panel) this.applyLayout();
    }

    _fold() {
        for (const id of foldOrder()) {
            const el = document.getElementById(id);
            if (!el) continue;
            const labelKey = HEADER_MENU_ROW_LABEL_KEYS[id];
            if (labelKey) el.setAttribute('data-menu-label', catalogText(labelKey));
            this.panel.appendChild(el);
        }
        this.controls.classList.add('controls--folded');
        this.isFolded = true;
    }

    /* there is nothing */
    _unfold() {
        this.close();
        for (const id of foldOrder()) {
            const el = document.getElementById(id);
            if (el) this.controls.insertBefore(el, this.toggle);
        }
        this.controls.classList.remove('controls--folded');
        this.isFolded = false;
    }

    open() {
        if (!this.panel) return;
        this.panel.hidden = false;
        this.panel.classList.add('header-menu-panel--open');
        this.toggle.setAttribute('aria-expanded', 'true');
        this.isOpen = true;
    }

    close() {
        if (!this.panel) return;
        this.panel.classList.remove('header-menu-panel--open');
        this.panel.hidden = true;
        this.toggle.setAttribute('aria-expanded', 'false');
        this.isOpen = false;
    }
}

window.HeaderMenu = new HeaderMenu();
window.HeaderMenuConstants = {
    ROW_LABEL_KEYS: HEADER_MENU_ROW_LABEL_KEYS,
    CONTROL_IDS: HEADER_MENU_CONTROL_IDS,
    TOOL_CONTROL_IDS: HEADER_TOOL_CONTROL_IDS,
    SESSION_CONTROL_IDS: HEADER_SESSION_CONTROL_IDS
};

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => window.HeaderMenu.init());
} else {
    window.HeaderMenu.init();
}

console.log('[HeaderMenu Module] Exported as window.HeaderMenu');
})();
