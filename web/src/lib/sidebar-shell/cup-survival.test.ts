/** @vitest-environment jsdom */
import { beforeAll, describe, expect, it } from 'vitest';
import { sidebarShell } from './shell.svelte';
import { loadRowInteractions, settle, startRowRun } from './row-interaction-fixture';

let w: Record<string, any>;
beforeAll(async () => { w = loadRowInteractions(sidebarShell); });

describe('cup survival', () => {
    it('a keep awake change on another row keeps this cup node', async () => {
        startRowRun();
        await settle();
        const cup = document.querySelector('[data-keep-awake-session="cloude_c"]');
        const svg = cup?.querySelector('svg');
        expect(cup).toBeTruthy();
        await w.CloudeWeb.autoSleep.setKeepAwake('cloude_a', true);
        window.dispatchEvent(new CustomEvent('cloude:auto-sleep-changed'));
        await settle();
        const cup2 = document.querySelector('[data-keep-awake-session="cloude_c"]');
        expect(document.querySelector('[data-keep-awake-session="cloude_a"]')).toBeTruthy();
        expect(cup2 === cup).toBe(true);
        expect(cup2?.querySelector('svg') === svg).toBe(true);
    });
});
