import { expect, test } from 'vitest';
import { PACK_TABS, packTabOf } from './pack-hash';

test('#pack/ssh, #ssh and the old machines slug open computers with the ssh landing', () => {
  for (const hash of ['#pack/ssh', '#ssh', '#settings/hosts/machines']) expect(packTabOf(hash)).toEqual({ tab: 'computers', ssh: true });
  expect(packTabOf('#pack/work')).toEqual({ tab: 'work', ssh: false });
  expect(PACK_TABS).not.toContain('ssh');
});
