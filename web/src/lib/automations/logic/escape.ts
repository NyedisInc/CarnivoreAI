/* the detail pane */
import { data } from '../page-store.svelte';

export function escapeTaken(e: Event): boolean {
  if ((e.target as Element | null)?.closest?.('input, select, textarea, [contenteditable="true"]')) return true;
  if (data.commandsOpen) return true;
  if (document.querySelector('.oc-confirm-popup')) return true;
  return [...document.querySelectorAll('[role="menu"]')].some((m) => m.getClientRects().length > 0 && (m as HTMLElement).offsetWidth > 0);
}

export function claimEscape(e: Event): void {
  e.preventDefault();
  e.stopPropagation();
}
