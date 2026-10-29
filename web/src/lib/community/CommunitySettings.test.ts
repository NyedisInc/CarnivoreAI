/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import CommunitySettings from './CommunitySettings.svelte';
import type { CommunityHost } from './community';
import { createI18n } from '../../../../client/js/i18n/runtime.js';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);
const settle = () => new Promise<void>((resolve) => setTimeout(resolve, 10));

let panel: Record<string, unknown> | null = null;

function show(host: Partial<CommunityHost>) {
    const target = document.createElement('div');
    document.body.appendChild(target);
    panel = mount(CommunitySettings, { target, props: { t, host: host as CommunityHost } as never }) as never;
    flushSync();
}

afterEach(() => {
    if (panel) unmount(panel as never);
    panel = null;
    document.body.innerHTML = '';
});

describe('reply emails', () => {
    it('shows one control with the stored state and one write when it is pressed', async () => {
        const setNotifyReplies = vi.fn(async (on: boolean) => ({ notify_replies: on }));
        show({ readNotifyReplies: async () => true, setNotifyReplies });
        await settle();
        expect(document.querySelectorAll('button').length).toBe(1);
        const check = document.querySelector<HTMLButtonElement>('[data-community-replies]')!;
        expect(check.getAttribute('aria-checked')).toBe('true');
        check.click();
        await settle();
        expect(setNotifyReplies).toHaveBeenCalledWith(false);
        expect(check.getAttribute('aria-checked')).toBe('false');
    });

    it('stays off and disabled when the host does not say', async () => {
        show({ readNotifyReplies: async () => null, setNotifyReplies: vi.fn() });
        await settle();
        const check = document.querySelector<HTMLButtonElement>('[data-community-replies]')!;
        expect(check.disabled).toBe(true);
        expect(check.getAttribute('aria-checked')).toBe('false');
    });
});
