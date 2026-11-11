/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { openWidgetMenu } from './widget-gesture';

afterEach(() => {
    document.body.innerHTML = '';
});

function grid(): { view: HTMLElement; corner: HTMLElement; headed: HTMLElement } {
    document.body.innerHTML =
        '<div><section data-cell="a"><button data-corner></button></section>' +
        '<section data-cell="b"><div id="view"></div></section>' +
        '<section data-cell="c"><button data-corner></button><div id="headed"></div></section></div>';
    const q = (s: string) => document.querySelector<HTMLElement>(s)!;
    return { view: q('#view'), corner: q('[data-cell="a"] [data-corner]'), headed: q('#headed') };
}

test('a headerless widget does not click a neighbour icon and dispatches contextmenu', () => {
    const { view, corner } = grid();
    const click = vi.fn();
    corner.addEventListener('click', click);
    const seen = vi.fn();
    view.addEventListener('contextmenu', seen);
    openWidgetMenu({ x: 5, y: 6 }, view);
    expect(click).not.toHaveBeenCalled();
    expect(seen).toHaveBeenCalledTimes(1);
});

test('a widget with a header clicks its own icon', () => {
    const { headed } = grid();
    const own = document.querySelector<HTMLElement>('[data-cell="c"] [data-corner]')!;
    const click = vi.fn();
    own.addEventListener('click', click);
    openWidgetMenu(null, headed);
    expect(click).toHaveBeenCalledTimes(1);
});
