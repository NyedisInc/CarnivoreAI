
import { remoteMenuOpen } from './remote-menu';

const OPEN_TIMEOUT_MS = 3000;

export interface MenuOpening {
  ok: boolean;
  reason: string;
}

export async function openWidgetMenu(cell: Element | null): Promise<MenuOpening> {
  if (!cell) return { ok: false, reason: 'no widget is drawn, so there is no menu to open' };
  const button = cell.querySelector<HTMLElement>('button[aria-haspopup="menu"]');
  if (!button) return { ok: false, reason: 'this host draws no menu button for the widget' };
  button.click();
  const started = performance.now();
  while (performance.now() - started < OPEN_TIMEOUT_MS) {
    if (document.querySelector('[role="menu"]:popover-open') || remoteMenuOpen()) return { ok: true, reason: '' };
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  return { ok: false, reason: 'the menu button was pressed but no menu opened' };
}

export function openMenuPanel(): Element | null {
  return document.querySelector('[role="menu"]:popover-open');
}
