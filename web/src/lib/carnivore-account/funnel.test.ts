/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cancelPendingAccount, requireAccount, SIGNIN_REQUEST_EVENT } from './funnel';
import { startAccountStore } from './account-store.svelte';

let signedIn = false;
let stop: () => void;

async function sessionEvent(): Promise<void> {
    window.dispatchEvent(new Event('cloude:catalog-session'));
    await vi.waitFor(() => undefined);
    await new Promise((r) => setTimeout(r, 0));
}

beforeEach(async () => {
    signedIn = false;
    (globalThis as any).API = { getCatalogSession: async () => ({ signed_in: signedIn, login: 'a@b.c', provider: 'email' }) };
    stop = startAccountStore();
    await new Promise((r) => setTimeout(r, 0));
});
afterEach(() => {
    cancelPendingAccount();
    stop();
});

describe('requireAccount', () => {
    it('signed out opens once and resumes exactly once after the session event', async () => {
        const opened = vi.fn();
        window.addEventListener(SIGNIN_REQUEST_EVENT, opened);
        const resume = vi.fn();
        await requireAccount({ feature: 'share_link', src: 'menu', resume });
        await requireAccount({ feature: 'share_link', src: 'menu', resume });
        expect(opened).toHaveBeenCalledTimes(1);
        expect((opened.mock.calls[0]?.[0] as CustomEvent).detail).toEqual({ feature: 'share_link', src: 'menu' });
        expect(resume).not.toHaveBeenCalled();
        signedIn = true;
        await sessionEvent();
        expect(resume).toHaveBeenCalledTimes(1);
        await sessionEvent();
        expect(resume).toHaveBeenCalledTimes(1);
        window.removeEventListener(SIGNIN_REQUEST_EVENT, opened);
    });

    it('signed in resumes immediately', async () => {
        signedIn = true;
        await sessionEvent();
        const resume = vi.fn();
        await requireAccount({ feature: 'rate', src: 'rate', resume });
        expect(resume).toHaveBeenCalledTimes(1);
    });

    it('a guest_ok feature runs without opening the sign-in modal while signed out', async () => {
        const opened = vi.fn();
        window.addEventListener(SIGNIN_REQUEST_EVENT, opened);
        const resume = vi.fn();
        expect(await requireAccount({ feature: 'rate', src: 'rate', resume })).toBe('resumed');
        expect(await requireAccount({ feature: 'install_report', src: 'install', resume })).toBe('resumed');
        expect(resume).toHaveBeenCalledTimes(2);
        expect(opened).not.toHaveBeenCalled();
        const held = vi.fn();
        expect(await requireAccount({ feature: 'comment', src: 'rate', resume: held })).toBe('prompted');
        expect(opened).toHaveBeenCalledTimes(1);
        expect(held).not.toHaveBeenCalled();
        window.removeEventListener(SIGNIN_REQUEST_EVENT, opened);
    });

    it('a dropped pending resume never runs', async () => {
        const resume = vi.fn();
        await requireAccount({ feature: 'note', src: 'chip', resume });
        cancelPendingAccount();
        signedIn = true;
        await sessionEvent();
        expect(resume).not.toHaveBeenCalled();
    });
});
