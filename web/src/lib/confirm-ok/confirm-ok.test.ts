/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DANGER_START_FOCUS } from './focus-policy';
import { confirmChoice, confirmOk, onMiddleClick, suppressMiddleAutoscroll } from './confirm-ok';

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

describe('confirmOk options', () => {
    afterEach(() => { document.body.innerHTML = ''; });

    it('shows details under the message and none when absent', async () => {
        const withDetails = confirmOk({ title: 't', message: 'm', details: 'cannot be undone' });
        await flush();
        expect(document.querySelector('[data-confirm-ok-details]')!.textContent).toBe('cannot be undone');
        document.querySelector<HTMLButtonElement>('[data-confirm-ok-cancel]')!.click();
        await withDetails;
        const bare = confirmOk({ title: 't', message: 'm' });
        await flush();
        expect(document.querySelector('[data-confirm-ok-details]')).toBeNull();
        document.querySelector<HTMLButtonElement>('[data-confirm-ok-cancel]')!.click();
        await bare;
    });

    it('a danger confirm wears the danger button and starts where DANGER_START_FOCUS says', async () => {
        const answer = confirmOk({ title: 't', message: 'm', variant: 'danger' });
        await flush();
        const go = document.querySelector<HTMLButtonElement>('[data-confirm-ok-go]')!;
        expect(go.getAttribute('data-btn')).toBe('danger');
        const start = DANGER_START_FOCUS === 'cancel' ? '[data-confirm-ok-cancel]' : '[data-confirm-ok-go]';
        expect(document.activeElement).toBe(document.querySelector(start));
        go.click();
        expect(await answer).toBe(true);
    });

    it('Enter on a danger dialog acts only from the ok button, never from the message text', async () => {
        const answer = confirmOk({ title: 't', message: 'm', variant: 'danger' });
        await flush();
        const text = document.querySelector<HTMLElement>('[data-confirm-ok-message]')!;
        const stray = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
        text.dispatchEvent(stray);
        document.querySelector('.modal-overlay')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
        expect(document.querySelector('.modal-overlay')).not.toBeNull();
        document.querySelector<HTMLButtonElement>('[data-confirm-ok-go]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
        expect(await answer).toBe(true);
    });

    it('Enter on the cancel button is left to the browser, which presses cancel', async () => {
        const answer = confirmOk({ title: 't', message: 'm' });
        await flush();
        const cancel = document.querySelector<HTMLButtonElement>('[data-confirm-ok-cancel]')!;
        const enter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
        cancel.dispatchEvent(enter);
        expect(enter.defaultPrevented).toBe(false);
        cancel.click();
        expect(await answer).toBe(false);
    });

    it('Enter on the dialog itself confirms a plain dialog', async () => {
        const answer = confirmOk({ title: 't', message: 'm' });
        await flush();
        document.querySelector('.modal-overlay')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
        expect(await answer).toBe(true);
    });
});

describe('confirmChoice (three buttons)', () => {
    afterEach(() => { document.body.innerHTML = ''; });

    async function open() {
        const answer = confirmChoice({ title: 'download', message: 'unsaved edits', okLabel: 'save and download', altLabel: 'download saved copy' });
        await flush();
        return { answer };
    }

    it('shows cancel, the alt and ok in that order, and each button answers its own value', async () => {
        for (const [selector, expected] of [['[data-confirm-ok-go]', 'ok'], ['[data-confirm-ok-alt]', 'alt'], ['[data-confirm-ok-cancel]', 'cancel']] as const) {
            const { answer } = await open();
            const order = [...document.querySelectorAll('.modal-footer button')].map((b) => b.textContent);
            expect(order).toEqual(['cancel', 'download saved copy', 'save and download']);
            document.querySelector<HTMLButtonElement>(selector)!.click();
            expect(await answer).toBe(expected);
        }
    });

    it('Enter on the alt button is the alt button, not ok', async () => {
        const { answer } = await open();
        const alt = document.querySelector<HTMLButtonElement>('[data-confirm-ok-alt]')!;
        const enter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
        alt.dispatchEvent(enter);
        expect(enter.defaultPrevented).toBe(false);
        alt.click();
        expect(await answer).toBe('alt');
    });

    it('Escape is cancel', async () => {
        const { answer } = await open();
        document.querySelector('.modal-overlay')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        expect(await answer).toBe('cancel');
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
