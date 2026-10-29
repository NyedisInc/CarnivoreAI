import { expect, test } from 'vitest';
import { filterAwakeSleeping } from './bucketing';

const rows = [
  { name: 'awake', agent_family: 'claude' },
  { name: 'asleep', agent_family: 'claude', asleep: true },
  { name: 'closed', agent_family: 'claude', closed: true },
  { name: 'arch', agent_family: 'claude', archived: true },
];
const names = (open: boolean, sleeping: boolean): string[] => filterAwakeSleeping(rows as never, open, sleeping).map((r) => r.name);

test('both on lists awake and sleeping', () => expect(names(true, true)).toEqual(['awake', 'asleep', 'closed', 'arch']));
test('open only lists the awake ones', () => expect(names(true, false)).toEqual(['awake', 'closed', 'arch']));
test('sleeping only lists the asleep ones', () => expect(names(false, true)).toEqual(['asleep', 'closed', 'arch']));
test('both off lists no awake or sleeping session', () => expect(names(false, false)).toEqual(['closed', 'arch']));
