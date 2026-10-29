/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { revealOnPhone } from './phone-reveal';

function fixture(scrollTop: number, paneTop: number): { screen: HTMLElement; pane: HTMLElement } {
    const screen = document.createElement('div');
    screen.className = 'oc-page';
    const pane = document.createElement('div');
    screen.appendChild(pane);
    document.body.appendChild(screen);
    screen.scrollTop = scrollTop;
    screen.getBoundingClientRect = () => ({ top: 54 }) as DOMRect;
    pane.getBoundingClientRect = () => ({ top: paneTop }) as DOMRect;
    return { screen, pane };
}

function stubWidth(matches: boolean): void {
    vi.stubGlobal('matchMedia', (query: string) => ({ matches, media: query }) as MediaQueryList);
}

afterEach(() => {
    vi.unstubAllGlobals();
    document.body.innerHTML = '';
});

describe('revealOnPhone', () => {
    test('on a phone, a pane opened above the viewport is scrolled to the screen top', () => {
        stubWidth(true);
        const { screen, pane } = fixture(913, -208);
        revealOnPhone(pane);
        expect(screen.scrollTop).toBe(651);
    });

    test('above the phone breakpoint nothing moves', () => {
        stubWidth(false);
        const { screen, pane } = fixture(913, -208);
        revealOnPhone(pane);
        expect(screen.scrollTop).toBe(913);
    });
});
