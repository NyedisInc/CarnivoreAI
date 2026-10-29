import { afterEach, expect, test } from 'vitest';
import type { Automation } from './api';
import { sessionChoices } from './sessions-view';

afterEach(() => {
  delete (globalThis as { SessionLabel?: unknown }).SessionLabel;
});

const resolver = { resolve: (row: { label: string | null; name: string | null }) => row.label || (row.name ?? '').replace(/^(cloude|carnivore)_/, '') };
const rec = (uuid: string, tmux: string, title: string | null, lifecycle: string, asleep = false) =>
  ({ session_uuid: uuid, tmux_name: tmux, title, lifecycle, asleep, project_id: 1 });
const msg = (uuid: string): Automation =>
  ({ automation_id: 'a1', name: 'nightly', enabled: true, project_id: null, target: { kind: 'session_message', session_uuid: uuid }, next_fire_at: null, last_run: null }) as unknown as Automation;

test('labels come from the drawer resolver and stopped twins vanish', () => {
  (globalThis as { SessionLabel?: unknown }).SessionLabel = resolver;
  const records = [
    rec('u-live', 'carnivore_Orchard-3', 'Orchard Deploy', 'running'),
    rec('u-old1', 'carnivore_Orchard-3', 'Orchard', 'stopped'),
    rec('u-old2', 'carnivore_Orchard-3', 'Orchard-Deploy', 'stopped'),
    rec('u-nap', 'cloude_AdBoard', null, 'stopped', true),
  ];
  const choices = sessionChoices(records, [msg('u-live')]);
  expect(choices.map((c) => c.label)).toEqual(['Orchard Deploy', 'AdBoard']);

});
