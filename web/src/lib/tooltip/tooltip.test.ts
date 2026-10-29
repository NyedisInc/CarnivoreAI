/** @vitest-environment jsdom */
import { afterEach, beforeAll, beforeEach, describe, expect, test, vi } from 'vitest';
import { installSharedTooltip, PARK_ATTR, SHOW_DELAY_MS } from './tooltip';

function visible(): HTMLElement[] {
    return [...document.querySelectorAll<HTMLElement>('.cc-tooltip')].filter((el) => !el.hidden);
}

function over(el: Element): void {
    el.dispatchEvent(new MouseEvent('pointerover', { bubbles: true }));
}

function leavePage(): void {
    document.body.dispatchEvent(new MouseEvent('pointerout', { bubbles: true, relatedTarget: null }));
}

function stage(html: string): HTMLElement {
    const host = document.createElement('div');
    host.id = 'stage';
    host.innerHTML = html;
    document.body.appendChild(host);
    return host;
}

beforeAll(() => installSharedTooltip());

beforeEach(() => {
    vi.useFakeTimers();
});

afterEach(() => {
    leavePage();
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    document.getElementById('stage')?.remove();
});

describe('the delay', () => {
    test('nothing at 200ms, exactly one box at 700ms, reading the title', () => {
        const s = stage('<button id="pin" title="pin to top"><svg><path id="p"/></svg></button>');
        over(s.querySelector('#p')!);
        vi.advanceTimersByTime(200);
        expect(visible()).toHaveLength(0);
        vi.advanceTimersByTime(SHOW_DELAY_MS);
        expect(visible()).toHaveLength(1);
        expect(visible()[0]?.textContent).toBe('pin to top');
        expect(SHOW_DELAY_MS).toBe(750);
    });

    test('moving to a second target hides the first at once and waits again', () => {
        const s = stage('<button id="a" title="first">a</button><button id="b" data-tooltip="second">b</button>');
        over(s.querySelector('#a')!);
        vi.advanceTimersByTime(SHOW_DELAY_MS + 200);
        expect(visible().map((el) => el.textContent)).toEqual(['first']);
        over(s.querySelector('#b')!);
        expect(visible()).toHaveLength(0);
        vi.advanceTimersByTime(200);
        expect(visible()).toHaveLength(0);
        vi.advanceTimersByTime(SHOW_DELAY_MS);
        expect(visible().map((el) => el.textContent)).toEqual(['second']);
        expect(document.querySelectorAll('.cc-tooltip')).toHaveLength(1);
    });

    test('keyboard focus shows it after the same delay and blur hides it', () => {
        const s = stage('<button id="f" title="settings">s</button>');
        const btn = s.querySelector<HTMLButtonElement>('#f')!;
        btn.focus();
        vi.advanceTimersByTime(200);
        expect(visible()).toHaveLength(0);
        vi.advanceTimersByTime(SHOW_DELAY_MS);
        expect(visible()).toHaveLength(1);
        btn.blur();
        expect(visible()).toHaveLength(0);
    });
});

describe('the native tooltip never fires beside it', () => {
    test('the title, and every ancestor title, is parked while the pointer is inside and put back after', () => {
        const s = stage('<div id="row" title="the row"><button id="pin" title="pin to top">x</button></div><i id="out">o</i>');
        const row = s.querySelector('#row')!;
        const pin = s.querySelector('#pin')!;
        over(pin);
        expect(pin.hasAttribute('title')).toBe(false);
        expect(row.hasAttribute('title')).toBe(false);
        expect(pin.getAttribute(PARK_ATTR)).toBe('pin to top');
        vi.advanceTimersByTime(SHOW_DELAY_MS + 200);
        expect(visible().map((el) => el.textContent)).toEqual(['pin to top']);
        over(s.querySelector('#out')!);
        expect(pin.getAttribute('title')).toBe('pin to top');
        expect(row.getAttribute('title')).toBe('the row');
        expect(pin.hasAttribute(PARK_ATTR)).toBe(false);
        expect(visible()).toHaveLength(0);
    });

    test('a title the app rewrites while parked is parked again and the box follows it', async () => {
        const s = stage('<span id="led" title="working">*</span>');
        const led = s.querySelector('#led')!;
        over(led);
        vi.advanceTimersByTime(SHOW_DELAY_MS + 200);
        led.setAttribute('title', 'stopped - waiting on you');
        await Promise.resolve();
        expect(led.hasAttribute('title')).toBe(false);
        expect(led.getAttribute(PARK_ATTR)).toBe('stopped - waiting on you');
        expect(visible().map((el) => el.textContent)).toEqual(['stopped - waiting on you']);
    });

    test('leaving the page puts every title back', () => {
        const s = stage('<button id="x" title="close">x</button>');
        over(s.querySelector('#x')!);
        leavePage();
        expect(s.querySelector('#x')!.getAttribute('title')).toBe('close');
    });
});

describe('where there is no tooltip', () => {
    test('a control with no words (the kebab) shows nothing, even after the delay', () => {
        const s = stage('<button id="kebab" aria-label="agent actions for api">:</button>');
        over(s.querySelector('#kebab')!);
        vi.advanceTimersByTime(SHOW_DELAY_MS * 3);
        expect(visible()).toHaveLength(0);
    });

    test('an empty value on the nearest carrier means none, not the ancestor', () => {
        const s = stage('<div title="the row"><button id="b" data-tooltip="">b</button></div>');
        over(s.querySelector('#b')!);
        vi.advanceTimersByTime(SHOW_DELAY_MS * 3);
        expect(visible()).toHaveLength(0);
    });

    test('inside data-tooltip-off nothing shows, and the title is still parked', () => {
        const s = stage('<div data-tooltip-off><button id="row" title="logout">l</button></div>');
        const row = s.querySelector('#row')!;
        over(row);
        vi.advanceTimersByTime(SHOW_DELAY_MS * 3);
        expect(visible()).toHaveLength(0);
        expect(row.hasAttribute('title')).toBe(false);
        expect(row.getAttribute(PARK_ATTR)).toBe('logout');
    });

    test('a control whose popup is open shows none', () => {
        const s = stage('<button id="m" title="sections" aria-expanded="true">m</button>');
        over(s.querySelector('#m')!);
        vi.advanceTimersByTime(SHOW_DELAY_MS * 3);
        expect(visible()).toHaveLength(0);
    });

    test('a press hides it, and it stays hidden until the pointer moves to another target', () => {
        const s = stage('<button id="b" title="restart"><svg><path id="p"/></svg></button><i id="o">o</i>');
        over(s.querySelector('#b')!);
        vi.advanceTimersByTime(SHOW_DELAY_MS + 200);
        expect(visible()).toHaveLength(1);
        s.querySelector('#b')!.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }));
        expect(visible()).toHaveLength(0);
        over(s.querySelector('#p')!);
        vi.advanceTimersByTime(SHOW_DELAY_MS * 3);
        expect(visible()).toHaveLength(0);
        over(s.querySelector('#o')!);
        over(s.querySelector('#b')!);
        vi.advanceTimersByTime(SHOW_DELAY_MS + 200);
        expect(visible()).toHaveLength(1);
    });

    test('a touch never shows one', () => {
        const s = stage('<button id="t" title="pin">t</button>');
        const ev = new MouseEvent('pointerover', { bubbles: true });
        Object.defineProperty(ev, 'pointerType', { value: 'touch' });
        s.querySelector('#t')!.dispatchEvent(ev);
        vi.advanceTimersByTime(SHOW_DELAY_MS * 3);
        expect(visible()).toHaveLength(0);
    });
});

describe('accessibility', () => {
    test('the shown box is role=tooltip and named by the target, whose own describedby survives', () => {
        const s = stage('<button id="b" title="notes" aria-describedby="hint">n</button><p id="hint">h</p><i id="o">o</i>');
        const b = s.querySelector('#b')!;
        over(b);
        vi.advanceTimersByTime(SHOW_DELAY_MS + 200);
        const box = visible()[0]!;
        expect(box.getAttribute('role')).toBe('tooltip');
        expect(b.getAttribute('aria-describedby')!.split(' ')).toEqual(['hint', box.id]);
        over(s.querySelector('#o')!);
        expect(b.getAttribute('aria-describedby')).toBe('hint');
    });
});

describe('above an open menu panel (issue 2077)', () => {
    afterEach(() => {
        delete (HTMLElement.prototype as unknown as Record<string, unknown>).showPopover;
        delete (HTMLElement.prototype as unknown as Record<string, unknown>).hidePopover;
    });

    test('the bubble is a manual popover re-shown on every show, closed on hide', () => {
        const calls: string[] = [];
        Object.assign(HTMLElement.prototype, {
            showPopover() { calls.push('show'); },
            hidePopover() { calls.push('hide'); },
        });
        const s = stage('<button id="b" data-tooltip="needs a folder">b</button><button id="c" data-tooltip="other">c</button>');
        over(s.querySelector('#b')!);
        vi.advanceTimersByTime(SHOW_DELAY_MS + 200);
        const box = visible()[0]!;
        expect(box.getAttribute('popover')).toBe('manual');
        expect(calls).toEqual(['show']);
        over(s.querySelector('#c')!);
        vi.advanceTimersByTime(SHOW_DELAY_MS + 200);
        expect(calls).toEqual(['show', 'hide', 'show']);
        leavePage();
        expect(calls.at(-1)).toBe('hide');
    });
});

describe('a touch tap on a disabled menu item (issue 2077)', () => {
    test('shows the reason and the tap itself dispatches no click', () => {
        const ran = vi.fn();
        const s = stage('<div role="menu"><button role="menuitem" id="d" aria-disabled="true" data-tooltip="close the session first">restart</button></div>');
        const d = s.querySelector('#d')!;
        d.addEventListener('click', ran);
        const ev = new MouseEvent('pointerup', { bubbles: true });
        Object.defineProperty(ev, 'pointerType', { value: 'touch' });
        d.dispatchEvent(ev);
        const box = visible()[0]!;
        expect(box.textContent).toBe('close the session first');
        expect(ran).not.toHaveBeenCalled();
        expect(d.getAttribute('aria-disabled')).toBe('true');
    });
});
