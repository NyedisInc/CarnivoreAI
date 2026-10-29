import { describe, expect, test } from 'vitest';
import { drawnRect, keyMessage, modifiersOf, mouseButton, pageScale, toPagePoint, viewportFor, wheelDelta } from './input-map';
import { instanceName, isInstanceId, kindOf, metaFor } from '../../opscenter/engine/meta';

const NONE = { altKey: false, ctrlKey: false, metaKey: false, shiftKey: false };

describe('a scaled canvas maps to page CSS pixels', () => {
    test('a canvas drawn at half size doubles every coordinate', () => {
        const box = { left: 10, top: 20, width: 640, height: 400 };
        const page = { width: 1280, height: 800 };
        expect(toPagePoint(10, 20, box, page)).toEqual({ x: 0, y: 0 });
        expect(toPagePoint(330, 220, box, page)).toEqual({ x: 640, y: 400 });
        expect(pageScale(box, page)).toBe(2);
    });

    test('the letterbox is taken off before scaling', () => {
        const box = { left: 0, top: 0, width: 400, height: 400 };
        const page = { width: 800, height: 400 };
        expect(drawnRect(box, page)).toEqual({ left: 0, top: 100, width: 400, height: 200 });
        expect(toPagePoint(200, 200, box, page)).toEqual({ x: 400, y: 200 });
        expect(toPagePoint(100, 150, box, page)).toEqual({ x: 200, y: 100 });
    });

    test('a tall page gets bars left and right', () => {
        const box = { left: 50, top: 0, width: 400, height: 400 };
        const page = { width: 400, height: 800 };
        expect(drawnRect(box, page)).toEqual({ left: 150, top: 0, width: 200, height: 400 });
        expect(toPagePoint(250, 200, box, page)).toEqual({ x: 200, y: 400 });
    });

    test('a press on a bar clamps onto the nearest page edge', () => {
        const box = { left: 0, top: 0, width: 400, height: 400 };
        const page = { width: 800, height: 400 };
        expect(toPagePoint(200, 10, box, page)).toEqual({ x: 400, y: 0 });
        expect(toPagePoint(500, 390, box, page)).toEqual({ x: 799, y: 399 });
    });

    test('nothing drawn maps nowhere rather than dividing by zero', () => {
        expect(toPagePoint(5, 5, { left: 0, top: 0, width: 0, height: 0 }, { width: 800, height: 600 })).toEqual({ x: 0, y: 0 });
        expect(pageScale({ left: 0, top: 0, width: 0, height: 0 }, { width: 800, height: 600 })).toBe(1);
    });
});

describe('keys, buttons, wheel and the viewport', () => {
    test('modifiers are the server bitmask', () => {
        expect(modifiersOf(NONE)).toBe(0);
        expect(modifiersOf({ ...NONE, altKey: true, metaKey: true })).toBe(5);
        expect(modifiersOf({ altKey: true, ctrlKey: true, metaKey: true, shiftKey: true })).toBe(15);
    });

    test('buttons', () => {
        expect([0, 1, 2, 3].map(mouseButton)).toEqual(['left', 'middle', 'right', 'none']);
    });

    test('a printable key carries text, a shortcut and a key up do not', () => {
        expect(keyMessage({ ...NONE, key: 'a', code: 'KeyA', keyCode: 65 }, 'down')).toEqual({
            type: 'key', event: 'down', key: 'a', code: 'KeyA', keyCode: 65, text: 'a', modifiers: 0,
        });
        expect(keyMessage({ ...NONE, key: 'Enter', code: 'Enter', keyCode: 13 }, 'down').text).toBe('\r');
        expect(keyMessage({ ...NONE, key: 'ArrowLeft', code: 'ArrowLeft', keyCode: 37 }, 'down').text).toBe('');
        expect(keyMessage({ ...NONE, ctrlKey: true, key: 'a', code: 'KeyA', keyCode: 65 }, 'down').text).toBe('');
        expect(keyMessage({ ...NONE, key: 'a', code: 'KeyA', keyCode: 65 }, 'up').text).toBe('');
        expect(keyMessage({ ...NONE, key: 'x', code: 'KeyX', keyCode: 999 }, 'down').keyCode).toBe(255);
    });

    test('wheel deltas convert lines and pages to pixels', () => {
        expect(wheelDelta({ deltaX: 0, deltaY: 120, deltaMode: 0 }, 800)).toEqual({ deltaX: 0, deltaY: 120 });
        expect(wheelDelta({ deltaX: 1, deltaY: 3, deltaMode: 1 }, 800)).toEqual({ deltaX: 16, deltaY: 48 });
        expect(wheelDelta({ deltaX: 0, deltaY: 1, deltaMode: 2 }, 800).deltaY).toBe(800);
    });

    test('the viewport asked for stays inside the server bounds', () => {
        expect(viewportFor(120, 900.4, 3)).toEqual({ width: 200, height: 900, dpr: 2 });
        expect(viewportFor(5000, 5000, 0)).toEqual({ width: 3840, height: 2160, dpr: 1 });
    });
});

describe('a browser slot is an instance of its own kind', () => {
    test('kind, name and record', () => {
        expect(isInstanceId('browser:0123456789abcdef')).toBe(true);
        expect(kindOf('browser:0123456789abcdef')).toBe('browser');
        expect(kindOf('terminal:ses_1')).toBe('terminal');
        expect(kindOf('themes')).toBeNull();
        expect(instanceName('browser:0123456789abcdef')).toBe('0123456789abcdef');
        const meta = metaFor('browser:0123456789abcdef');
        expect(meta.icon).toBe('globe');
        expect(meta.titleKey).toBe('opscenter.cell.browser.title');
        expect(meta.titleName, 'a hex id is not a name anybody chose').toBeUndefined();
    });
});
