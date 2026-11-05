/** @vitest-environment jsdom */
import assert from 'node:assert/strict';
import { flushSync, untrack } from 'svelte';
import { describe, it } from 'vitest';
import * as Bar from './bar';

describe('a bar repaint inside an in-flight Svelte update', () => {
    it('leaves a sibling subtree drawing afterwards', () => {
        document.body.innerHTML = '<div id="session-sidebar-bar-slot"></div><p id="out"></p>';
        Bar.reset();
        const out = document.getElementById('out') as HTMLElement;
        let shown = 0;
        let ticks = 0;
        let bump = (): void => {};
        const cleanup = $effect.root(() => {
            let tick = $state(0);
            let n = $state(0);
            const doubled = $derived(n * 2);
            $effect.pre(() => {
                void tick;
                untrack(() => (n += 1));
                Bar.paint();
                untrack(() => (n += 1));
            });
            $effect(() => {
                out.textContent = String(doubled);
                shown = doubled;
            });
            $effect(() => {
                void tick;
                ticks += 1;
            });
            bump = () => {
                tick += 1;
            };
        });
        flushSync();
        for (let i = 1; i <= 3; i++) {
            bump();
            flushSync();
            assert.equal(out.textContent, String(4 + i * 4), `write ${i} drew`);
        }
        assert.equal(shown, 16);
        assert.ok(ticks >= 4);
        cleanup();
    });
});
