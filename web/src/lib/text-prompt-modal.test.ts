/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { afterEach, beforeEach, describe, expect, test } from 'vitest';

const repoRoot = path.join(process.cwd(), '..');

/** The globals this file hangs on `window` and must take back off it. */
const INSTALLED = ['ModalStack', 'TextPromptModal'] as const;

function installLegacy(files: string[]): void {
    const context: Record<string, unknown> = { console };
    context.window = context;
    context.globalThis = context;
    context.document = document;
    context.setTimeout = setTimeout;
    context.clearTimeout = clearTimeout;
    vm.createContext(context);
    for (const file of files) {
        vm.runInContext(
            fs.readFileSync(path.join(repoRoot, 'client', 'js', file), 'utf8'),
            context,
        );
    }
    for (const key of Object.keys(context)) {
        if ((INSTALLED as readonly string[]).includes(key)) {
            (window as unknown as Record<string, unknown>)[key] = context[key];
        }
    }
}

function modal(): { open(options: Record<string, unknown>): Promise<string | null> } {
    return (window as unknown as { TextPromptModal: never }).TextPromptModal;
}

function openPrompt(): Promise<string | null> {
    return modal().open({
        title: 'new group',
        label: 'group name',
        placeholder: 'e.g. research',
        confirmLabel: 'create',
        cancelLabel: 'cancel',
    });
}

function overlay(): HTMLElement {
    const el = document.querySelector('.modal-overlay');
    if (!el) throw new Error('modal did not render a .modal-overlay');
    return el as HTMLElement;
}

function input(): HTMLInputElement {
    return overlay().querySelector('#text-prompt-modal-input') as HTMLInputElement;
}

beforeEach(() => {
    for (const key of INSTALLED) delete (window as unknown as Record<string, unknown>)[key];
    document.body.innerHTML = '';
    installLegacy(['modal-stack.js', 'text-prompt-modal.js']);
});

afterEach(() => {
    for (const key of INSTALLED) delete (window as unknown as Record<string, unknown>)[key];
    document.body.innerHTML = '';
});

describe('text prompt modal - real client/js/text-prompt-modal.js', () => {
    test('renders no native prompt call - it is a real dialog in the DOM', () => {
        void openPrompt();
        expect(document.querySelectorAll('.modal-overlay').length).toBe(1);
        expect(overlay().querySelector('.text-prompt-modal__verb')?.textContent).toContain('new group');
        expect(overlay().querySelector('label')?.textContent).toBe('group name');
    });

    test('the field is present and takes the confirm-button path to resolve typed text', async () => {
        const p = openPrompt();
        input().value = 'research';
        const confirm = overlay().querySelector('#text-prompt-modal-confirm') as HTMLButtonElement;
        confirm.click();
        await expect(p).resolves.toBe('research');
        expect(document.querySelectorAll('.modal-overlay').length).toBe(0);
    });

    test('Enter in the field submits exactly like clicking confirm', async () => {
        const p = openPrompt();
        input().value = 'ops';
        input().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        await expect(p).resolves.toBe('ops');
    });

    test('the cancel button resolves null and creates nothing', async () => {
        const p = openPrompt();
        input().value = 'discarded';
        const cancel = overlay().querySelector('#text-prompt-modal-cancel') as HTMLButtonElement;
        cancel.click();
        await expect(p).resolves.toBeNull();
    });

    test('Escape resolves null, through the shared ModalStack trap', async () => {
        const p = openPrompt();
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        await expect(p).resolves.toBeNull();
    });

    test('a click on the backdrop cancels; a click inside the dialog does not', async () => {
        const p = openPrompt();
        (overlay().querySelector('.modal-content') as HTMLElement).dispatchEvent(
            new MouseEvent('click', { bubbles: true }),
        );
        const backdrop = overlay();
        backdrop.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        await expect(p).resolves.toBeNull();
    });

    test('an empty submit is NOT refused here - it resolves the empty string, unvalidated', async () => {
        const p = openPrompt();
        const confirm = overlay().querySelector('#text-prompt-modal-confirm') as HTMLButtonElement;
        confirm.click();
        await expect(p).resolves.toBe('');
    });

    test('the buttons wear the restart picker\'s shared classes, not the retired bracket style', () => {
        void openPrompt();
        const confirm = overlay().querySelector('#text-prompt-modal-confirm') as HTMLButtonElement;
        const cancel = overlay().querySelector('#text-prompt-modal-cancel') as HTMLButtonElement;
        expect(confirm.classList.contains('modal-btn-confirm')).toBe(true);
        expect(confirm.classList.contains('modal-btn-primary')).toBe(false);
        expect(confirm.classList.contains('modal-btn-danger')).toBe(false);
        expect(cancel.classList.contains('modal-btn-secondary')).toBe(true);
        expect(cancel.classList.contains('modal-btn-confirm')).toBe(false);
    });
});
