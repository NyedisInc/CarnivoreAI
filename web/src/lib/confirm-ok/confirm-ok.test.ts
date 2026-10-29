/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { confirmOk, onMiddleClick, suppressMiddleAutoscroll } from './confirm-ok';

const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

describe('confirmOk', () => {
    afterEach(() => { document.body.innerHTML = ''; });

    async function open(): Promise<{ answer: Promise<boolean>; ok: HTMLButtonElement }> {
        const answer = confirmOk({ title: 'close tab', message: 'close tab a?' });
        await flush();
        return { answer, ok: document.querySelector<HTMLButtonElement>('[data-confirm-ok-go]')! };
    }

    it('focuses ok by default, with the confirm look and the catalog words', async () => {
        const { ok } = await open();
        expect(document.activeElement).toBe(ok);
        expect(ok.getAttribute('data-btn')).toBe('confirm');
        expect(ok.textContent).toBe('ok');
        expect(document.querySelector('[data-confirm-ok-cancel]')!.getAttribute('data-btn')).toBe('secondary');
    });

    it('Enter on the focused ok confirms (the browser presses the focused button)', async () => {
        const { answer, ok } = await open();
        expect(document.activeElement).toBe(ok);
        ok.click();
        expect(await answer).toBe(true);
        expect(document.querySelector('.modal-overlay')).toBeNull();
    });

    it('Escape cancels', async () => {
        const { answer } = await open();
        document.querySelector('.modal-overlay')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        expect(await answer).toBe(false);
    });

    it('cancel cancels', async () => {
        const { answer } = await open();
        document.querySelector<HTMLButtonElement>('[data-confirm-ok-cancel]')!.click();
        expect(await answer).toBe(false);
    });
});

describe('middle-click helpers', () => {
    it('suppresses autoscroll for the middle button only', () => {
        const mid = new MouseEvent('mousedown', { button: 1, cancelable: true });
        const left = new MouseEvent('mousedown', { button: 0, cancelable: true });
        suppressMiddleAutoscroll(mid);
        suppressMiddleAutoscroll(left);
        expect(mid.defaultPrevented).toBe(true);
        expect(left.defaultPrevented).toBe(false);
    });

    it('runs only for the middle button', () => {
        const run = vi.fn();
        expect(onMiddleClick(new MouseEvent('auxclick', { button: 2 }), run)).toBe(false);
        expect(run).not.toHaveBeenCalled();
        expect(onMiddleClick(new MouseEvent('auxclick', { button: 1, cancelable: true }), run)).toBe(true);
        expect(run).toHaveBeenCalledOnce();
    });
});
