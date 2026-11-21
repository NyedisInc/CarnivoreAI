
export interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export function toFramePoint(key: Rect, frame: Rect, scale: number = 1): { x: number; y: number } {
  const clamp = (value: number, max: number): number => Math.min(Math.max(value, 0), Math.max(max - 1, 0));
  return { x: clamp((key.left + key.width / 2 - frame.left) / scale, frame.width / scale), y: clamp((key.top + key.height / 2 - frame.top) / scale, frame.height / scale) };
}

export interface KeyMenuBridge {
  request(key: Rect): void;
  subscribe(handler: (key: Rect) => void): () => void;
}

export function createKeyMenuBridge(): KeyMenuBridge {
  const handlers = new Set<(key: Rect) => void>();
  return {
    request: (key) => handlers.forEach((handler) => handler(key)),
    subscribe: (handler) => {
      handlers.add(handler);
      return () => handlers.delete(handler);
    },
  };
}

export const KEY_MENU_CONTEXT = Symbol('dwl-key-menu');
