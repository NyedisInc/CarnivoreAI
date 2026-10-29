
export interface Box {
    left: number;
    top: number;
    width: number;
    height: number;
}

export interface PageSize {
    width: number;
    height: number;
}

export interface ModifierKeys {
    altKey: boolean;
    ctrlKey: boolean;
    metaKey: boolean;
    shiftKey: boolean;
}

export interface KeyMessage {
    type: 'key';
    event: 'down' | 'up';
    key: string;
    code: string;
    keyCode: number;
    text: string;
    modifiers: number;
}

export const VIEWPORT_BOUNDS = { minW: 200, maxW: 3840, minH: 200, maxH: 2160, minDpr: 0.5, maxDpr: 2 } as const;

const KEY_FIELD_MAX = 32;

export function drawnRect(box: Box, page: PageSize): Box {
    if (box.width <= 0 || box.height <= 0 || page.width <= 0 || page.height <= 0) {
        return { left: box.left, top: box.top, width: 0, height: 0 };
    }
    const scale = Math.min(box.width / page.width, box.height / page.height);
    const width = page.width * scale;
    const height = page.height * scale;
    return { left: box.left + (box.width - width) / 2, top: box.top + (box.height - height) / 2, width, height };
}

export function pageScale(box: Box, page: PageSize): number {
    const drawn = drawnRect(box, page);
    return drawn.width > 0 ? page.width / drawn.width : 1;
}

export function toPagePoint(clientX: number, clientY: number, box: Box, page: PageSize): { x: number; y: number } {
    const drawn = drawnRect(box, page);
    if (drawn.width <= 0 || drawn.height <= 0) return { x: 0, y: 0 };
    const x = ((clientX - drawn.left) / drawn.width) * page.width;
    const y = ((clientY - drawn.top) / drawn.height) * page.height;
    return {
        x: Math.round(Math.min(Math.max(x, 0), page.width - 1)),
        y: Math.round(Math.min(Math.max(y, 0), page.height - 1)),
    };
}

export function modifiersOf(e: ModifierKeys): number {
    return (e.altKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.metaKey ? 4 : 0) | (e.shiftKey ? 8 : 0);
}

export function mouseButton(button: number): 'left' | 'middle' | 'right' | 'none' {
    if (button === 0) return 'left';
    if (button === 1) return 'middle';
    if (button === 2) return 'right';
    return 'none';
}

export function wheelDelta(
    e: { deltaX: number; deltaY: number; deltaMode: number },
    pageHeight: number,
): { deltaX: number; deltaY: number } {
    const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? pageHeight : 1;
    return { deltaX: Math.round(e.deltaX * unit), deltaY: Math.round(e.deltaY * unit) };
}

export function keyMessage(
    e: ModifierKeys & { key: string; code: string; keyCode: number },
    event: 'down' | 'up',
): KeyMessage {
    const shortcut = e.ctrlKey || e.metaKey;
    let text = '';
    if (event === 'down' && !shortcut) {
        if (e.key === 'Enter') text = '\r';
        else if ([...e.key].length === 1) text = e.key;
    }
    return {
        type: 'key',
        event,
        key: e.key.slice(0, KEY_FIELD_MAX),
        code: e.code.slice(0, KEY_FIELD_MAX),
        keyCode: Math.min(Math.max(Math.trunc(e.keyCode) || 0, 0), 255),
        text,
        modifiers: modifiersOf(e),
    };
}

export function viewportFor(width: number, height: number, dpr: number): { width: number; height: number; dpr: number } {
    const b = VIEWPORT_BOUNDS;
    const clamp = (v: number, lo: number, hi: number): number => Math.min(Math.max(v, lo), hi);
    return {
        width: Math.round(clamp(width, b.minW, b.maxW)),
        height: Math.round(clamp(height, b.minH, b.maxH)),
        dpr: clamp(Number.isFinite(dpr) && dpr > 0 ? dpr : 1, b.minDpr, b.maxDpr),
    };
}
