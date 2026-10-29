/* something else */
import { ensurePanel, panelInstance, unmountPanel } from '../mount';
import { whenLegacyBootComplete } from '../legacy-boot';
import LedgerScreen from './LedgerScreen.svelte';
import type { Component } from 'svelte';

export const LEDGER_SCREEN_CONTAINER = 'ledger-screen';

export const LEDGER_HASH = '#ledger';

const LEDGER_SCREEN_PANEL = LedgerScreen as unknown as Component<
    Record<string, never>,
    Record<string, unknown>
>;

interface ScreenHandle {
    show?: (account?: string) => void;
    close?: () => void;
    isOpen?: () => boolean;
}

export function mountLedgerScreen(): Record<string, unknown> | null {
    return ensurePanel(LEDGER_SCREEN_CONTAINER, LEDGER_SCREEN_PANEL, {});
}

export function unmountLedgerScreen(): boolean {
    return unmountPanel(LEDGER_SCREEN_CONTAINER);
}

export function openLedgerScreen(account?: string): boolean {
    const handle = (mountLedgerScreen() ?? panelInstance(LEDGER_SCREEN_CONTAINER)) as
        | ScreenHandle
        | null;
    if (!handle || typeof handle.show !== 'function') return false;
    handle.show(account);
    return true;
}

export function closeLedgerScreen(): boolean {
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
