/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { Translate } from '../sessions/types';
import type { DiscoveredMac, FederationApi, PeerRow } from './federation-api';
import { createHostsAdapter, type HostRow } from './hosts-adapter';
import HostsScreen from './HostsScreen.svelte';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);

let mounted: Record<string, unknown> | null = null;
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

const local: HostRow = {
    key: 'local', label: 'hostb', local: true, ssh_target: null, ssh_port: null, socket: null, enabled: true,
    session_count: 3, probe_state: 'never', probe_detail: null, probed_at: null, tmux_path: null, tmux_version: null,
    login_path: null, agent_paths: null, login_shell: null, machine_id: null, remote_carnivore: null,
    created_at: '', updated_at: '',
};
const paired: PeerRow = { key: 'peer-1', label: 'hosta', peer_install_id: 'iid-1', fid: 'fid-hosta', initiator: true, state: 'connected', protocol: 1 };
const found: DiscoveredMac = { name: 'studio', host: 'studio.local.', port: 8000, addresses: [], fid: 'fid-studio', state: 'new', known_host: false };

const fed = (): FederationApi => ({
    discovered: vi.fn(async () => ({ discovered: [found], advertise: true, state: 'up', browse_state: 'up' })),
    settings: vi.fn(async () => ({ advertise: true, state: 'up' })),
    setAdvertise: vi.fn(async (advertise: boolean) => ({ advertise, state: 'up' })),
    peers: vi.fn(async () => [paired]),
    pair: vi.fn(),
    confirmPair: vi.fn(),
    pending: vi.fn(async () => []),
    confirmPending: vi.fn(),
    cancelPending: vi.fn(),
    unpair: vi.fn(),
    grants: vi.fn(async () => []),
    revoke: vi.fn(),
    beginCode: vi.fn(),
    rotate: vi.fn(),
} as unknown as FederationApi);

async function view(which: 'machines' | 'pairing'): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    const calls = fed();
    const fetcher = (async () => ({ status: 'ok', hosts: [local] })) as never;
    mounted = mount(HostsScreen, { target, props: { t, fed: calls, embedded: true, view: which, adapter: createHostsAdapter(t, fetcher, calls) } });
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    await tick();
    flushSync();
    return target;
}

const names = (root: HTMLElement): string[] => Array.from(root.querySelectorAll('.mgr-card__name')).map((el) => el.textContent?.trim() ?? '');

test('machines lists this computer and the paired one and has no rotate key', async () => {
    const root = await view('machines');
    expect(names(root)).toEqual(['hostb', 'hosta']);
    expect(root.querySelector('[data-host-rotate]')).toBeNull();
    expect(root.querySelector('[data-host-advertise]')).toBeNull();
    expect(root.querySelector('[data-mgr-install]')).not.toBeNull();
    expect(root.querySelector('.mgr-mark')?.textContent ?? '').not.toContain('this machine');
});

test('pairing lists the found computer and carries the advertise switch and the rotate key', async () => {
    const root = await view('pairing');
    expect(names(root)).toEqual(['studio']);
    expect(root.querySelector('[data-host-rotate]')).not.toBeNull();
    expect(root.querySelector('[data-host-advertise]')).not.toBeNull();
    expect(root.querySelector('[data-mgr-install]')).toBeNull();
});
