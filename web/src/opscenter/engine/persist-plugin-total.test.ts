import { expect, it } from 'vitest';
import { metaFor } from './meta';

it('metaFor answers a placeholder for an unregistered plugin instance, never throws', () => {
  const meta = metaFor('zzplug.view:row:7' as never);
  expect(meta.id).toBe('zzplug.view:row:7');
  expect(meta.titleKey).toBe('opscenter.cell.plugin_pending.title');
});
