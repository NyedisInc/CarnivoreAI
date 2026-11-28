import { describe, expect, test } from 'vitest';
import { buildRoster, countsOf, inFilter, lookFlags, needsLook, sortRoster, type RosterComputer } from './roster-model';

const machine = (id: string, over: Record<string, unknown> = {}) => ({ install_id: id, label: id, is_self: id === 'me', is_master: id === 'alpha', paired: id === 'alpha',
  state: id === 'me' ? 'self' : 'connected', capabilities: [], specs: null, snapshot: null, roster_v1: null, ...over });
const link = (state: string) => ({ install_id: 'm3', state, since: 1700000000, dialed_by: 'this', standing: true, on_demand: false });

function roster(o: { linkState: string; alpha?: string; m3State?: string }): RosterComputer[] {
  return buildRoster({
    view: { self: { install_id: 'me' }, computers: [{ install_id: 'alpha', label: 'alpha', transport: 'tls', state: 'connected', last_link_at: null, dial: { state: 'linked' } }],
      mesh: { switch: 'on', links: [link(o.linkState)] }, heard: { m3: { age_s: 4, at_ms: Date.now(), via: 'direct', app_version: '1.17.0' } } } as never,
    machines: [machine('me'), machine('alpha', { state: o.alpha ?? 'connected' }), machine('m3', { state: o.m3State ?? 'reported_connected' })] as never, hosts: [], peers: [],
  });
}
const m3 = (list: RosterComputer[]): RosterComputer => list.find((c) => c.id === 'm3')!;

describe('another member, the alpha up and reporting it connected, direct link unreachable', () => {
  const list = roster({ linkState: 'unreachable' });
  test('no unreach flag, not needing a look, not in the filter, not counted', () => {
    expect(lookFlags(m3(list)).unreach).toBe(false);
    expect(needsLook(m3(list))).toBe(false);
    expect(inFilter(m3(list), 'unreach')).toBe(false);
    expect(countsOf(list).unreach).toBe(0);
  });
  test('it does not sort ahead of the alpha', () => {
    expect(sortRoster(list, 'status').map((c) => c.id).indexOf('alpha')).toBeLessThan(sortRoster(list, 'status').map((c) => c.id).indexOf('m3'));
  });
});

describe('the alpha not vouching', () => {
  test('the alpha down: unreach', () => expect(lookFlags(m3(roster({ linkState: 'unreachable', alpha: 'disconnected' }))).unreach).toBe(true));
  test('the alpha reporting it disconnected: unreach', () => expect(lookFlags(m3(roster({ linkState: 'unreachable', m3State: 'reported_disconnected' }))).unreach).toBe(true));
});

describe('faults on the direct path keep their flags', () => {
  test.each(['refused', 'local_network_blocked', 'excluded'])('%s: unreach', (state) => expect(lookFlags(m3(roster({ linkState: state }))).unreach).toBe(true));
  test('cert_mismatch: identity', () => expect(lookFlags(m3(roster({ linkState: 'cert_mismatch' }))).identity).toBe(true));
});

test('a star-paired computer (member false) with dial unreachable still flags', () => {
  const list = buildRoster({
    view: { self: { install_id: 'me' }, computers: [{ install_id: 'm3', label: 'm3', transport: 'tls', state: 'connected', last_link_at: null, dial: { state: 'unreachable' } }] } as never,
    machines: [machine('me', { is_master: true }), machine('m3', { state: 'reported_connected', paired: true })] as never, hosts: [], peers: [],
  });
  expect(m3(list).member).toBe(false);
  expect(lookFlags(m3(list)).unreach).toBe(true);
});
