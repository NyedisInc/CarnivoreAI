/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { confirmOk } from './confirm-ok';

const source = fs.readFileSync(path.join(process.cwd(), '..', 'client', 'js', 'modal-stack.js'), 'utf8');
const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

type Stack = { push(el: Element, o: { onEscape(): void }): void; remove?(el: Element): void };

describe('a confirm over a ModalStack dialog', () => {
    afterEach(() => { document.body.innerHTML = ''; });

    it('Escape closes only the confirm, never the dialog under it', async () => {
        new Function(source)();
        const stack = (window as unknown as { ModalStack: Stack }).ModalStack;
        const editor = document.createElement('div');
        editor.className = 'modal-overlay';
        document.body.appendChild(editor);
        let editorEscapes = 0;
        stack.push(editor, { onEscape: () => { editorEscapes += 1; } });

        const answer = confirmOk({ title: 'discard', message: 'discard unsaved changes?' });
        await flush();
        document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
        expect(await answer).toBe(false);
        expect(editorEscapes).toBe(0);

        document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
        expect(editorEscapes).toBe(1);
    });
});
