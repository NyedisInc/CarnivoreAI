import { t } from '../i18n/index.svelte';
import { openItemMenu } from '../item-menu/open.svelte';
import { announceFailure, usableGroups } from '../sidebar-shell/interaction-globals';

let wired = false;

export function openPickerFor(anchor: Element, name: string): void {
    if (!usableGroups()) {
        announceFailure(t('sidebar.group.pick.unavailable'));
        return;
    }
    openItemMenu('grouppick', { name, anchor }, anchor);
}

export function init(): void {
    if (wired || typeof document === 'undefined') return;
    document.addEventListener('keydown', (e: KeyboardEvent) => {
        const row = e.target instanceof Element ? e.target.closest('.session-sidebar-row') : null;
        if (!(row instanceof HTMLElement) || e.key !== 'g' || e.altKey || e.metaKey || e.ctrlKey) return;
        e.preventDefault();
        openPickerFor(row, row.dataset['name'] ?? '');
    });
    wired = true;
}
