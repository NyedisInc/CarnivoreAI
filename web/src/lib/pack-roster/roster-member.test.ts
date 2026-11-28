/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { setLocale } from '../i18n/index.svelte';
import { buildRoster, countsOf, type RosterComputer } from './roster-model';
import { countOnline, stateWord } from '../sidebar-shell/pack-stats';
import RosterCard from './RosterCard.svelte';
import PaneOverview from './PaneOverview.svelte';

setLocale('en');
const SNAP = { load: { cores: 8, load_1: 1, memory_percent: 10, disk_percent: 10 }, reserve: { level: 'in_use', cpu_pct: 50, mem_pct: 50 } };
const machine = (id: string, over: Record<string, unknown> = {}) => ({ install_id: id, label: id, is_self: id === 'me', is_master: id === 'alpha', paired: id === 'alpha' || id === 'dock',
  state: id === 'me' ? 'self' : 'connected', capabilities: [], specs: null, snapshot: null, roster_v1: null, ...over });
const entry = (id: string, transport: string) => ({ install_id: id, label: id, transport, state: 'connected', last_link_at: null, dial: { state: 'linked' } });
const LINK = { install_id: 'm3', state: 'linked', since: 1700000000, dialed_by: 'this', standing: true, on_demand: false };
const host = { key: 'box', label: 'box', local: false, ssh_target: 'alice@box', ssh_port: null, computer_install_id: null, probed_at: null, socket: 'cloude' };

function roster(opts: { mesh: boolean; alpha: 'connected' | 'disconnected'; roster_v1?: boolean | null }): RosterComputer[] {
  const m3 = machine('m3', { state: 'reported_connected', roster_v1: opts.roster_v1 ?? null });
  return buildRoster({
    view: { self: { install_id: 'me' }, computers: [entry('alpha', 'tls'), entry('dock', 'ssh')],
      ...(opts.mesh ? { mesh: { switch: 'on', links: [LINK] }, heard: { m3: { age_s: 4, at_ms: Date.now(), via: 'direct', app_version: '1.17.0' } } } : {}) } as never,
    machines: [machine('me'), machine('alpha', { state: opts.alpha, snapshot: SNAP }), m3, machine('dock', { snapshot: SNAP })] as never, hosts: [host] as never, peers: [],
  });
}

let cards: ReturnType<typeof mount>[] = [];
afterEach(() => { cards.forEach((c) => unmount(c)); cards = []; document.body.innerHTML = ''; });
function cardText(c: RosterComputer): string {
  const target = document.createElement('ul');
  document.body.append(target);
  cards.push(mount(RosterCard, { target, props: { c, onOpen: () => {}, nowMs: Date.now() } }));
  flushSync();
  return target.textContent ?? '';
}
const find = (list: RosterComputer[], id: string): RosterComputer => list.find((c) => c.id === id)!;

describe('another member on a member computer', () => {
  test.each([['up', 'connected'], ['down', 'disconnected']] as const)('mesh on, alpha %s: version from the status card, linked directly, figures line, in pack only', (_n, alpha) => {
    const list = roster({ mesh: true, alpha });
    const text = cardText(find(list, 'm3'));
    expect(text).toContain('carnivore 1.17.0');
    expect(text).toContain('linked directly');
    expect(text).toContain('cpu, memory and disk show on the alpha');
    expect(text).not.toContain('no carnivore on it');
    expect(text).not.toContain('over ssh');
    expect(countsOf(list)).toMatchObject({ all: 5, inpack: 4, overssh: 2, sshonly: 1, older: 1 });
  });
  test('mesh off: no version, no transport claim, the figures line stays, still in pack and not over ssh or older', () => {
    const list = roster({ mesh: false, alpha: 'connected' });
    const text = cardText(find(list, 'm3'));
    expect(text).not.toContain('no carnivore on it');
    expect(text).not.toContain('over ssh');
    expect(text).not.toContain('linked directly');
    expect(text).toContain('cpu, memory and disk show on the alpha');
    expect(countsOf(list)).toMatchObject({ inpack: 4, overssh: 2, older: 1 });
  });
  test('older only when measured old: roster_v1 false counts, null does not', () => {
    expect(countsOf(roster({ mesh: false, alpha: 'connected', roster_v1: false })).older).toBe(2);
    expect(countsOf(roster({ mesh: false, alpha: 'connected', roster_v1: null })).older).toBe(1);
  });
  test('the words stay true where they are true: a real ssh-only host and an entry that says ssh', () => {
    const list = roster({ mesh: true, alpha: 'connected' });
    expect(cardText(find(list, 'host:box'))).toContain('no carnivore on it');
    expect(cardText(find(list, 'dock'))).toContain('over ssh');
    expect(cardText(find(list, 'alpha'))).not.toContain('cpu, memory and disk show on the alpha');
  });
});

describe('mesh off: the card says what the alpha reported', () => {
  test('connected to alpha, no last seen never, no not linked', () => {
    const text = cardText(find(roster({ mesh: false, alpha: 'connected' }), 'm3'));
    expect(text).toContain('connected to alpha');
    expect(text).not.toContain('not linked');
    expect(text).not.toContain('last seen never');
  });
  test('the alpha down: the relayed word drops to unknown', () => {
    const text = cardText(find(roster({ mesh: false, alpha: 'disconnected' }), 'm3'));
    expect(text).not.toContain('connected to alpha');
    expect(text).toContain('unknown');
  });
  test('the overview pane last seen row never reads never for that member', () => {
    const target = document.createElement('div');
    document.body.append(target);
    cards.push(mount(PaneOverview, { target, props: { c: find(roster({ mesh: false, alpha: 'connected' }), 'm3'), onWork: () => {}, nowMs: Date.now() } }));
    flushSync();
    const dts = [...target.querySelectorAll('dt')];
    const row = dts.find((d) => d.textContent === 'last seen')!.nextElementSibling!.textContent;
    expect(row).toBe('-');
    expect(row).not.toContain('never');
  });
});

describe('the work tab reads the direct member link', () => {
  const link = (state: string) => ({ ...LINK, state }) as never;
  const alphaDown = [machine('me'), machine('alpha', { state: 'disconnected' }), machine('m3', { state: 'unknown' })] as never[];
  test('alpha down, direct link linked: the word is linked and it counts online; without the link it reads unknown and does not', () => {
    expect(stateWord('unknown', link('linked'), false)).toBe('linked');
    expect(countOnline(alphaDown, (m) => (m.install_id === 'm3' ? link('linked') : null))).toBe(2);
    expect(countOnline(alphaDown, () => null)).toBe(1);
  });
  test('alpha up and mesh off: a reported connected computer still counts, as today', () => {
    const up = [machine('me'), machine('alpha'), machine('m3', { state: 'reported_connected' })] as never[];
    expect(countOnline(up, () => null)).toBe(3);
  });
});
