
const HEADER_BRAND_ICON_URL = '/static/img/carnivore/carnivore-wordmark.png';
const HEADER_BRAND_ICON_URL_2X = '/static/img/carnivore/carnivore-wordmark@2x.png';
const HEADER_BRAND_EMOJI = '☁️';

function _onHeaderIconLoadError(_event) {
    console.error('Header brand icon failed to load: ' + HEADER_BRAND_ICON_URL);
    var iconEl = document.getElementById('header-icon');
    if (iconEl) {
        iconEl.innerHTML = '';
        iconEl.textContent = HEADER_BRAND_EMOJI;
        iconEl.dataset.iconFallback = 'emoji';
    }
}

function setHeaderIdentity(opts) {
    var iconEl = document.getElementById('header-icon');
    var textEl = document.getElementById('header-title-text');
    var headerRowEl = document.querySelector('.header-row');
    var subheaderEl = document.getElementById('home-subheader');
    if (headerRowEl && subheaderEl) {
        if (opts.subheader) {
            headerRowEl.classList.add('header--home');
            document.body.classList.add('home-header-active');
            subheaderEl.textContent = opts.subheader;
            subheaderEl.hidden = false;
        } else {
            headerRowEl.classList.remove('header--home');
            document.body.classList.remove('home-header-active');
            subheaderEl.hidden = true;
        }
    }
    if (iconEl) {
        var existingImg = iconEl.querySelector('img[data-brand-icon]');
        if (!existingImg) {
            iconEl.innerHTML = '<img data-brand-icon src="' + HEADER_BRAND_ICON_URL +
                '" srcset="' + HEADER_BRAND_ICON_URL_2X + ' 2x" alt="Carnivore" />';
            delete iconEl.dataset.iconFallback;
            existingImg = iconEl.querySelector('img');
        }
        if (existingImg && !existingImg.dataset.errorWired) {
            existingImg.dataset.errorWired = 'true';
            existingImg.addEventListener('error', _onHeaderIconLoadError, { once: true });
        }
    }
    if (textEl) {
        var fullTitle = opts.title == null ? 'Carnivore' : opts.title;
        if (window.HeaderTitleFit) {
            window.HeaderTitleFit.setTitle(fullTitle);
        } else {
            textEl.textContent = fullTitle;
        }
    }
    if (opts.icon === 'cloude') {
        _wireHeaderTitleRename();
    } else {
        _unwireHeaderTitleRename();
    }
}

function _wireHeaderTitleRename() {
    const titleEl = document.getElementById('header-title-text');
    if (!titleEl) return;
    titleEl.classList.remove('header-title-editable');
    titleEl.removeAttribute('title');
    let pencilEl = document.getElementById('header-rename-pencil');
    if (!pencilEl) {
        pencilEl = document.createElement('span');
        pencilEl.id = 'header-rename-pencil';
        pencilEl.className = 'header-rename-pencil';
        pencilEl.setAttribute('role', 'button');
        pencilEl.setAttribute('tabindex', '0');
        pencilEl.setAttribute('aria-label', window.CloudeI18n.t('session.rename.short'));
        pencilEl.textContent = '✎';
        titleEl.insertAdjacentElement('afterend', pencilEl);
    }
    const trigger = (e) => {
        e.stopPropagation();
        if (window.TerminalController && typeof window.TerminalController._enterHeaderRename === 'function') {
            window.TerminalController._enterHeaderRename();
        }
    };
    pencilEl.onclick = trigger;
    pencilEl.onkeydown = (e) => {
        if (e.key === 'Enter' || e.key === ' ') trigger(e);
    };
}

function _unwireHeaderTitleRename() {
    const titleEl = document.getElementById('header-title-text');
    if (titleEl) {
        titleEl.classList.remove('header-title-editable');
        titleEl.removeAttribute('title');
        titleEl.onclick = null;
    }
    const pencilEl = document.getElementById('header-rename-pencil');
    if (pencilEl && pencilEl.parentNode) pencilEl.parentNode.removeChild(pencilEl);
}

/* the same words */
function sessionDisplayName(sessionLike) {
    if (!sessionLike || typeof sessionLike !== 'object') return null;
    var row = {
        label: sessionLike.label,
        name: sessionLike.name || sessionLike.tmux_session || null,
    };
    if (window.SessionLabel) return window.SessionLabel.resolve(row);
    if (typeof row.label === 'string' && row.label.trim()) return row.label.trim();
    return row.name || null;
}
window.sessionDisplayName = sessionDisplayName;

function setPageTitle(session) {
    var brand = 'Carnivore';
    var name = typeof session === 'string' ? session : sessionDisplayName(session);
    if (name && String(name).trim()) {
        document.title = String(name).trim() + ' - ' + brand;
    } else {
        document.title = brand;
    }
}
window.setPageTitle = setPageTitle; window.setHeaderIdentity = setHeaderIdentity;

class AppController {
    constructor() {
        this.currentScreen = null;
        this.logoutBtn = null;
        this.settingsBtn = null;
        this.configEditorBtn = null;
        this.sessionNotesBtn = null;
    }

    _placeStatusLight(screen) {
        const el = document.getElementById('statusText');
        if (!el) return;
        if (el.parentNode) el.parentNode.removeChild(el);
    }

    async init() {
        console.log('App: Initializing');

        this.logoutBtn = document.getElementById('logoutBtn');
        this.settingsBtn = document.getElementById('settingsBtn');
        this.configEditorBtn = document.getElementById('configEditorBtn');
        this.sessionNotesBtn = document.getElementById('sessionNotesBtn');

        if (window.Themes && typeof window.Themes.applyStoredThemeIdSync === 'function') {
            try { window.Themes.applyStoredThemeIdSync(); } catch (_) {  }
        }


        this.setupEventListeners();

        window.Auth.init();

        if (window.Auth.isAuthenticated()) {
            console.log('App: User has token, verifying...');
            const isValid = await window.Auth.verifyToken();
            if (isValid) {
                await this._initAuthenticatedState();
                if (window.Router && window.Router.bootScreen) window.Router.bootScreen(this); else this.showLaunchpad();
            } else {
                console.log('App: Token invalid, showing auth');
                this.showAuth();
            }
        } else {
            console.log('App: No token, showing auth');
            this.showAuth();
        }
    }

    async _initAuthenticatedState() {
        if (globalThis.AppEvents) {
            try { globalThis.AppEvents.start(); } catch (err) {
                console.warn('App: event channel failed to start', err);
            }
        }
        if (globalThis.SessionRestoreOffer) {
            try { globalThis.SessionRestoreOffer.start(window.API); } catch (err) {
                console.warn('App: restore offer check failed to start', err);
            }
        }
        await this._hydratePreferences();
        await this._initThemes();
    }

    async _hydratePreferences() {
        if (!globalThis.Preferences) return;
        const status = await globalThis.Preferences.hydrate(window.API);
        if (status !== globalThis.Preferences.HYDRATED) {
            console.warn('App: preferences unavailable - running on local defaults');
        }
        if (window.MotionSetting) window.MotionSetting.apply();
    }

    async _initThemes() {
        if (!window.Themes) return;
        try {
            await window.Themes.init();
        } catch (e) {
            console.warn('App: Themes.init failed - registry will use fallback', e);
        }
    }

    _openSettingsIfDeepLinked() {
        if (window.location.hash !== '#settings') return;
        if (window.CloudeWeb && typeof window.CloudeWeb.openSettingsScreen === 'function') {
            window.CloudeWeb.openSettingsScreen();
        }
    }

    setupEventListeners() {
        window.addEventListener('authenticated', () => {
            console.log('App: User authenticated');
            this._initAuthenticatedState().finally(() => (window.Router && window.Router.bootScreen ? window.Router.bootScreen(this) : this.showLaunchpad()));
        });

        window.addEventListener('auth-required', () => {
            console.log('App: Auth required');
            this.showAuth();
        });

        window.addEventListener('logged-out', () => {
            console.log('App: User logged out');
            this.showAuth();
        });

        window.addEventListener('session-created', (e) => {
            console.log('App: Session created', e.detail);
            if (window.NavigationGeneration && e.detail.nav != null
                && !window.NavigationGeneration.keep(e.detail.nav, 'session create')) return;
            this.showTerminal(e.detail.session, {
                initialScrollbackB64: e.detail.initialScrollbackB64,
                fifoStartOffset: e.detail.fifoStartOffset,
            });
        });

        window.addEventListener('session-destroyed', () => {
            console.log('App: Session destroyed');
            this.showLaunchpad();
        });

        const appTitle = document.getElementById('appTitle');
        window.DismissGuard.onContainerActivate(appTitle, () => {
            if (this.currentScreen === 'terminal') {
                console.log('App: Title clicked, returning to launcher');
                this.goHome();
                return;
            }
        });

        if (this.logoutBtn) {
            this.logoutBtn.addEventListener('click', () => this.logout());
        }

        var headerIconEl = document.getElementById('header-icon');
        if (headerIconEl) {
            headerIconEl.addEventListener('click', () => this.showLaunchpad());
        }

        if (this.settingsBtn) {
            this.settingsBtn.addEventListener('click', () => {
                if (window.CloudeWeb && typeof window.CloudeWeb.openSettingsScreen === 'function') {
                    window.CloudeWeb.openSettingsScreen();
                }
            });
        }

        if (this.configEditorBtn) {
            this.configEditorBtn.addEventListener('click', () => {
                if (window.ConfigEditorLoader && typeof window.ConfigEditorLoader.toggleWhenReady === 'function') {
                    window.ConfigEditorLoader.toggleWhenReady(this.configEditorBtn);
                } else {
                    console.error('App: ConfigEditorLoader is not loaded - ' +
                        'the config editor family cannot be fetched.');
                }
            });
        }
    }

    /* on the terminal screen the current session */
    goHome() {
        if (this.currentScreen !== 'terminal') return;
        console.log('App: Home clicked, returning to launcher (session stays attached)');
        if (window.TerminalController && typeof window.TerminalController.pauseForHome === 'function') {
            window.TerminalController.pauseForHome();
        }
        this.showLaunchpad();
    }

    showAuth() {
        console.log('App: Showing auth screen');
        if (this.currentScreen && window.NavigationGeneration) {
            window.NavigationGeneration.begin('auth');
        }
        this.hideAllScreens();
        document.getElementById('auth-screen').classList.add('active');
        window.Auth.resolveEntry();
        window.ScreenChrome.apply('auth');
        if (window.SessionSidebar) window.SessionSidebar.hide();
        this.currentScreen = 'auth';
        this._placeStatusLight('auth');
        window.ThemeNavigation.applyForGlobal();
        setHeaderIdentity({ icon: 'brand', title: '' });
        setPageTitle(null);
        if (window.Router && typeof window.Router.resetToLauncher === 'function') {
            window.Router.resetToLauncher();
        }
    }

    showLaunchpad() {
        console.log('App: Showing launchpad screen');
        var navGenBeforeEntry = window.NavigationGeneration
            ? window.NavigationGeneration.current() : null;
        if (this.currentScreen && window.NavigationGeneration) {
            window.NavigationGeneration.begin('launchpad');
        }
        if (window.Router && typeof window.Router.clearError === 'function') {
            window.Router.clearError(navGenBeforeEntry);
        }
        this.hideAllScreens();
        document.getElementById('launchpad-screen').classList.add('active');
        if (window.LaunchpadHost) window.LaunchpadHost.enter();
        window.AppScreenEntry.revealAuthedChrome(this);
        if (window.SessionSidebar) {
            window.SessionSidebar.setActiveSession(null, null);
            window.SessionSidebar.show();
        }
        this.currentScreen = 'launchpad';
        window.ScreenChrome.apply('launchpad');
        window.ThemeNavigation.applyForGlobal();
        setHeaderIdentity({
            icon: 'brand',
            title: 'Launcher',
            subheader: 'select a project or create a new project'
        });
        setPageTitle(null);
        this._openSettingsIfDeepLinked();
        if (window.AppBootComplete) window.AppBootComplete.announce();
        if (window.Router && typeof window.Router.resetToLauncher === 'function') {
            window.Router.resetToLauncher();
        }

        // on the terminal screen

        if (!window.Launchpad.launchpadScreen) {
            window.Launchpad.init();
        }

        this._placeStatusLight('launchpad');

        window.Launchpad.loadProjects();
    }

    async showTerminal(session, opts = {}) {
        console.log('App: Showing terminal screen');
        if (window.LaunchpadHost) window.LaunchpadHost.exit();
        await window.AppScreenEntry.enterTerminal(this, session, session,
            'terminal connect', function (nav) {
                window.TerminalController.connectToSession(session, opts, { nav: nav });
            });
    }

    focusTerminal() {
        setTimeout(() => {
            const input = document.querySelector('.xterm-helper-textarea');
            if (input) input.focus();
        }, 100);
    }

    async returnToExistingTerminal(session) {
        console.log('App: Returning to existing terminal', session && session.id);
        var inner = (session && session.session) ? session.session : session;
        await window.AppScreenEntry.enterTerminal(this, session, inner,
            'terminal rejoin', function (nav) {
                window.TerminalController.reconnectToExistingSession(session, { nav: nav });
            });
    }

    hideAllScreens() {
        document.querySelectorAll('.screen').forEach(screen => {
            screen.classList.remove('active');
        });
        ['closeCatalogScreen', 'closeLedgerScreen', 'closeBrowserScreen', 'closeThemesScreen', 'closeWarezScreen', 'closeEliteScreen', 'closePluginsScreen', 'closeSkillsManagerScreen', 'closeWidgetsScreen', 'closeWrappersScreen', 'closeHostsScreen', 'closeBlueprintsScreen', 'closeSettingsScreen', 'closeAccountScreen', 'closeSessionsScreen', 'closeDocsScreen', 'closeChangelogScreen', 'closeLogsScreen', 'closeWarroomScreen', 'closeTaskManagerSettingsScreen', 'closeHuddleAgentScreen', 'closeDashboardsScreen', 'closeAutomationsScreen', 'closeModsScreen', 'closeTerminalEmpty'].forEach(name => {
            if (window.CloudeWeb && typeof window.CloudeWeb[name] === 'function') {
                window.CloudeWeb[name]();
            }
        });
    }

    async logout() {
        const confirmed = await this.showConfirmModal(
            'logout',
            window.CloudeI18n.t('account.logout.confirm.title'),
            window.CloudeI18n.t('account.logout.confirm.message'),
            undefined,
            undefined,
            'danger'
        );

        if (confirmed) {
            if (window.TerminalController.sessionActive) {
                try {
                    await window.TerminalController.destroySession(
                        null, { confirmedBy: 'App.logout' });
                } catch (error) {
                    console.error('App: Error destroying session during logout:', error);
                }
            }

            window.Auth.logout();
        }
    }

    showConfirmModal(title, message, details = null, primaryLabel = 'confirm', secondaryLabel = 'cancel', primaryVariant = 'primary', overlayClass = null) {
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = overlayClass
                ? `modal-overlay confirm-modal ${overlayClass}`
                : 'modal-overlay confirm-modal';

            const safeTitle = this._escapeHtml(title);
            const safeMessage = this._escapeHtml(message);
            const safeDetails = details ? this._escapeHtml(details) : null;

            const headerHtml = `<div class="modal-titlerow"><span class="confirm-modal__verb">${safeTitle}</span></div>`;

            overlay.innerHTML = `
                <div class="modal-content">
                    ${headerHtml}
                    <div class="modal-body">
                        <div class="modal-message">${safeMessage}</div>
                        ${safeDetails ? `<div class="modal-description">${safeDetails}</div>` : ''}
                    </div>
                    <div class="modal-footer">
                        <button class="modal-btn modal-btn-secondary" id="modal-cancel">${this._escapeHtml(secondaryLabel)}</button>
                        <button class="modal-btn modal-btn-${primaryVariant === 'danger' ? 'danger' : 'primary'}" id="modal-confirm">${this._escapeHtml(primaryLabel)}</button>
                    </div>
                </div>
            `;

            document.body.appendChild(overlay);

            const confirmBtn = overlay.querySelector('#modal-confirm');
            const cancelBtn = overlay.querySelector('#modal-cancel');

            let releaseTrap = () => {};
            let settled = false;

            const settle = (answer) => {
                if (settled) return;
                settled = true;
                if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
                releaseTrap();
                resolve(answer);
            };

            if (window.ModalStack && typeof window.ModalStack.trap === 'function') {
                releaseTrap = window.ModalStack.trap(overlay, {
                    onEscape: () => settle(false),
                });
            }

            confirmBtn.addEventListener('click', () => settle(true));

            cancelBtn.addEventListener('click', () => settle(false));

            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) settle(false);
            });

            setTimeout(() => confirmBtn.focus(), 100);
        });
    }

    _syncSessionUrl(sessionName, replace) {
        if (!sessionName || !window.Router || typeof window.Router.enterSession !== 'function') {
            return;
        }
        var slug = (window.Launchpad && typeof window.Launchpad._deriveRunningSessionDisplayName === 'function')
            ? window.Launchpad._deriveRunningSessionDisplayName(sessionName)
            : sessionName;
        window.Router.enterSession(slug, { replace: !!replace });
    }

    _escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str == null ? '' : String(str);
        return div.innerHTML;
    }
}

const App = new AppController();
window.App = App;

window.addEventListener('load', () => {
    App.init();
    if (window.Router && typeof window.Router.init === 'function') {
        window.Router.init();
    }
});
