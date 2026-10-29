
export const KEY_MENU_MESSAGE = 'dwl-key-menu';

export interface KeyMenuMessage {
  type: typeof KEY_MENU_MESSAGE;
  x: number;
  y: number;
}

export function readKeyMenuMessage(data: unknown): KeyMenuMessage | null {
  const found = data as Partial<KeyMenuMessage> | null;
  return found && found.type === KEY_MENU_MESSAGE && Number.isFinite(found.x) && Number.isFinite(found.y) ? (found as KeyMenuMessage) : null;
}
