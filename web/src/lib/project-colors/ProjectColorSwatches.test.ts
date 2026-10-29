/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import ProjectColorSwatches from './ProjectColorSwatches.svelte';
import { SOFT_PROJECT_COLORS } from './palette';
import { setLocale, t } from '../i18n/index.svelte';

setLocale('en');
let handle: ReturnType<typeof mount> | null = null;
afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

function draw(value: string, onPick = vi.fn()) {
    handle = mount(ProjectColorSwatches, { target: document.body, props: { value, labelledBy: 'x', t, onPick } });
    flushSync();
    return onPick;
}

const checked = () => [...document.querySelectorAll('[aria-checked="true"]')];

test('one swatch per soft color; a pick reports its hex and the current one is selected', () => {
    const onPick = draw('#817040');
    expect(document.querySelectorAll('button[data-project-color]').length).toBe(SOFT_PROJECT_COLORS.length);
    expect(checked().map((e) => e.getAttribute('data-project-color'))).toEqual(['#817040']);
    (document.querySelector('[data-project-color="#966356"]') as HTMLElement).click();
    expect(onPick).toHaveBeenCalledWith('#966356');
});

test('a legacy color name selects nothing and adds no swatch (hex only since 2026-10-22)', () => {
    draw('cyan');
    expect(checked().map((e) => e.getAttribute('data-project-color'))).toEqual([]);
    expect(document.querySelectorAll('button[data-project-color]').length).toBe(SOFT_PROJECT_COLORS.length);
});

test('the custom swatch wears a wheel svg, opens the popover, commits only on OK, and cancel reports nothing', () => {
    const onPick = draw('#123456');
    const custom = document.querySelector('[data-project-color-custom]') as HTMLElement;
    expect(custom.getAttribute('aria-checked')).toBe('true');
    expect(custom.querySelector('svg[data-project-color-wheel]')).not.toBeNull();
    custom.click();
    flushSync();
    const pop = () => document.querySelector('[data-project-color-popover]');
    expect(pop()).not.toBeNull();
    const red = pop()!.querySelector('input[data-channel="r"]') as HTMLInputElement;
    red.value = '170';
    red.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    (pop()!.querySelector('[data-project-color-cancel]') as HTMLElement).click();
    flushSync();
    expect(onPick).not.toHaveBeenCalled();
    expect(pop()).toBeNull();
    custom.click();
    flushSync();
    const g = pop()!.querySelector('input[data-channel="g"]') as HTMLInputElement;
    g.value = '187';
    g.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    (pop()!.querySelector('[data-project-color-ok]') as HTMLElement).click();
    flushSync();
    expect(onPick).toHaveBeenCalledWith('#12bb56');
    expect(pop()).toBeNull();
});

test('the popover starts from 56/56/56 when the project has no color, and Escape cancels', () => {
    const onPick = draw('');
    (document.querySelector('[data-project-color-custom]') as HTMLElement).click();
    flushSync();
    const pop = document.querySelector('[data-project-color-popover]')!;
    expect([...pop.querySelectorAll<HTMLInputElement>('input[data-channel]')].map((i) => i.value)).toEqual(['56', '56', '56']);
    pop.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    flushSync();
    expect(document.querySelector('[data-project-color-popover]')).toBeNull();
    expect(onPick).not.toHaveBeenCalled();
});

test('no color swatch: absent by default, drawn first with allowNone, pressed when the value is empty, reports an empty pick', () => {
    draw('');
    expect(document.querySelector('[data-project-color-none]')).toBeNull();
    unmount(handle!);
    document.body.innerHTML = '';
    const onPick = vi.fn();
    handle = mount(ProjectColorSwatches, { target: document.body, props: { value: '', labelledBy: 'x', t, onPick, allowNone: true } });
    flushSync();
    const none = document.querySelector('[data-project-color-none]') as HTMLElement;
    expect(none).not.toBeNull();
    expect(document.querySelector('.pc-swatches')!.firstElementChild).toBe(none);
    expect(none.getAttribute('aria-checked')).toBe('true');
    expect(none.getAttribute('aria-label')).toBe('default color');
    expect(document.querySelectorAll('button[data-project-color]').length).toBe(SOFT_PROJECT_COLORS.length);
    (document.querySelector('[data-project-color="#966356"]') as HTMLElement).click();
    none.click();
    expect(onPick.mock.calls).toEqual([['#966356'], ['']]);
});

test('the popover previews every change live; cancel ends the preview, OK leaves it for the caller to end', () => {
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { cb(0); return 1; });
    const onPreview = vi.fn();
    const onPick = vi.fn();
    handle = mount(ProjectColorSwatches, { target: document.body, props: { value: '#123456', labelledBy: 'x', t, onPick, onPreview } });
    flushSync();
    const custom = document.querySelector('[data-project-color-custom]') as HTMLElement;
    const pop = () => document.querySelector('[data-project-color-popover]') as HTMLElement;
    custom.click();
    flushSync();
    expect(pop().querySelector('input[type="color"]')).toBeNull();
    const r = pop().querySelector('input[data-channel="r"]') as HTMLInputElement;
    r.value = '170';
    r.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    const gg = pop().querySelector('input[data-channel="g"]') as HTMLInputElement;
    gg.value = '0';
    gg.dispatchEvent(new Event('input', { bubbles: true }));
    const bb = pop().querySelector('input[data-channel="b"]') as HTMLInputElement;
    bb.value = '0';
    bb.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    expect(onPreview).toHaveBeenLastCalledWith('#aa0000');
    const square = pop().querySelector('[data-pc-square]') as HTMLElement;
    square.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', shiftKey: true, bubbles: true }));
    flushSync();
    expect(onPreview).toHaveBeenLastCalledWith('#c30000');
    const g = pop().querySelector('input[data-channel="g"]') as HTMLInputElement;
    g.value = '187';
    g.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    expect(onPreview).toHaveBeenLastCalledWith('#c3bb00');
    (pop().querySelector('[data-project-color-cancel]') as HTMLElement).click();
    flushSync();
    expect(onPreview).toHaveBeenLastCalledWith(null);
    expect(onPick).not.toHaveBeenCalled();
    onPreview.mockClear();
    custom.click();
    flushSync();
    (pop().querySelector('[data-project-color-ok]') as HTMLElement).click();
    flushSync();
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPreview).not.toHaveBeenCalledWith(null);
    vi.unstubAllGlobals();
});
