import type { AccountIdentity } from './account-identity';

export const CHIP_SELECTOR = '[data-bar-action="account"]';

export const accountMenu: { open: boolean; anchor: HTMLElement | null } = $state({ open: false, anchor: null });

export const accountChip: { identity: AccountIdentity | null } = $state({ identity: null });

export function ownerIdentity(): AccountIdentity | null {
    return accountChip.identity;
}

function markExpanded(el: HTMLElement | null, open: boolean): void {
    el?.setAttribute('aria-expanded', open ? 'true' : 'false');
}

export function toggleAccountMenu(anchor: HTMLElement | null): void {
    if (accountMenu.open && accountMenu.anchor === anchor) {
        closeAccountMenu();
        return;
    }
    markExpanded(accountMenu.anchor, false);
    accountMenu.anchor = anchor;
    accountMenu.open = true;
    markExpanded(anchor, true);
}

export function closeAccountMenu(): void {
    accountMenu.open = false;
    markExpanded(accountMenu.anchor, false);
}

export function reanchorAccountMenu(): void {
    if (!accountMenu.open || !accountMenu.anchor || accountMenu.anchor.isConnected) return;
    if (typeof document === 'undefined') return;
    const chips = [...document.querySelectorAll<HTMLElement>(CHIP_SELECTOR)];
    const shown = chips.find((el) => el.getClientRects().length > 0) ?? chips[0] ?? null;
    if (!shown) {
        accountMenu.open = false;
        return;
    }
    accountMenu.anchor = shown;
    markExpanded(shown, true);
}
