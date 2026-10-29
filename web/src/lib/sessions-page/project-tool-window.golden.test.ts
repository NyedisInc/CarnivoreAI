/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import ProjectToolWindow from './ProjectToolWindow.svelte';
import FakePanel from './ProjectTools.fake-panel.svelte';
import { setLocale, t } from '../i18n/index.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import { registerProjectPanel, resetProjectPanels } from '../../cplugs/sdk/project-panels';
import { recorded, reframed, snapshot } from '../dialog-frame/goldens';

const FRAME = { addClasses: ['oc-anchored'] };

installPopoverPolyfill();
setLocale('en');

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  resetProjectPanels();
  document.body.replaceChildren();
});

test('the window renders its recorded markup', () => {
  registerProjectPanel({ id: 'crate.project', labelKey: 'cplug.crate.project.group', component: FakePanel as never, enabled: () => true });
  app = mount(ProjectToolWindow, { target: document.body, props: { tool: { kind: 'panel', panelId: 'crate.project' }, project: { id: 18, name: 'acme' }, t, onClose: vi.fn() } });
  flushSync();
  const now = snapshot(document.querySelector('[data-project-tool]')!);
  expect(now).toBe(reframed(recorded('project-tool-window', now), FRAME));
});
