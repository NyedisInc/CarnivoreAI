import { ensurePanel, panelInstance, unmountPanel } from '../mount';
import { whenLegacyBootComplete } from '../legacy-boot';
import type { Component } from 'svelte';

export const LEDGER_SCREEN_CONTAINER = 'ledger-screen';

export const LEDGER_HASH = '#ledger';

let loadedLedgerPanel: Component<Record<string, never>, Record<string, unknown>> | null = null;
let ledgerLoadPromise: Promise<Component<Record<string, never>, Record<string, unknown>> | null> | null = null;
let pendingLedgerOpen: { account?: string } | null = null;

function ensureLedgerLoaded(): Promise<Component<Record<string, never>, Record<string, unknown>> | null> {
    if (loadedLedgerPanel) return Promise.resolve(loadedLedgerPanel);
    ledgerLoadPromise ??= import('./LedgerScreen.svelte').then((mod) => {
        loadedLedgerPanel = mod.default as unknown as Component<Record<string, never>, Record<string, unknown>>;
        return loadedLedgerPanel;
    }).catch((err) => {
        ledgerLoadPromise = null;
        console.error('ledger-host: failed to load LedgerScreen', err);
        return null;
    });
    return ledgerLoadPromise;
}

interface ScreenHandle {
    show?: (account?: string) => void;
    close?: () => void;
    isOpen?: () => boolean;
}

/* the home screen */
export function mountLedgerScreen(): Record<string, unknown> | null {
    if (!loadedLedgerPanel) {
        void ensureLedgerLoaded();
        return panelInstance(LEDGER_SCREEN_CONTAINER);
    }
    return ensurePanel(LEDGER_SCREEN_CONTAINER, loadedLedgerPanel, {});
}

export function unmountLedgerScreen(): boolean {
    pendingLedgerOpen = null;
    return unmountPanel(LEDGER_SCREEN_CONTAINER);
}

export function openLedgerScreen(account?: string): boolean {
    if (loadedLedgerPanel) {
        const handle = (mountLedgerScreen() ?? panelInstance(LEDGER_SCREEN_CONTAINER)) as ScreenHandle | null;
        if (!handle || typeof handle.show !== 'function') return false;
        handle.show(account);
        return true;
    }
    if (typeof document === 'undefined' || !document.getElementById(LEDGER_SCREEN_CONTAINER)) return false;
    const ticket = { account };
    pendingLedgerOpen = ticket;
    void ensureLedgerLoaded().then((panel) => {
        if (!panel || pendingLedgerOpen !== ticket) return;
        pendingLedgerOpen = null;
        const handle = (mountLedgerScreen() ?? panelInstance(LEDGER_SCREEN_CONTAINER)) as ScreenHandle | null;
        handle?.show?.(ticket.account);
    });
    return true;
}

export function closeLedgerScreen(): boolean {
    if (pendingLedgerOpen) {
        pendingLedgerOpen = null;
        return true;
    }
    const handle = panelInstance(LEDGER_SCREEN_CONTAINER) as ScreenHandle | null;
    if (!handle || typeof handle.close !== 'function') return false;
    handle.close();
    return true;
}

export function ledgerHashTarget(hash: string | null | undefined): string | null {
    if (typeof hash !== 'string') return null;
    const trimmed = hash.trim();
    const bare = trimmed.startsWith('#') ? trimmed.slice(1) : trimmed;
    const name = LEDGER_HASH.slice(1);
    if (bare === name) return '';
    if (!bare.startsWith(`${name}/`) || bare.length === name.length + 1) return null;
    try {
        return decodeURIComponent(bare.slice(name.length + 1));
    } catch {
        return null;
    }
}

export function isLedgerHash(hash: string | null | undefined): boolean {
    return ledgerHashTarget(hash) !== null;
}

export function ledgerAccountHash(id: string): string {
    return `${LEDGER_HASH}/${encodeURIComponent(id)}`;
}

export function wireLedgerDeepLink(
    target: Window | null = typeof window !== 'undefined' ? window : null,
): () => void {
    if (!target) return () => {};
    const apply = (): void => {
        const account = ledgerHashTarget(target.location?.hash);
        if (account === null) closeLedgerScreen();
        else openLedgerScreen(account || undefined);
    };
    target.addEventListener('hashchange', apply);
    const stopWaiting = whenLegacyBootComplete(target, apply);
    return () => {
        stopWaiting();
        target.removeEventListener('hashchange', apply);
    };
}
