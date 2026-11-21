/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { homeLayout } from '../../../opscenter/engine/layout.svelte';
import { editorSeams, finishLayoutEditor, layoutEditor } from '../../../opscenter/layout-editor/editor.svelte';

const real = { ...editorSeams };
afterEach(() => {
    finishLayoutEditor();
    Object.assign(editorSeams, real);
});

describe('section heading menu: edit layout', { timeout: 100_000 }, () => {
    test.each(['home', 'terminal', 'warroom'] as const)('is offered and works on the %s page', async (page) => {
        editorSeams.page = () => page;
        editorSeams.store = () => homeLayout;
        editorSeams.wide = () => true;
        await import('./all');
        const { itemMenu } = await import('../registry');
        const built = itemMenu('section', { key: 'companies', anchor: document.createElement('div') }, { close: () => {}, glyph: () => '' });
        const nodes = built!.nodes as unknown as { id: string; run: () => void }[];
        const node = nodes.find((n) => n.id === 'edit-layout');
        expect(node).toBeDefined();
        node!.run();
        expect(layoutEditor.active).toBe(true);
        expect(layoutEditor.page).toBe(page);
    });
});
