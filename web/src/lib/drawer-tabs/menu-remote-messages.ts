import type { WireNode, WireRect } from './menu-remote';

export const MENU_SHOW = 'dwl-menu-show';
export const MENU_HIDE = 'dwl-menu-hide';
export const MENU_CHOOSE = 'dwl-menu-choose';
export const MENU_CLOSE = 'dwl-menu-close';

export interface MenuShowMessage { type: typeof MENU_SHOW; id: number; label: string; anchor: WireRect | null; nodes: WireNode[] }
export interface MenuHideMessage { type: typeof MENU_HIDE; id: number }
export interface MenuChooseMessage { type: typeof MENU_CHOOSE; id: number; path: string[] }
export interface MenuCloseMessage { type: typeof MENU_CLOSE; id: number }

export function readMenuMessage<T extends { type: string; id: number }>(data: unknown, type: T['type']): T | null {
  const found = data as Partial<T> | null;
  return found && typeof found === 'object' && found.type === type && Number.isInteger(found.id) ? (found as T) : null;
}
