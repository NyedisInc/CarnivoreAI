import { describe, expect, test } from 'vitest';
import { buildRoster, countsOf, inFilter, moveInOrder, orderEditable, situationOf, strandedCount, successorOrder, takeoverReasonKey } from './roster-model';

const machine = (id: string, over: Record<string, unknown> = {}) => ({ install_id: id, label: id, is_self: id === 'me', is_master: id === 'me', paired: id !== 'me', ...over });
const entry = (id: string) => ({ install_id: id, label: id, transport: 'ssh', state: 'connected', last_link_at: null, dial: { state: 'linked' } });

describe('roster kind', () => {
  const build = (machines: unknown[]) => buildRoster({
    view: { self: { install_id: 'me' }, computers: [entry('dock')] } as never,
    machines: machines as never, hosts: [], peers: [],
  });
  test('a paired ssh computer in the snapshot is in the pack, counted, and still in the older filter', () => {
    const list = build([machine('me'), machine('dock')]);
    const dock = list.find((c) => c.id === 'dock')!;
    expect(dock.kind).toBe('pack');
    expect(inFilter(dock, 'inpack')).toBe(true);
    expect(inFilter(dock, 'older')).toBe(true);
    expect(countsOf(list).older).toBe(1);
  });
  test('an ssh link the snapshot does not list keeps the paired-older kind', () => {
    const dock = build([machine('me')]).find((c) => c.id === 'dock')!;
    expect(dock.kind).toBe('paired-older');
    expect(inFilter(dock, 'older')).toBe(true);
  });
});

describe('reconnect model', () => {
  const m = (id: string, over: Record<string, unknown> = {}) => machine(id, { roster_v1: true, rank: null, eligible: false, link_path: id === 'me' ? null : 'direct', age_seconds: 5, ...over });
  const view = (machines: unknown[], over: Record<string, unknown> = {}) => ({ master_install_id: 'me', self_install_id: 'me', machines, interim: false, takeover_available: { ok: true, reason: 'ok' }, ...over }) as never;
  const roster = (machines: unknown[]) => buildRoster({ view: { self: { install_id: 'me' }, computers: machines.map((x) => entry((x as { install_id: string }).install_id)) } as never, machines: machines as never, hosts: [], peers: [] });

  test('a relayed link badges, a computer without the roster capability needs an update and the stranded count says how many', () => {
    const list = roster([m('me', { rank: 0 }), m('dock', { rank: 1, link_path: 'relay' }), m('old', { rank: 2, roster_v1: false })]);
    expect(list.find((c) => c.id === 'dock')).toMatchObject({ viaRelay: true, needsUpdate: false });
    expect(list.find((c) => c.id === 'old')).toMatchObject({ viaRelay: false, needsUpdate: true });
    expect(list.find((c) => c.id === 'me')?.needsUpdate).toBe(false);
    expect(strandedCount(list)).toBe(1);
    expect(roster([m('me'), machine('dock')]).every((c) => !c.needsUpdate && !c.viaRelay)).toBe(true);
  });

  test('the order reads in rank order, moves one place and stops at the ends; only main outside an interim edits it', () => {
    const list = roster([m('me', { rank: 2 }), m('a', { rank: 0 }), m('b', { rank: 1 })]);
    expect(successorOrder(list).map((c) => c.id)).toEqual(['a', 'b', 'me']);
    expect(moveInOrder(['a', 'b', 'me'], 'me', -1)).toEqual(['a', 'me', 'b']);
    expect(moveInOrder(['a', 'b', 'me'], 'a', -1)).toEqual(['a', 'b', 'me']);
    expect(moveInOrder(['a', 'b', 'me'], 'me', 1)).toEqual(['a', 'b', 'me']);
    expect(orderEditable(view([m('me', { is_master: true })]))).toBe(true);
    expect(orderEditable(view([m('me', { is_master: false }), m('a', { is_master: true })]))).toBe(false);
    expect(orderEditable(view([m('me', { is_master: true })], { interim: true }))).toBe(false);
    expect(orderEditable(null)).toBe(false);
  });

  test('the takeover reason is the server\'s and the situation names looking, main offline and main now', () => {
    for (const reason of ['off', 'no_eligible', 'alpha_not_updated', 'ok']) expect(takeoverReasonKey(view([], { takeover_available: { ok: reason === 'ok', reason } }))).toBe(reason);
    expect(takeoverReasonKey(null)).toBe('unknown');
    const member = (path: string, age: number | null) => view([m('me', { is_master: false }), m('a', { is_master: true, link_path: path, age_seconds: age })], { master_install_id: 'a' });
    expect(situationOf(member('direct', 3))).toBe('normal');
    expect(situationOf(member('relay', 3))).toBe('normal');
    expect(situationOf(member('none', 40))).toBe('looking');
    expect(situationOf(member('none', null))).toBe('looking');
    expect(situationOf(member('none', 900))).toBe('main_offline');
    expect(situationOf(view([m('me', { is_master: true })], { interim: true }))).toBe('main_now');
    expect(situationOf(view([m('me', { is_master: true })]))).toBe('normal');
    expect(situationOf(null)).toBe('normal');
  });
});
