/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { confirmPositional } from './confirm-ok';

const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));
const appSource = fs.readFileSync(path.join(process.cwd(), '..', 'client', 'js', 'app.js'), 'utf8');

type LegacyApp = { showConfirmModal(...args: unknown[]): Promise<boolean> };

function loadLegacyApp(): LegacyApp {
    const noop = () => undefined;
    const sandbox: Record<string, unknown> = {
        document, console, setTimeout, clearTimeout,
        addEventListener: noop, removeEventListener: noop, location: window.location,
        CloudeWeb: { launchpad: { confirm: confirmPositional } },
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.runInNewContext(`${appSource}\n;globalThis.__app = App;`, sandbox);
    return sandbox.__app as LegacyApp;
}

const press = (el: Element, key: string): void => { el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })); };
const active = (): Element => document.activeElement as Element;

describe('App.showConfirmModal forwards to the one confirm', () => {
    let app: LegacyApp;
    beforeEach(() => { app = loadLegacyApp(); });
    afterEach(() => { document.body.innerHTML = ''; });

    it('renders through ModalShell with the caller words and details, and Enter resolves true', async () => {
        const answer = app.showConfirmModal('remove group', 'remove "a"?', 'members stay', 'remove', 'keep');
        await flush();
        expect(document.querySelector('.modal-overlay[role="dialog"]')).not.toBeNull();
        expect(document.querySelector('.modal-titlerow, .text-prompt-modal__verb')!.textContent).toContain('remove group');
        expect(document.querySelector('[data-confirm-ok-message]')!.textContent).toBe('remove "a"?');
        expect(document.querySelector('[data-confirm-ok-details]')!.textContent).toBe('members stay');
        expect(document.querySelector('[data-confirm-ok-go]')!.textContent).toBe('remove');
        expect(document.querySelector('[data-confirm-ok-cancel]')!.textContent).toBe('keep');
        press(active(), 'Enter');
        expect(await answer).toBe(true);
        expect(document.querySelector('.modal-overlay')).toBeNull();
    });

    it('Escape resolves false', async () => {
        const answer = app.showConfirmModal('t', 'm');
        await flush();
        press(active(), 'Escape');
        expect(await answer).toBe(false);
    });

    it('a danger dialog wears the danger button; Enter on ok confirms', async () => {
        const answer = app.showConfirmModal('t', 'm', null, 'delete', 'cancel', 'danger');
        await flush();
        const go = document.querySelector('[data-confirm-ok-go]')!;
        expect(go.getAttribute('data-btn')).toBe('danger');
        press(go, 'Enter');
        expect(await answer).toBe(true);
    });

    it('a plain dialog starts on the confirming button', async () => {
        const answer = app.showConfirmModal('t', 'm');
        await flush();
        expect(active()).toBe(document.querySelector('[data-confirm-ok-go]'));
        document.querySelector<HTMLButtonElement>('[data-confirm-ok-cancel]')!.click();
        expect(await answer).toBe(false);
    });
});
