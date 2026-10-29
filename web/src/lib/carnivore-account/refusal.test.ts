/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const registerOpen = vi.fn();
vi.mock('./open-register', () => ({ openRegisterModal: () => registerOpen() }));

import { authFetch } from '../../opscenter/api/auth.svelte';
import { cancelPendingAccount, registerSignInOpener } from './funnel';
import { installRefusalHandler, withoutRegisterDialog } from './refusal';

const opener = vi.fn();

function answer(status: number, body: unknown): void {
    globalThis.fetch = vi.fn(async () => new Response(JSON.stringify(body), { status })) as never;
}

async function call(): Promise<void> {
    await authFetch('/x').catch(() => undefined);
    await new Promise((r) => setTimeout(r, 0));
}

beforeEach(() => {
    opener.mockReset();
    registerOpen.mockReset();
    registerSignInOpener(opener);
    installRefusalHandler();
});
afterEach(() => {
    cancelPendingAccount();
    registerSignInOpener(null);
});

describe('account refusals through authFetch', () => {
    it('account_required opens the sign-in modal for its feature', async () => {
        answer(403, { code: 'account_required', feature: 'share_link', detail: 'sign in' });
        await call();
        expect(opener).toHaveBeenCalledTimes(1);
        expect(opener).toHaveBeenCalledWith({ feature: 'share_link', src: 'refusal' });
    });

    it('the code nested in detail is read too, and an unknown feature is generic', async () => {
        answer(403, { detail: { code: 'account_required', feature: 'nope' } });
        await call();
        expect(opener).toHaveBeenCalledWith({ feature: 'generic', src: 'refusal' });
    });

    it('the catalog signed-out 403 opens the generic modal; a revoked session says so', async () => {
        answer(403, { code: 'unauthorized' });
        await call();
        expect(opener).toHaveBeenLastCalledWith({ feature: 'generic', src: 'refusal' });
        cancelPendingAccount();
        answer(403, { code: 'session_revoked' });
        await call();
        expect(opener).toHaveBeenLastCalledWith({ feature: 'generic', src: 'revoked' });
    });

    it('a 401 from the app login never opens it, even with an account code in the body', async () => {
        answer(401, { code: 'account_required', feature: 'share_link' });
        await call();
        expect(opener).not.toHaveBeenCalled();
        expect(registerOpen).not.toHaveBeenCalled();
    });

    it('a burst of refusals opens the modal once', async () => {
        answer(403, { code: 'account_required', feature: 'phone_link' });
        await Promise.all([call(), call(), call()]);
        expect(opener).toHaveBeenCalledTimes(1);
    });

    it('a registration code opens the handle step, and a plain 403 opens nothing', async () => {
        answer(403, { detail: { code: 'handle_required' } });
        await call();
        expect(registerOpen).toHaveBeenCalledTimes(1);
        answer(403, { detail: 'not available over the link' });
        await call();
        expect(opener).not.toHaveBeenCalled();
        expect(registerOpen).toHaveBeenCalledTimes(1);
    });

    it('a registration refusal inside withoutRegisterDialog opens no dialog, and the next one outside it does (X5-52)', async () => {
        answer(403, { detail: { code: 'handle_required' } });
        await withoutRegisterDialog(call);
        expect(registerOpen).not.toHaveBeenCalled();
        await call();
        expect(registerOpen).toHaveBeenCalledTimes(1);
    });

    it('withoutRegisterDialog keeps the sign-in modal for a sign-in refusal', async () => {
        answer(403, { code: 'account_required', feature: 'share_link' });
        await withoutRegisterDialog(call);
        expect(opener).toHaveBeenCalledTimes(1);
    });
});
