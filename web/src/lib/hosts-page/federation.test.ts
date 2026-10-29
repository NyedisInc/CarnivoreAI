/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import { ApiError } from '../../opscenter/api/auth.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { Translate } from '../sessions/types';
import type { DiscoveredMac, FederationApi, GrantRow, PairPending, PeerRow, PendingPair } from './federation-api';
import { errorCode } from './federation-api';
import { machineKey } from './hosts-adapter';
import PairModal from './PairModal.svelte';
import ShowCodeModal from './ShowCodeModal.svelte';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);

let mounted: Record<string, unknown> | null = null;
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

const settle = async (): Promise<void> => {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    await tick();
    flushSync();
};

const peer = (over: Partial<PeerRow>): PeerRow => ({
    key: 'peer-1', label: 'studio', peer_install_id: 'iid-1', fid: 'fid-studio', initiator: true, state: 'connected', protocol: 1, ...over,
});
const pending = (over: Partial<PairPending>): PairPending => ({
    pending: true, nonce: 'nn', sas: '12345 67890', label: 'studio', fid: 'fid-studio', proof: 'typed', peer_owner_confirms: true,
    expires_in: 300, ...over,
});
const seen = (over: Partial<DiscoveredMac>): DiscoveredMac => ({
    name: 'studio', host: 'studio.local.', port: 8000, addresses: [], fid: 'fid-studio', state: 'new', known_host: false, ...over,
});
function fakeFed(over: Partial<{ peers: PeerRow[]; found: DiscoveredMac[]; grants: GrantRow[] }> = {}): FederationApi {
    return {
        discovered: vi.fn(async () => ({ discovered: over.found ?? [], advertise: true, state: 'up', browse_state: 'up' })),
        settings: vi.fn(async () => ({ advertise: true, state: 'up' })),
        setAdvertise: vi.fn(async (advertise: boolean) => ({ advertise, state: 'up' })),
        peers: vi.fn(async () => over.peers ?? []),
        pair: vi.fn(async () => pending({})),
        confirmPair: vi.fn(async (_nonce: string, match: boolean) => (match ? peer({}) : { cancelled: true as const })),
        pending: vi.fn(async () => []),
        confirmPending: vi.fn(async () => ({ state: 'active' })),
        cancelPending: vi.fn(async () => undefined),
        unpair: vi.fn(async () => undefined),
        grants: vi.fn(async () => over.grants ?? []),
        revoke: vi.fn(async () => undefined),
        beginCode: vi.fn(async () => ({ nonce: 'n1', code: 'ABCD2345', expires_in: 600 })),
        rotate: vi.fn(async () => ({ fid: 'new', announced: 1, not_announced: 0 })),
    };
}

describe('machine key', () => {
    test('machineKey drops user and domain but keeps an address whole', () => {
        expect(machineKey('alex@Studio.local')).toBe('studio');
        expect(machineKey('192.168.1.5')).toBe('192.168.1.5');
    });
});

describe('pair dialog (F14)', () => {
    const mountPair = async (fed: FederationApi, found: DiscoveredMac | null = null) => {
        const close = vi.fn();
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PairModal, { target, props: { fed, t, found, close } });
        await settle();
        return close;
    };
    const press = async (selector: string): Promise<void> => {
        (document.querySelector(selector) as HTMLElement).click();
        await settle();
    };
    const type = async (id: string, value: string): Promise<void> => {
        const input = document.getElementById(id) as HTMLInputElement;
        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
    };

    test('zero typing: one press shows the comparison code, one more click on they match closes with the peer, no code asked', async () => {
        const fed = fakeFed();
        (fed.pair as ReturnType<typeof vi.fn>).mockResolvedValueOnce(pending({ proof: 'ssh_file', peer_owner_confirms: false }));
        const close = await mountPair(fed, seen({ state: 'pinned', host: 'studio.local.', port: 22 }));
        await press('[data-fed-pair-confirm]');
        expect(fed.pair).toHaveBeenCalledTimes(1);
        expect(fed.pair).toHaveBeenCalledWith({ ssh_target: 'studio.local', discovered_name: 'studio' });
        expect(document.querySelector('[data-fed-sas]')?.textContent).toBe('12345 67890');
        expect(document.querySelector('[data-fed-sas-peer-confirms]')).toBeNull();
        expect(close).not.toHaveBeenCalled();
        expect(fed.confirmPair).not.toHaveBeenCalled();
        await press('[data-fed-sas-match]');
        expect(fed.confirmPair).toHaveBeenCalledWith('nn', true);
        expect(close).toHaveBeenCalledWith(expect.objectContaining({ key: 'peer-1' }));
        expect(document.getElementById('modal-pair-nonce')).toBeNull();
    });

    test('they differ sends the mismatch, closes with nothing and never returns a peer', async () => {
        const fed = fakeFed();
        const close = await mountPair(fed, seen({}));
        await press('[data-fed-pair-confirm]');
        expect(document.querySelector('[data-fed-sas-peer-confirms]')).not.toBeNull();
        expect(document.querySelector('[data-fed-sas-differ]')?.getAttribute('data-btn')).toBe('danger');
        await press('[data-fed-sas-differ]');
        expect(fed.confirmPair).toHaveBeenCalledWith('nn', false);
        expect(close).toHaveBeenCalledWith(null);
    });

    test('closing the dialog while a code is pending counts as a mismatch', async () => {
        const fed = fakeFed();
        const close = await mountPair(fed, seen({}));
        await press('[data-fed-pair-confirm]');
        await press('[data-modal-close]');
        expect(fed.confirmPair).toHaveBeenCalledWith('nn', false);
        expect(close).toHaveBeenCalledWith(null);
    });

    test('a failed confirm shows its sentence and keeps the code on screen', async () => {
        const fed = fakeFed();
        (fed.confirmPair as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('peer down'));
        const close = await mountPair(fed, seen({}));
        await press('[data-fed-pair-confirm]');
        await press('[data-fed-sas-match]');
        expect(document.querySelector('[data-fed-pair-error]')?.textContent).toContain('peer down');
        expect(document.querySelector('[data-fed-sas]')).not.toBeNull();
        expect(close).not.toHaveBeenCalled();
    });

    test('typed_code_required opens the code screen and the retry carries the typed values', async () => {
        const fed = fakeFed();
        const refusal = new ApiError('first contact', 409, null, { detail: { code: 'typed_code_required', detail: 'first contact' } });
        (fed.pair as ReturnType<typeof vi.fn>).mockRejectedValueOnce(refusal);
        const close = await mountPair(fed);
        await type('modal-pair-target', 'studio.tail1234.ts.net');
        await press('[data-fed-pair-confirm]');
        expect(document.querySelector('[data-fed-pair-reason]')?.textContent).toBe('first contact');
        expect(close).not.toHaveBeenCalled();
        await type('modal-pair-nonce', 'nn');
        await type('modal-pair-code', 'CODE');
        await press('[data-fed-pair-confirm]');
        expect(fed.pair).toHaveBeenLastCalledWith({ ssh_target: 'studio.tail1234.ts.net', typed_nonce: 'nn', typed_code: 'CODE' });
        expect(close).not.toHaveBeenCalled();
        await press('[data-fed-sas-match]');
        expect(close).toHaveBeenCalledTimes(1);
    });

    test('any other refusal is shown and nothing closes', async () => {
        const fed = fakeFed();
        (fed.pair as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new ApiError('peer down', 502, null, { detail: { code: 'peer_unreachable', detail: 'peer down' } }));
        const close = await mountPair(fed, seen({}));
        await press('[data-fed-pair-confirm]');
        expect(document.querySelector('[data-fed-pair-error]')?.textContent).toContain('peer down');
        expect(close).not.toHaveBeenCalled();
    });

    test('errorCode reads the code out of the detail object', () => {
        expect(errorCode(new ApiError('x', 409, null, { detail: { code: 'typed_code_required' } }))).toBe('typed_code_required');
        expect(errorCode(new Error('x'))).toBeNull();
    });
});

describe('the acceptor screen (P10)', () => {
    const waiting = (over: Partial<PendingPair> = {}): PendingPair => ({
        nonce: 'n1', sas: '12345 67890', label: 'studio', fid: 'fid-studio', proof: 'typed', initiator_accepted: false,
        owner_confirmed: false, expires_in: 200, ...over,
    });
    const open = async (fed: FederationApi) => {
        const close = vi.fn();
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(ShowCodeModal, { target, props: { fed, t, pollMs: 5, close } });
        await settle();
        return close;
    };
    const later = async (): Promise<void> => {
        await new Promise((r) => setTimeout(r, 30));
        await settle();
    };

    test('the code shows until another mac uses it, then the comparison code replaces it', async () => {
        const fed = fakeFed();
        await open(fed);
        expect(document.querySelector('[data-fed-code-value]')?.textContent).toBe('ABCD2345');
        (fed.pending as ReturnType<typeof vi.fn>).mockResolvedValue([waiting()]);
        await later();
        expect(document.querySelector('[data-fed-sas]')?.textContent).toBe('12345 67890');
        expect(document.querySelector('[data-fed-code-value]')).toBeNull();
        expect(document.querySelector('[data-fed-sas-differ]')?.getAttribute('data-btn')).toBe('danger');
    });

    test('a pairing with another id is not shown here', async () => {
        const fed = fakeFed();
        (fed.pending as ReturnType<typeof vi.fn>).mockResolvedValue([waiting({ nonce: 'other' })]);
        await open(fed);
        await later();
        expect(document.querySelector('[data-fed-sas]')).toBeNull();
    });

    test('they match confirms on this mac; they differ cancels the pairing and closes', async () => {
        const fed = fakeFed();
        (fed.pending as ReturnType<typeof vi.fn>).mockResolvedValue([waiting()]);
        const close = await open(fed);
        await later();
        (document.querySelector('[data-fed-sas-differ]') as HTMLElement).click();
        await settle();
        expect(fed.cancelPending).toHaveBeenCalledWith('n1');
        expect(close).toHaveBeenCalledWith(null);
        expect(fed.confirmPending).not.toHaveBeenCalled();
    });

    test('a match that the server says is still waiting on the other mac keeps the dialog open', async () => {
        const fed = fakeFed();
        (fed.pending as ReturnType<typeof vi.fn>).mockResolvedValue([waiting()]);
        (fed.confirmPending as ReturnType<typeof vi.fn>).mockResolvedValue({ state: 'awaiting_initiator' });
        const close = await open(fed);
        await later();
        (document.querySelector('[data-fed-sas-match]') as HTMLElement).click();
        await settle();
        expect(fed.confirmPending).toHaveBeenCalledWith('n1');
        expect(close).not.toHaveBeenCalled();
        expect(document.querySelector('[data-fed-sas-waiting]')).not.toBeNull();
        (fed.pending as ReturnType<typeof vi.fn>).mockResolvedValue([]);
        await later();
        expect(close).toHaveBeenCalledWith(null);
    });

    test('a confirm that throws leaves the match button usable for a retry (u140-02)', async () => {
        const fed = fakeFed();
        (fed.pending as ReturnType<typeof vi.fn>).mockResolvedValue([waiting()]);
        (fed.confirmPending as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('network down'));
        await open(fed);
        await later();
        const match = document.querySelector('[data-fed-sas-match]') as HTMLButtonElement;
        match.click();
        await settle();
        expect(document.querySelector('[data-fed-code-error]')).not.toBeNull();
        expect((document.querySelector('[data-fed-sas-match]') as HTMLButtonElement).disabled).toBe(false);
        (document.querySelector('[data-fed-sas-match]') as HTMLButtonElement).click();
        await settle();
        expect(fed.confirmPending).toHaveBeenCalledTimes(2);
    });

    test('closing the dialog while a comparison is waiting and not yet confirmed here cancels the pairing (u140-02)', async () => {
        const fed = fakeFed();
        (fed.pending as ReturnType<typeof vi.fn>).mockResolvedValue([waiting()]);
        const close = await open(fed);
        await later();
        (document.querySelector('[data-modal-close]') as HTMLElement).click();
        await settle();
        expect(fed.cancelPending).toHaveBeenCalledWith('n1');
        expect(close).toHaveBeenCalledWith(null);
    });

    test('closing after this owner already said they match does not cancel the pairing (u140-02)', async () => {
        const fed = fakeFed();
        (fed.pending as ReturnType<typeof vi.fn>).mockResolvedValue([waiting()]);
        (fed.confirmPending as ReturnType<typeof vi.fn>).mockResolvedValue({ state: 'awaiting_initiator' });
        const close = await open(fed);
        await later();
        (document.querySelector('[data-fed-sas-match]') as HTMLElement).click();
        await settle();
        (document.querySelector('[data-modal-close]') as HTMLElement).click();
        await settle();
        expect(fed.cancelPending).not.toHaveBeenCalled();
        expect(close).toHaveBeenCalledWith(null);
    });
});
