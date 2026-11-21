/** @vitest-environment jsdom */
import { tick } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import { goKeyChords } from './go-keys.svelte';

describe('goKeyChords', () => {
    it('is the built Cmd+[ and Cmd+] with no overrides', () => {
        expect(goKeyChords({}, 'mac')).toEqual({ 'history.back': ['Cmd+['], 'history.forward': ['Cmd+]'] });
    });
    it('carries an override, an unbind and leaves the other action alone', () => {
        const keys = goKeyChords({ mac: { 'history.back': ['cmd+j'], 'history.forward': [] } }, 'mac');
        expect(keys).toEqual({ 'history.back': ['cmd+j'], 'history.forward': [] });
    });
    it('ignores the other keyboard family', () => {
        expect(goKeyChords({ other: { 'history.back': ['ctrl+j'] } }, 'mac')['history.back']).toEqual(['Cmd+[']);
    });
});

describe('startGoKeys', () => {
    it('publishes at start and again after the saved overrides change', async () => {
        const goKeys = vi.fn();
        vi.doMock('../sessions/env', () => ({ hostWindow: () => ({ carnivoreDesktop: { goKeys } }) }));
        vi.doMock('../palette/palette-host', () => ({ onMac: () => true }));
        vi.resetModules();
        const { keymapStore } = await import('../keymap/keymap-store.svelte');
        vi.spyOn(keymapStore, 'start').mockImplementation(() => {});
        const { startGoKeys } = await import('./go-keys.svelte');
        startGoKeys();
        await tick();
        expect(goKeys).toHaveBeenCalledTimes(1);
        expect(goKeys.mock.calls[0][0]['history.back']).toEqual(['Cmd+[']);
        keymapStore.overrides = { mac: { 'history.back': ['cmd+j'] } };
        await tick();
        expect(goKeys).toHaveBeenCalledTimes(2);
        expect(goKeys.mock.calls[1][0]['history.back']).toEqual(['cmd+j']);
    });
});
