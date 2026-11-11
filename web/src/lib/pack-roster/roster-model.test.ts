import { describe, expect, test } from 'vitest';
import { buildRoster, countsOf, inFilter } from './roster-model';

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
