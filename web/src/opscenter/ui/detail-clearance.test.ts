// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it } from 'vitest';
import { CLEAR_ATTR, CLEAR_PROP, clearToasts, clearanceFor } from './detail-clearance';

const root = document.documentElement;

afterEach(() => {
    document.body.innerHTML = '';
});

function pane(left: number): HTMLElement {
    const el = document.createElement('section');
    el.getBoundingClientRect = () => ({ left }) as DOMRect;
    document.body.append(el);
    return el;
}

describe('detail pane clearance for the toast stack', () => {
    it('steps the stack in to end where a side pane begins (Plugins at 1212px)', () => {
        expect(clearanceFor(700, 1212)).toEqual({ mode: 'side', right: 512 });
    });

    it('drops the stack to the bottom when the pane leaves no room beside it (540px)', () => {
        expect(clearanceFor(0, 540)).toEqual({ mode: 'full' });
        expect(clearanceFor(300, 540)).toEqual({ mode: 'full' });
    });

    it('publishes on the root while a pane is mounted and removes it on destroy', () => {
        Object.defineProperty(window, 'innerWidth', { value: 1212, configurable: true });
        const handle = clearToasts(pane(700));
        expect(root.getAttribute(CLEAR_ATTR)).toBe('side');
        expect(root.style.getPropertyValue(CLEAR_PROP)).toBe('512px');
        handle.destroy();
        expect(root.hasAttribute(CLEAR_ATTR)).toBe(false);
        expect(root.style.getPropertyValue(CLEAR_PROP)).toBe('');
    });

    it('the toast stack reads what the pane publishes', () => {
        const css = readFileSync('../client/css/toast.css', 'utf8');
        expect(css).toContain('var(--oc-toast-clear-right, 0px)');
        expect(css).toMatch(/:root\[data-toast-clear="full"\] \.toast-container/);
    });
});
