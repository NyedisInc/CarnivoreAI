/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import { ApiError } from '../../opscenter/api/auth.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { Translate } from '../sessions/types';
import type { DiscoveredMac, FederationApi, GrantRow, PairPending, PeerRow, PendingPair } from './federation-api';
import { errorCode } from './federation-api';
import { createHostsAdapter, machineKey, type HostRow } from './hosts-adapter';
import HostsScreen from './HostsScreen.svelte';
import PairModal from './PairModal.svelte';
import ShowCodeModal from './ShowCodeModal.svelte';
import PeerDetail from './PeerDetail.svelte';

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

const host = (over: Partial<HostRow>): HostRow => ({
    key: 'local', label: 'hostb', local: true, ssh_target: null, ssh_port: null, socket: null, enabled: true,
    session_count: 0, probe_state: 'never', probe_detail: null, probed_at: null, tmux_path: null, tmux_version: null,
    login_path: null, agent_paths: null, login_shell: null, machine_id: null, remote_carnivore: null,
    created_at: '', updated_at: '', ...over,
});
const peer = (over: Partial<PeerRow>): PeerRow => ({
    key: 'peer-1', label: 'hosta', peer_install_id: 'iid-1', fid: 'fid-hosta', initiator: true, state: 'connected', protocol: 1, ...over,
});
const pending = (over: Partial<PairPending>): PairPending => ({
    pending: true, nonce: 'nn', sas: '12345 67890', label: 'hosta', fid: 'fid-hosta', proof: 'typed', peer_owner_confirms: true,
    expires_in: 300, ...over,
});
const seen = (over: Partial<DiscoveredMac>): DiscoveredMac => ({
    name: 'studio', host: 'studio.local.', port: 8000, addresses: [], fid: 'fid-studio', state: 'new', known_host: false, ...over,
});
const grant = (over: Partial<GrantRow>): GrantRow => ({
    grant_id: 'g1', peer_install_id: 'iid-1', fid: 'fid-hosta', label: 'hosta', scopes: ['sessions'], created_at: '',
    last_seen_at: null, revoked_at: null, ...over,
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

async function screen(hosts: HostRow[], fed: FederationApi): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    const fetcher = (async () => ({ status: 'ok', hosts })) as never;
    mounted = mount(HostsScreen, { target, props: { t, fed, embedded: true, adapter: createHostsAdapter(t, fetcher, fed) } });
    await settle();
    return target;
}

describe('link states, in words (F19)', () => {
    const cases: Array<[string, string]> = [
        ['connected', 'connected'],
        ['disconnected', 'disconnected'],
        ['incompatible', 'incompatible'],
        ['unpaired', 'unpaired'],
        ['identity_changed', 'identity changed'],
        ['connecting', 'connecting'],
    ];
    test.each(cases)('%s prints %s', async (state, word) => {
        const root = await screen([host({}), host({ key: 'peer-1', label: 'hosta', local: false, ssh_target: 'hosta' })], fakeFed({ peers: [peer({ state })] }));
        const badge = root.querySelector(`[data-peer-state="${state}"]`);
        expect(badge?.textContent?.trim()).toBe(word);
    });
});

describe('machine grouping (F7)', () => {
    test('an ssh host and a peer of one Mac share one heading; another Mac gets its own', async () => {
        const hosts = [
            host({}),
            host({ key: 'ssh-1', label: 'hosta', local: false, ssh_target: 'acme@hosta.local' }),
            host({ key: 'peer-1', label: 'hosta', local: false, ssh_target: 'hosta.example.ts.net' }),
        ];
        const root = await screen(hosts, fakeFed({ peers: [peer({})] }));
        const heads = [...root.querySelectorAll('[data-host-group-head]')].map((h) => h.getAttribute('data-host-group-head'));
        expect(heads).toEqual(['m:local', 'm:hosta']);
        const hosta = root.querySelector('[data-group="m:hosta"]')!;
        expect(hosta.querySelectorAll('[data-item-id]').length).toBe(2);
        expect(hosta.querySelector('.oc-page__group-meta')?.textContent).toContain('ssh host + paired computer');
    });
    test('machineKey drops user and domain but keeps an address whole', () => {
        expect(machineKey('acme@Hosta.local')).toBe('hosta');
        expect(machineKey('203.0.113.11')).toBe('203.0.113.11');
    });
});

describe('discovered list', () => {
    test('a sighting lists under its own heading and opens a pair button; a paired one is hidden', async () => {
        const fed = fakeFed({ peers: [peer({})], found: [seen({}), seen({ name: 'hosta', fid: 'fid-hosta' })] });
        const root = await screen([host({}), host({ key: 'peer-1', label: 'hosta', local: false, ssh_target: 'hosta' })], fed);
        const group = root.querySelector('[data-group="found"]')!;
        expect(group.querySelectorAll('[data-item-id]').length).toBe(1);
        expect(group.textContent).toContain('studio');
        expect(group.textContent).toContain('first contact: a code is needed');
        (group.querySelector('.mgr-card__open') as HTMLElement).click();
        await settle();
        expect(root.querySelector('[data-found-pair]')).not.toBeNull();
    });
});

describe('advertise switch (F15)', () => {
    test('pressing it sends the other value and shows what the server answered', async () => {
        const fed = fakeFed();
        const root = await screen([host({})], fed);
        const sw = root.querySelector('[data-host-advertise]') as HTMLElement;
        expect(sw.getAttribute('aria-checked')).toBe('true');
        sw.click();
        await settle();
        expect(fed.setAdvertise).toHaveBeenCalledWith(false);
        expect(root.querySelector('[data-host-advertise]')?.getAttribute('aria-checked')).toBe('false');
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
        expect(document.querySelector('[data-fed-sas-differ]')?.className).toContain('modal-btn-danger');
        await press('[data-fed-sas-differ]');
        expect(fed.confirmPair).toHaveBeenCalledWith('nn', false);
        expect(close).toHaveBeenCalledWith(null);
    });

    test('closing the dialog while a code is pending counts as a mismatch', async () => {
        const fed = fakeFed();
        const close = await mountPair(fed, seen({}));
        await press('[data-fed-pair-confirm]');
        await press('.modal-close');
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
        await type('modal-pair-target', 'hosta.example.ts.net');
        await press('[data-fed-pair-confirm]');
        expect(document.querySelector('[data-fed-pair-reason]')?.textContent).toBe('first contact');
        expect(close).not.toHaveBeenCalled();
        await type('modal-pair-nonce', 'nn');
        await type('modal-pair-code', 'CODE');
        await press('[data-fed-pair-confirm]');
        expect(fed.pair).toHaveBeenLastCalledWith({ ssh_target: 'hosta.example.ts.net', typed_nonce: 'nn', typed_code: 'CODE' });
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

describe('grants, revoke and unpair (F16)', () => {
    async function detail(fed: FederationApi): Promise<void> {
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PeerDetail, { target, props: { peer: peer({}), fed, t, onChanged: () => undefined, onOpen: () => undefined } });
        await settle();
    }
    const go = async (): Promise<void> => {
        (document.querySelector('[data-fed-confirm-go]') as HTMLElement).click();
        await settle();
    };

    test('lists only this peer\'s grants; revoke asks first, then revokes that grant', async () => {
        const fed = fakeFed({ grants: [grant({}), grant({ grant_id: 'other', peer_install_id: 'iid-2' })] });
        await detail(fed);
        expect(document.querySelectorAll('[data-grant-id]').length).toBe(1);
        (document.querySelector('[data-peer-revoke]') as HTMLElement).click();
        await settle();
        expect(fed.revoke).not.toHaveBeenCalled();
        expect(document.querySelector('[data-fed-confirm-go]')?.className).toContain('modal-btn-danger');
        await go();
        expect(fed.revoke).toHaveBeenCalledWith('g1');
    });

    test('unpair asks first (danger), then calls the one route', async () => {
        const fed = fakeFed();
        await detail(fed);
        (document.querySelector('[data-peer-unpair]') as HTMLElement).click();
        await settle();
        expect(fed.unpair).not.toHaveBeenCalled();
        await go();
        expect(fed.unpair).toHaveBeenCalledWith('peer-1');
    });
});

describe('rotate key', () => {
    test('needs the confirm; cancel calls nothing', async () => {
        const fed = fakeFed();
        const root = await screen([host({})], fed);
        (root.querySelector('[data-host-rotate]') as HTMLElement).click();
        await settle();
        (document.querySelector('[data-fed-confirm-cancel]') as HTMLElement).click();
        await settle();
        expect(fed.rotate).not.toHaveBeenCalled();
        (root.querySelector('[data-host-rotate]') as HTMLElement).click();
        await settle();
        (document.querySelector('[data-fed-confirm-go]') as HTMLElement).click();
        await settle();
        expect(fed.rotate).toHaveBeenCalledTimes(1);
        expect(root.querySelector('[data-host-tool-notice]')?.textContent).toContain('new key new');
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
        expect(document.querySelector('[data-fed-sas-differ]')?.className).toContain('modal-btn-danger');
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
});
