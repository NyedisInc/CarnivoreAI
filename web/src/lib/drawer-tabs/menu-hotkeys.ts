import { RAIL_HINT_ROWS } from '../../opscenter/shell/rail-hints';
import { RAIL_RUN } from '../../opscenter/shell/rail-items';
import { dismissTransientFlyout } from '../sidebar-widgets/flyout.svelte';

export const DOUBLE_DOT_MS = 600;

let lastDot = 0;

export function closeDrawerAfterSwitch(): void {
  dismissTransientFlyout();
  (globalThis as { SessionSidebarPin?: { closeAfterSwitch?: () => void } }).SessionSidebarPin?.closeAfterSwitch?.();
}

function typingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || !el.tagName) return false;
  return /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable === true;
}

export function handleMenuHotkey(event: KeyboardEvent): boolean {
  if (event.metaKey || event.ctrlKey || event.altKey || event.isComposing || typingTarget(event.target)) return false;
  let id: string | undefined;
  if (event.key === '.') {
    const now = Date.now();
    if (lastDot && now - lastDot <= DOUBLE_DOT_MS) {
      lastDot = 0;
      id = 'home';
    } else {
      lastDot = now;
      return false;
    }
  } else {
    lastDot = 0;
    id = RAIL_HINT_ROWS.find((r) => r.keys === event.key)?.id;
  }
  const run = id ? RAIL_RUN[id] : undefined;
  if (!run) return false;
  event.preventDefault();
  run();
  closeDrawerAfterSwitch();
  return true;
}
