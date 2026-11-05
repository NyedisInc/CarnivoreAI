/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ANCHOR_GAP_PX, createAnchoredPopup } from './anchored-popup';

function anchorAt(bottom: number): HTMLButtonElement {
    const el = document.createElement('button');
    el.getBoundingClientRect = () => ({ left: 20, bottom, top: bottom - 10, right: 40, width: 20, height: 10, x: 20, y: bottom - 10, toJSON: () => ({}) });
    document.body.appendChild(el);
    return el;
}

afterEach(() => { document.body.replaceChildren(); });

describe('createAnchoredPopup', () => {
    it('places the popup under the anchor and mounts into it', () => {
        const popup = createAnchoredPopup({ onClose: vi.fn() });
        const mount = vi.fn();
        const el = document.createElement('div');
        popup.open(el, anchorAt(100), mount);
        expect(el.style.top).toBe(`${100 + ANCHOR_GAP_PX}px`);
        expect(popup.element).toBe(el);
        expect(mount).toHaveBeenCalledTimes(1);
    });

    it('Escape closes it, unmounts first and returns focus to the anchor', () => {
        const onClose = vi.fn();
        const popup = createAnchoredPopup({ onClose });
        const anchor = anchorAt(100);
        popup.open(document.createElement('div'), anchor, () => {});
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
        expect(onClose).toHaveBeenCalledTimes(1);
        expect(popup.element).toBeNull();
        expect(document.activeElement).toBe(anchor);
    });

    it('a press outside closes it without taking focus; a press inside leaves it open', () => {
        const popup = createAnchoredPopup({ onClose: vi.fn() });
        const el = document.createElement('div');
        const inner = document.createElement('span');
        el.appendChild(inner);
        const anchor = anchorAt(100);
        popup.open(el, anchor, () => {});
        inner.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        expect(popup.element).toBe(el);
        document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        expect(popup.element).toBeNull();
        expect(document.activeElement).not.toBe(anchor);
    });

    it('slides up when it would run past the viewport bottom, unless told not to fit', () => {
        const tall = (): HTMLElement => { const el = document.createElement('div'); Object.defineProperty(el, 'offsetHeight', { value: 5000 }); return el; };
        const fits = createAnchoredPopup({ onClose: vi.fn() });
        const a = tall();
        fits.open(a, anchorAt(100), () => {});
        expect(parseInt(a.style.top, 10)).toBeLessThan(100 + ANCHOR_GAP_PX);
        const stays = createAnchoredPopup({ onClose: vi.fn(), fitVertically: false });
        const b = tall();
        stays.open(b, anchorAt(100), () => {});
        expect(b.style.top).toBe(`${100 + ANCHOR_GAP_PX}px`);
    });
});
