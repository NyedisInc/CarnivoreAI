/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { mount, unmount } from 'svelte';
import { afterEach, describe, expect, test } from 'vitest';

import TallModal from './fixtures/TallModal.svelte';

const SHELL_CSS = /<style>([\s\S]*)<\/style>/.exec(readFileSync('src/lib/dialog-frame/ModalShell.svelte', 'utf8'))![1]!;

let mounted: Record<string, unknown> | null = null;

afterEach(() => {
    if (mounted) void unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
    document.head.innerHTML = '';
});

function frame(): { panel: HTMLElement; body: HTMLElement; footer: HTMLElement; head: HTMLElement } {
    const style = document.createElement('style');
    style.textContent = SHELL_CSS.replace(/@layer components \{[\s\S]*\}\s*$/, '');
    document.head.append(style);
    mounted = mount(TallModal, { target: document.body, props: { rows: 60 } });
    const panel = document.querySelector<HTMLElement>('.modal-content')!;
    return {
        panel,
        body: panel.querySelector<HTMLElement>('.modal-body')!,
        footer: panel.querySelector<HTMLElement>('.modal-footer')!,
        head: panel.querySelector<HTMLElement>('.modal-titlerow')!,
    };
}

describe('ModalShell caps its panel at the window', () => {
    test('the panel is a column no taller than the overlay', () => {
        const { panel } = frame();
        const style = getComputedStyle(panel);
        expect(style.display).toBe('flex');
        expect(style.flexDirection).toBe('column');
        expect(style.maxHeight).toBe('100%');
    });

    test('the body is the scroll container and the footer keeps its place', () => {
        const { body, footer, head } = frame();
        const bodyStyle = getComputedStyle(body);
        expect(bodyStyle.overflowY).toBe('auto');
        expect(bodyStyle.minHeight).toMatch(/^0(px)?$/);
        expect(getComputedStyle(footer).flexShrink).toBe('0');
        expect(getComputedStyle(head).flexShrink).toBe('0');
        expect(footer.querySelector('[data-tall-approve]')).not.toBeNull();
    });
});
