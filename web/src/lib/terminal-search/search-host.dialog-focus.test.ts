/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { browserSearchHost } from './search-host';
import { installKeyRouting } from './search-keys';

afterEach(() => {
    document.body.replaceChildren();
});

function pressFind(on: HTMLElement): { opened: number; prevented: boolean } {
    const host = browserSearchHost();
    let opened = 0;
    const stop = installKeyRouting({
        isOpen: () => false, containsTarget: () => false, alternate: () => false,
        screenActive: () => true, modalOpen: () => host.modalOpen(),
        open: () => { opened += 1; }, close() {}, step() {}, jump() {},
    }, document);
    const event = new KeyboardEvent('keydown', { key: 'f', metaKey: true, bubbles: true, cancelable: true });
    on.dispatchEvent(event);
    stop();
    return { opened, prevented: event.defaultPrevented };
}

test('focus inside an in-place editor reads as a modal and Cmd+F stays in the editor', () => {
    const editor = document.createElement('div');
    editor.className = 'config-editor-inplace';
    editor.setAttribute('data-modal', 'config-editor');
    const field = document.createElement('textarea');
    editor.append(field);
    document.body.append(editor);
    field.focus();
    expect(document.activeElement).toBe(field);

    expect(browserSearchHost().modalOpen()).toBe(true);
    expect(pressFind(field)).toEqual({ opened: 0, prevented: false });
});

test('control: focus on an ordinary element with nothing stacked still opens search', () => {
    const field = document.createElement('textarea');
    document.body.append(field);
    field.focus();
    expect(document.activeElement).toBe(field);

    expect(browserSearchHost().modalOpen()).toBe(false);
    expect(pressFind(field)).toEqual({ opened: 1, prevented: true });
});
