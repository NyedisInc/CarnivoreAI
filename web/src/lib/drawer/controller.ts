import * as Clicks from './clicks';
import { load } from './fetch';
import * as Density from './density';
import * as LeaderVisibility from './leader-visibility';
import * as EmptySections from './empty-sections.svelte';
import * as StatsVisibility from './stats-visibility.svelte';
import * as SectionVisibility from './section-visibility.svelte';
import * as ClosedVisibility from './closed-visibility.svelte';
import * as ArchivedVisibility from './archived-visibility';
import * as RowIconPrefs from './row-icon-prefs';
import type { ListingVerdict } from './listing-state';
import { repaint as paintList } from './paint';
import { onGroupToggleClick } from './chrome-clicks';
import * as Pin from './pin';
import * as Resize from './resize';
import type { ArrangedRow } from './arrangement';
import * as Store from './store';
import { drawerEnv } from './env';
import { sidebarShell } from '../sidebar-shell/shell.svelte';
import { refreshGroups } from '../sidebar-shell/interaction-globals';
import { init as initGroupKeys } from './group-actions';
import { rememberLastView, watchSessionDestroyed } from './last-view';
import { noteDrawerClosed } from '../menu-page/menu-page-origin';
import { sidebarTabs } from '../dynamic-tabs/tab-store.svelte';
import type { ListingPushGlobal } from '../listing-push/boot';

function listingPush(): ListingPushGlobal | null {
    const found = (drawerEnv() as { ListingPush?: ListingPushGlobal }).ListingPush;
    return found && typeof found.pushOrPoll === 'function' ? found : null;
}

export interface PendingSelection {
    name: string;
    nav: unknown;
}

interface ControllerGlobals {
    BrowserStorageMigrate?: { readMigrating(k: string): string | null; writeMigrating(k: string, v: string): void };
    SessionHeaderLed?: { beginRequest?(): unknown; update?(rows: unknown[], active: string | null): void };
    SessionEntryToasts?: { dismissFor?(id: string | null, name: string | null): void };
    App?: { showLaunchpad?(): void };
    CloudeWeb?: {
        layoutPage?: { isActive?(): boolean; holds?(sessionId: string, tmuxName: string): boolean };
        browsers?: { showing?(): string | null };
    };
}

function g(): ControllerGlobals {
    return drawerEnv() as ControllerGlobals;
}

export class SessionSidebarController {
    toggleBtn: HTMLElement | null = null;
    panel: HTMLElement | null = null;
    backdrop: HTMLElement | null = null;
    collapseBtn: HTMLElement | null = null;
    brandBtn: HTMLElement | null = null;
    listEl: HTMLElement | null = null;

    isOpen = false;
    _wired = false;
    _pollInterval: ReturnType<typeof setInterval> | null = null;
    _pushStop: (() => void) | null = null;
    _lastSig: string | null = null;

    _rows: ArrangedRow[] = [];
    _listing: ListingVerdict = { ok: true, reason: null, detail: null };
    _missing: string[] = [];

    _dragging = false;
    _activeSessionId: string | null = null;
    _activeTmuxName: string | null = null;
    _pendingSelection: PendingSelection | null = null;

    _transientOpen = false;

    _fetchGeneration = 0;
    _fetchPromise: Promise<void> | null = null;
    _fetchAgain = false;

    _loader: (activeTmuxName: string | null) => Promise<{ rows: unknown[]; listing: ListingVerdict }> = load;

    static get STORAGE_KEY(): string {
        return 'carnivore.session.sidebar';
    }

    static get POLL_MS(): number {
        return 5000;
    }

    static get SUPPORTS_INERT(): boolean {
        return typeof HTMLElement !== 'undefined' && 'inert' in HTMLElement.prototype;
    }

    static _readPersisted(): string | null {
        const m = g().BrowserStorageMigrate;
        const k = SessionSidebarController.STORAGE_KEY;
        return m ? m.readMigrating(k) : localStorage.getItem(k);
    }

    static _writePersisted(v: string): void {
        const m = g().BrowserStorageMigrate;
        const k = SessionSidebarController.STORAGE_KEY;
        if (m) m.writeMigrating(k, v);
        else localStorage.setItem(k, v);
    }

    private storedPreference(): string | null {
        try {
            return SessionSidebarController._readPersisted();
        } catch {
            return null;
        }
    }

    init(): void {
        if (this._wired) return;
        this.toggleBtn = document.getElementById('session-sidebar-toggle');
        this.panel = document.getElementById('session-sidebar-panel');
        this.backdrop = document.getElementById('session-sidebar-backdrop');
        this.collapseBtn = document.getElementById('session-sidebar-collapse');
        this.brandBtn = document.getElementById('session-sidebar-brand');
        this.listEl = document.getElementById('session-sidebar-list');
        if (!this.toggleBtn || !this.panel || !this.backdrop || !this.listEl) {
            console.warn('SessionSidebar: required markup missing, skipping wire');
            return;
        }
        this.toggleBtn.addEventListener('click', () => this.toggle());
        if (this.collapseBtn) this.collapseBtn.addEventListener('click', () => this.close());
        if (this.brandBtn) {
            this.brandBtn.addEventListener('click', () => {
                if (!Pin.isEffectivelyPinned()) this.close();
                const app = g().App;
                if (app && typeof app.showLaunchpad === 'function') app.showLaunchpad();
            });
        }
        this.backdrop.addEventListener('click', () => this.close());
        document.addEventListener('keydown', (e) => {
            if (e.key !== 'Escape' || !this.isOpen) return;
            if (Pin.isEffectivelyPinned()) return;
            e.preventDefault();
            this.close();
        });
        this.listEl.addEventListener('click', (e) => { void this._onRowClick(e); });
        this._wired = true;
        this._setInteractive(false);
        Store.load();
        Pin.init();
        Resize.init();
        Density.init();
        watchSessionDestroyed();
        LeaderVisibility.init();
        EmptySections.init();
        StatsVisibility.init();
        SectionVisibility.init();
        ClosedVisibility.init();
        ArchivedVisibility.init();
        RowIconPrefs.init();
        initGroupKeys();
        void refreshGroups();
        console.log('SessionSidebar: wired');
    }

    show(): void {
        this.init();
        if (!this.toggleBtn) return;
        this.toggleBtn.classList.remove('hidden');
        const opens = Pin.opensFrom(this.storedPreference());
        if (opens && !this.isOpen) this.open();
        else Pin.apply();
    }

    hide(): void {
        this.close({ persist: false });
        if (this.toggleBtn) this.toggleBtn.classList.add('hidden');
    }

    _isThisTab(name: string): boolean {
        const browser = g().CloudeWeb?.browsers?.showing?.() ?? null;
        if (browser) return name === `browser:${browser}`;
        return !this._layoutOnScreen() && name === this._activeTmuxName;
    }

    refreshSelection(): void {
        for (const row of this._rows) row.is_this_tab = this._isThisTab(row.name);
        this.repaint();
    }

    _layoutOnScreen(): boolean {
        const page = g().CloudeWeb?.layoutPage;
        return !!(page && typeof page.isActive === 'function' && page.isActive());
    }

    _layoutHolds(sessionId: string, tmuxName: string): boolean {
        if (!this._layoutOnScreen()) return false;
        const page = g().CloudeWeb?.layoutPage;
        return typeof page?.holds === 'function' ? page.holds(sessionId, tmuxName) : true;
    }

    setActiveSession(sessionId: string | null, tmuxName: string | null): void {
        g().SessionHeaderLed?.beginRequest?.();
        this._fetchGeneration = (this._fetchGeneration || 0) + 1;
        if (sessionId && this._transientOpen) this._reconcileToPreference();
        const shown = this.isOpen || (typeof document !== 'undefined'
            && !!document.body?.classList?.contains('session-sidebar-railed'));
        if (shown && this._fetchPromise) this._fetchAgain = true;
        this._activeSessionId = sessionId || null;
        this._activeTmuxName = tmuxName || null;
        if ((sessionId || tmuxName) && !this._layoutHolds(sessionId || '', tmuxName || '')) {
            rememberLastView({ kind: 'session', sessionId: sessionId || '', tmuxName: tmuxName || '' });
        }
        g().SessionEntryToasts?.dismissFor?.(this._activeSessionId, this._activeTmuxName);
        for (const row of this._rows) row.is_this_tab = this._isThisTab(row.name);
        g().SessionHeaderLed?.update?.(this._rows, this._activeTmuxName);
        if (this.isOpen) this.repaint();
    }

    activeTmuxName(): string | null {
        return this._activeTmuxName;
    }

    toggle(): void {
        if (this.isOpen) this.close();
        else this.open();
    }

    open(opts?: { persist?: boolean }): void {
        if (!this.panel) return;
        const persist = !opts || opts.persist !== false;
        this.isOpen = true;
        this._transientOpen = !persist;
        this._setInteractive(true);
        this.panel.classList.add('session-sidebar-panel--open');
        this.panel.setAttribute('aria-hidden', 'false');
        if (this.backdrop) this.backdrop.hidden = false;
        if (this.toggleBtn) this.toggleBtn.setAttribute('aria-expanded', 'true');
        if (persist) {
            try {
                SessionSidebarController._writePersisted('1');
            } catch {
            }
        }
        Density.apply();
        LeaderVisibility.apply();
        ArchivedVisibility.apply();
        Pin.apply();
        void this._fetchAndRender();
        this._startPoll();
    }

    close(opts?: { persist?: boolean }): void {
        if (!this.panel) return;
        const persist = !opts || opts.persist !== false;
        if (this.isOpen) noteDrawerClosed(sidebarTabs.active());
        this.isOpen = false;
        this._transientOpen = false;
        this.panel.classList.remove('session-sidebar-panel--open');
        this._releaseFocus();
        this._setInteractive(false);
        this.panel.setAttribute('aria-hidden', 'true');
        if (this.backdrop) this.backdrop.hidden = true;
        if (this.toggleBtn) this.toggleBtn.setAttribute('aria-expanded', 'false');
        if (persist) {
            try {
                SessionSidebarController._writePersisted('0');
            } catch {
                // the drawer closed
            }
        }
        Pin.apply();
        this._stopPoll();
    }

    _releaseFocus(): void {
        if (!this.panel) return;
        const active = document.activeElement as HTMLElement | null;
        if (!active || !this.panel.contains(active)) return;
        if (typeof active.blur === 'function') active.blur();
        if (this.toggleBtn && typeof this.toggleBtn.focus === 'function') this.toggleBtn.focus();
    }

    _setInteractive(on: boolean): void {
        if (!this.panel || !SessionSidebarController.SUPPORTS_INERT) return;
        this.panel.inert = !on;
    }

    _reconcileToPreference(): void {
        this._transientOpen = false;
        if (!Pin.opensFrom(this.storedPreference())) this.close({ persist: false });
    }

    _closeAfterSwitch(): void {
        Pin.closeAfterSwitch();
    }

    _startPoll(): void {
        if (this._pollInterval || this._pushStop) return;
        const tick = (): void => {
            if (document.hidden) return;
            this._fetchAndRender().catch((err) => {
                console.warn('SessionSidebar: poll tick failed:', err);
            });
        };
        const push = listingPush();
        if (push) {
            this._pushStop = push.pushOrPoll(tick, SessionSidebarController.POLL_MS,
                ['list', 'attachable', 'records', 'companions']);
            return;
        }
        this._pollInterval = setInterval(tick, SessionSidebarController.POLL_MS);
    }

    _stopPoll(): void {
        if (this._pushStop) {
            this._pushStop();
            this._pushStop = null;
        }
        if (this._pollInterval) {
            clearInterval(this._pollInterval);
            this._pollInterval = null;
        }
    }

    async forceRefresh(): Promise<void> {
        this._lastSig = null;
        await this._fetchAndRender();
    }

    async _fetchAndRender(): Promise<void> {
        if (sidebarShell.isDragging()) return;
        if (this._fetchPromise) {
            this._fetchAgain = true;
            return this._fetchPromise;
        }
        this._fetchPromise = (async () => {
            do {
                this._fetchAgain = false;
                await this._loadAndRender();
            } while (this._fetchAgain);
        })();
        try {
            await this._fetchPromise;
        } finally {
            this._fetchPromise = null;
        }
    }

    async _loadAndRender(): Promise<void> {
        const request = this._fetchGeneration = (this._fetchGeneration || 0) + 1;
        const result = await this._loader(this._activeTmuxName);
        if (request !== this._fetchGeneration) return;
        this._listing = result.listing;
        this._rows = result.rows as ArrangedRow[];
        for (const row of this._rows) row.is_this_tab = this._isThisTab(row.name);
        g().SessionHeaderLed?.update?.(this._rows, this._activeTmuxName);
        this.repaint();
    }

    refreshNow(): Promise<void> | undefined {
        const body = typeof document !== 'undefined' ? document.body : null;
        const railed = !!(body && body.classList && body.classList.contains('session-sidebar-railed'));
        if (!this.isOpen && !railed) return undefined;
        return this._fetchAndRender().catch((err) => {
            console.warn('SessionSidebar: event-driven refresh failed:', err);
        });
    }

    repaint(): void {
        if (!this.listEl) return;
        paintList(this);
    }

    setDragging(on: boolean): void {
        const next = !!on;
        if (next === !!this._dragging) return;
        this._dragging = next;
        this.repaint();
    }

    render(rows: ArrangedRow[]): void {
        this._rows = Array.isArray(rows) ? rows : [];
        this.repaint();
    }

    async _onRowClick(e: MouseEvent): Promise<void> {
        await Clicks.onRowClick(this, e);
    }

    _onGroupToggleClick(btnEl: Element): void {
        onGroupToggleClick(this, btnEl);
    }

    async activateRow(rowEl: Element): Promise<void> {
        await Clicks.activateRow(this, rowEl);
    }

    async _onRowActionClick(btnEl: Element): Promise<void> {
        await Clicks.onRowActionClick(this, btnEl);
    }
}
