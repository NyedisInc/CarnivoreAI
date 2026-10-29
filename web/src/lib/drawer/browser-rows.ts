import { t } from '../i18n/index.svelte';
import { drawerEnv } from './env';

export const BROWSER_PREFIX = 'browser:';

interface BrowserInfo { id: string; label: string; url: string; state: string; created_at: string }
interface PageInfo { id: string; title: string; section?: unknown; opened_at?: unknown }

interface BrowserBridge {
    list(): BrowserInfo[];
    pages?(): PageInfo[];
    open(id: string): unknown;
    close(id: string): Promise<unknown>;
    rename(id: string, label: string): Promise<unknown>;
    popOut?(id: string): Promise<unknown>;
}

export interface BrowserMenuCtx { name: string; label?: string; isPage?: boolean; isFile?: boolean }

interface BrowserGlobals {
    CloudeWeb?: {
        browsers?: Partial<BrowserBridge>;
        sidebarShell?: { togglePinRow?(name: string): void };
        rowMenu?: { contextFromTrigger?(trigger: Element | null): BrowserMenuCtx | null };
    };
    App?: { showConfirmModal?(...args: unknown[]): Promise<boolean> };
}

function g(): BrowserGlobals {
    return drawerEnv() as BrowserGlobals;
}

function bridge(): BrowserBridge | null {
    const b = g().CloudeWeb?.browsers;
    return b && typeof b.list === 'function' ? (b as BrowserBridge) : null;
}

export function isBrowserName(name: unknown): boolean {
    return typeof name === 'string' && name.indexOf(BROWSER_PREFIX) === 0;
}

function idOf(name: unknown): string {
    return isBrowserName(name) ? (name as string).slice(BROWSER_PREFIX.length) : '';
}

const NO_PROJECT = { last_work_at: null, project_id: null, project_name: null, working_dir: null } as const;

export function rows(): Array<Record<string, unknown>> {
    const b = bridge();
    if (!b) return [];
    const pageRows = (typeof b.pages === 'function' ? b.pages() : []).map((page): Record<string, unknown> => ({
        name: BROWSER_PREFIX + page.id,
        kind: 'browser',
        browser_id: page.id,
        page: true,
        section: typeof page.section === 'string' && page.section ? page.section : null,
        label: page.title,
        url: null,
        status: 'page',
        created_at_epoch: Number(page.opened_at) || 0,
        ...NO_PROJECT,
    }));
    return b.list().map((info): Record<string, unknown> => ({
        name: BROWSER_PREFIX + info.id,
        kind: 'browser',
        browser_id: info.id,
        label: info.label,
        url: info.url,
        status: info.state,
        created_at_epoch: Date.parse(info.created_at) / 1000 || 0,
        ...NO_PROJECT,
    })).concat(pageRows);
}

export function activate(ctrl: { _closeAfterSwitch?: () => void } | null, name: string): boolean {
    if (!isBrowserName(name)) return false;
    const b = bridge();
    if (b) b.open(idOf(name));
    if (ctrl && typeof ctrl._closeAfterSwitch === 'function') ctrl._closeAfterSwitch();
    return true;
}

export function rename(id: string, label: string): Promise<unknown> {
    const b = bridge();
    if (!b) return Promise.reject(new Error('the browser module is not loaded'));
    return b.rename(id, label);
}

function reportCloseFailure(err: unknown): void {
    const detail = err instanceof Error && err.message ? err.message : String(err);
    console.error('SessionSidebarBrowsers: close failed:', err);
    alert(t('browser.close_failed', { detail }));
}

async function close(ctx: BrowserMenuCtx): Promise<void> {
    const b = bridge();
    if (!b) return;
    if (ctx.isPage || ctx.isFile) {
        try {
            await b.close(idOf(ctx.name));
        } catch (err) {
            reportCloseFailure(err);
        }
        return;
    }
    const app = g().App;
    const ok = app && typeof app.showConfirmModal === 'function'
        ? await app.showConfirmModal(t('browser.close.confirm'), ctx.label || ctx.name, t('browser.close.detail'), t('browser.menu.close'), undefined, 'danger')
        : window.confirm(t('browser.close.confirm'));
    if (!ok) return;
    try {
        await b.close(idOf(ctx.name));
    } catch (err) {
        reportCloseFailure(err);
    }
}

export function runMenuItem(itemId: string, ctx: BrowserMenuCtx): Promise<unknown> | null {
    if (itemId === 'close') return close(ctx);
    if (itemId === 'popout') {
        const b = bridge();
        return b && typeof b.popOut === 'function' ? b.popOut(idOf(ctx.name)) : Promise.resolve();
    }
    if (itemId === 'pin') {
        const shell = g().CloudeWeb?.sidebarShell;
        if (shell && typeof shell.togglePinRow === 'function') shell.togglePinRow(ctx.name);
        return Promise.resolve();
    }
    return null;
}

export function onKeyClick(keyEl: Element): Promise<unknown> {
    const rowEl = keyEl.closest('.session-sidebar-row');
    if (!rowEl) return Promise.resolve();
    const name = rowEl.getAttribute('data-name') || '';
    if (keyEl.getAttribute('data-browser-row-action') === 'close') {
        const menu = g().CloudeWeb?.rowMenu;
        const trigger = rowEl.querySelector('[data-row-menu]');
        const ctx = (menu && typeof menu.contextFromTrigger === 'function' && menu.contextFromTrigger(trigger))
            || { name, label: '', isPage: false };
        return runMenuItem('close', ctx) || Promise.resolve();
    }
    return runMenuItem('popout', { name }) || Promise.resolve();
}
