/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as Store from '../drawer/store';
import { isDragging, onRowPointerDown, slop, tookClick } from './row-drag';

type Win = Record<string, unknown>;
const win = globalThis as unknown as Win;

let list: HTMLElement;
let setDragging: ReturnType<typeof vi.fn>;

function box(el: Element, top: number, height: number): void {
    el.getBoundingClientRect = () => ({ top, bottom: top + height, left: 0, right: 300, width: 300, height, x: 0, y: top, toJSON() {} });
}

function drawBands(bandKey = 'p:1'): void {
    list.innerHTML = '';
    let y = 0;
    for (const [key, names] of [['pinned', ['a']], [bandKey, ['a', 'b', 'c']]] as const) {
        const group = document.createElement('div');
        group.className = 'session-sidebar-group';
        group.dataset.group = key;
        box(group, y, names.length * 20);
        for (const name of names) {
            const row = document.createElement('div');
            row.className = 'session-sidebar-row';
            row.dataset.name = name;
            row.dataset.band = key;
            row.innerHTML = '<span data-grip-session="x" class="mark"></span><button class="pin">p</button><button class="kebab">k</button>';
            box(row, y, 20);
            y += 20;
            group.append(row);
        }
        list.append(group);
    }
}

function pointer(type: string, init: { x?: number; y?: number; pointerType?: string; button?: number } = {}): MouseEvent {
    const e = new MouseEvent(type, { clientX: init.x ?? 100, clientY: init.y ?? 0, button: init.button ?? 0, bubbles: true, cancelable: true });
    Object.assign(e, { pointerId: 1, pointerType: init.pointerType ?? 'mouse' });
    return e;
}

function press(target: Element, init: Parameters<typeof pointer>[1] = {}): void {
    const e = pointer('pointerdown', init);
    Object.defineProperty(e, 'target', { value: target });
    onRowPointerDown(e as PointerEvent);
}

function move(y: number, x = 100, pointerType = 'mouse'): void { document.dispatchEvent(pointer('pointermove', { y, x, pointerType })); }
function release(y: number): void { document.dispatchEvent(pointer('pointerup', { y })); }

function rowIn(name: string, band: string): HTMLElement {
    return list.querySelector<HTMLElement>(`.session-sidebar-row[data-band="${band}"][data-name="${name}"]`)!;
}

beforeEach(() => {
    localStorage.clear();
    Store.load();
    list = document.createElement('div');
    document.body.append(list);
    setDragging = vi.fn();
    win.SessionSidebar = { listEl: list, setDragging, repaint: () => {} };
    win.CloudeWeb = undefined;
    drawBands();
});

afterEach(() => {
    release(0);
    tookClick();
    list.remove();
    delete win.SessionSidebar;
    delete win.CloudeWeb;
});

describe('who may start a drag', () => {
    it('a mouse press anywhere on the row arms a drag past the slop', () => {
        press(rowIn('b', 'p:1'), { y: 30 });
        move(30 + slop('mouse') + 1);
        expect(isDragging()).toBe(true);
    });

    it('a press on the PIN or the KEBAB arms nothing', () => {
        for (const sel of ['.pin', '.kebab']) {
            press(rowIn('b', 'p:1').querySelector(sel)!, { y: 30 });
            move(70);
            expect(isDragging(), sel).toBe(false);
        }
    });

    it('a RIGHT click arms nothing: that gesture opens the row menu', () => {
        press(rowIn('b', 'p:1'), { y: 30, button: 2 });
        move(70);
        expect(isDragging()).toBe(false);
    });

    it('a TOUCH away from the provider mark arms nothing, so the list scrolls', () => {
        press(rowIn('b', 'p:1'), { y: 30, pointerType: 'touch' });
        move(70, 100, 'touch');
        expect(isDragging()).toBe(false);
    });

    it('a TOUCH on the provider mark DOES arm a drag: it is the handle', () => {
        press(rowIn('b', 'p:1').querySelector('.mark')!, { y: 30, pointerType: 'touch' });
        move(70, 100, 'touch');
        expect(isDragging()).toBe(true);
    });

    it('a Layouts-band row is refused: the Layouts section owns its own reorder', () => {
        rowIn('b', 'p:1').dataset.band = 'layouts';
        press(rowIn('b', 'layouts'), { y: 30 });
        move(70);
        expect(isDragging()).toBe(false);
    });
});

describe('the touch threshold', () => {
    it('is larger than a mouse one, clears the 10px long-press scroll, and stays reachable', () => {
        expect(slop('touch')).toBeGreaterThan(slop('mouse'));
        expect(slop('touch')).toBeGreaterThan(10);
        expect(slop('touch')).toBeLessThan(40);
    });

    it('a TAP on the provider mark with finger jitter still reaches the click', () => {
        press(rowIn('b', 'p:1').querySelector('.mark')!, { y: 30, pointerType: 'touch' });
        move(36, 100, 'touch');
        release(36);
        expect(isDragging()).toBe(false);
        expect(tookClick()).toBe(false);
    });

    it('a real touch DRAG on the provider mark still works and claims its click', () => {
        press(rowIn('b', 'p:1').querySelector('.mark')!, { y: 30, pointerType: 'touch' });
        move(70, 100, 'touch');
        expect(isDragging()).toBe(true);
        release(70);
        expect(tookClick()).toBe(true);
    });

    it('the gesture keeps the threshold it started with', () => {
        press(rowIn('b', 'p:1').querySelector('.mark')!, { y: 30, pointerType: 'touch' });
        move(36, 100, 'mouse');
        expect(isDragging()).toBe(false);
    });
});

describe('who owns the click that ends it', () => {
    it('a press that never travels does NOT claim the click', () => {
        press(rowIn('b', 'p:1'), { y: 30 });
        move(32);
        release(32);
        expect(tookClick()).toBe(false);
    });

    it('a press that travels DOES claim the click, exactly once', () => {
        press(rowIn('b', 'p:1'), { y: 30 });
        move(70);
        release(70);
        expect(tookClick()).toBe(true);
        expect(tookClick()).toBe(false);
    });

    it('a new press clears a claim nothing consumed', () => {
        press(rowIn('b', 'p:1'), { y: 30 });
        move(70);
        release(70);
        press(rowIn('b', 'p:1'), { y: 30 });
        expect(tookClick()).toBe(false);
    });
});

describe('the handoff to the terminal page\'s tab strips (issue #455)', () => {
    function offer(taken: boolean): ReturnType<typeof vi.fn> {
        const begin = vi.fn(() => taken);
        list.getBoundingClientRect = () => ({ left: 0, right: 300, top: 0, bottom: 400, width: 300, height: 400, x: 0, y: 0, toJSON() {} });
        win.CloudeWeb = { tabDrag: { begin } };
        return begin;
    }

    it('a drag that leaves the list sideways is handed over, and claims the click', () => {
        const begin = offer(true);
        press(rowIn('b', 'p:1'), { y: 30, x: 100 });
        move(30, 140);
        expect(begin).toHaveBeenCalledTimes(1);
        expect(begin.mock.calls[0]![0]).toMatchObject({ name: 'b' });
        expect(isDragging()).toBe(false);
        move(300, 600);
        expect(begin).toHaveBeenCalledTimes(1);
        expect(tookClick()).toBe(true);
    });

    it('a vertical drag stays the drawer\'s own reorder', () => {
        const begin = offer(true);
        press(rowIn('b', 'p:1'), { y: 30, x: 100 });
        move(70, 110);
        expect(begin).not.toHaveBeenCalled();
        expect(isDragging()).toBe(true);
    });

    it('a refused handoff leaves the drawer drag alone', () => {
        const begin = offer(false);
        press(rowIn('b', 'p:1'), { y: 30, x: 100 });
        move(30, 400);
        expect(begin).toHaveBeenCalledTimes(1);
        move(70, 400);
        expect(isDragging()).toBe(true);
    });

    it('a finger never hands a drag to the tab strips', () => {
        const begin = offer(true);
        press(rowIn('b', 'p:1').querySelector('.mark')!, { y: 30, x: 100, pointerType: 'touch' });
        move(30, 400, 'touch');
        expect(begin).not.toHaveBeenCalled();
    });

    it('a plain click never offers anything', () => {
        const begin = offer(true);
        press(rowIn('b', 'p:1'), { y: 30, x: 100 });
        move(31, 101);
        release(31);
        expect(begin).not.toHaveBeenCalled();
    });
});

describe('a drag inside a band reorders that band and nothing else', () => {
    it.each(['p:1', 'g:x', 'rogue'])('band %s', (band) => {
        Store.save(['a'], ['a', 'b', 'c'], []);
        drawBands(band);
        press(rowIn('a', band), { y: 30 });
        move(75);
        release(75);
        const env = JSON.parse(localStorage.getItem(Store.STORAGE_KEY)!);
        expect(env.bands[band]).toEqual(['b', 'c', 'a']);
        expect(env.pinned).toEqual(['a']);
        expect(env.order).toEqual(['a', 'b', 'c']);
    });

    it('the same drag over ANOTHER project is refused and writes nothing', () => {
        Store.save(['a'], ['a', 'b', 'c'], []);
        const before = localStorage.getItem(Store.STORAGE_KEY);
        const other = document.createElement('div');
        other.className = 'session-sidebar-group';
        other.dataset.group = 'p:2';
        box(other, 80, 120);
        list.append(other);
        press(rowIn('a', 'p:1'), { y: 30 });
        move(150);
        release(150);
        expect(localStorage.getItem(Store.STORAGE_KEY)).toBe(before);
    });
});
