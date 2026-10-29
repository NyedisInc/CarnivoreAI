/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import TabStrip from './TabStrip.svelte';
import { manifestById } from '../widgets/core-manifests';

let app: ReturnType<typeof mount> | null = null;

afterEach(async () => {
  if (app) await unmount(app);
  app = null;
  document.body.replaceChildren();
});

function draw(items: { id: string; name: string; family: string | null; glyph?: string; badge?: { manifest: NonNullable<ReturnType<typeof manifestById>>; global?: boolean } }[]): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  app = mount(TabStrip, { target, props: { items, active: items[0]!.id, onSelect: () => {} } });
  flushSync();
  return target;
}

test('a widget item draws the badge host and the globe; a session item draws neither', () => {
  const tasksAll = manifestById('core.tasks-all')!;
  const root = draw([
    { id: 'widget:core.tasks-all', name: 'tasks', family: 'browser', glyph: 'tasks', badge: { manifest: tasksAll, global: true } },
    { id: 'terminal:ses_a', name: 'a', family: 'shell' },
  ]);
  const widget = root.querySelector('[data-tab="widget:core.tasks-all"]')!.closest('.oc-tabwrap')!;
  const session = root.querySelector('[data-tab="terminal:ses_a"]')!.closest('.oc-tabwrap')!;
  expect(widget.querySelector('.oc-tab-badgehost [data-widget-globe]')).not.toBeNull();
  expect(session.querySelector('.oc-tab-badgehost')).toBeNull();
});
