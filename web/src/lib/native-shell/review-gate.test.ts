/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { mount, unmount } from 'svelte';
import SignInModal from '../carnivore-account/SignInModal.svelte';
import { openWarezScreen } from '../catalog/warez-host';
import { openPublishPage } from '../catalog/publish-entry';
import { RAIL_DESTINATIONS, railItemVisible } from '../../opscenter/shell/rail-items';

type Win = { carnivoreShell?: unknown; webkit?: unknown };
const w = globalThis as unknown as Win;
let panel: Record<string, unknown> | null = null;

function fakeShell(): void {
    w.carnivoreShell = { version: 1, platform: 'ios' };
    w.webkit = { messageHandlers: { carnivore: { postMessage: () => undefined } } };
}

function open(): void {
    const host = { startWeb: async () => ({}), pollWeb: async () => ({}), startEmail: async () => ({}), verifyEmail: async () => ({}), verifyMailbox: async () => ({}) };
    panel = mount(SignInModal, { target: document.body, props: { feature: 'share_link', src: 'menu', close: () => undefined, host } as never }) as never;
}

beforeEach(() => {
    delete w.carnivoreShell;
    delete w.webkit;
    document.body.innerHTML = '';
    location.hash = '';
});
afterEach(() => {
    if (panel) unmount(panel as never);
    panel = null;
});

describe('app review gate', () => {
    test('in the shell: no provider buttons, no warez row, no warez page, no publish page', () => {
        fakeShell();
        open();
        expect(document.querySelector('[data-signin-provider]')).toBeNull();
        expect(document.querySelector('[data-signin-email]')).not.toBeNull();
        expect(railItemVisible(RAIL_DESTINATIONS.find((i) => i.id === 'warez')!)).toBe(false);
        expect(openWarezScreen()).toBe(false);
        openPublishPage();
        expect(location.hash).toBe('');
    });

    test('in a plain browser: provider buttons, warez row and publish link stay', () => {
        open();
        expect(document.querySelector('[data-signin-provider="google"]')).not.toBeNull();
        expect(document.querySelector('[data-signin-provider="github"]')).not.toBeNull();
        expect(railItemVisible(RAIL_DESTINATIONS.find((i) => i.id === 'warez')!)).toBe(true);
        openPublishPage();
        expect(location.hash).toContain('warez/publish');
    });
});
