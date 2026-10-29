import { hasDesktopCapability, desktopBridge } from '../settings-page/desktop-bridge';
import { removeTab } from '../../opscenter/engine/tab-groups.svelte';
import { terminalLayout } from '../../opscenter/engine/layout.svelte';
import { PRIMARY_SLOT } from '../../opscenter/engine/model';

export function canPopOutSession(rowId: number | null | undefined): boolean {
  return typeof rowId === 'number' && Number.isFinite(rowId) && rowId >= 0 && hasDesktopCapability('openSessionWindow');
}

export async function popOutSession(rowId: number, slot: string): Promise<void> {
  const open = desktopBridge()?.openSessionWindow;
  if (!open) return;
  let opened = false;
  try {
    opened = !!(await open(String(rowId)));
  } catch {
    opened = false;
  }
  if (!opened) return;
  if (slot === PRIMARY_SLOT) {
    (globalThis as { App?: { goHome?: () => void } }).App?.goHome?.();
    return;
  }
  removeTab(terminalLayout, slot);
}
