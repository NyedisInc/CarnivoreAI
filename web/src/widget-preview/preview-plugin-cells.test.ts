/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';

vi.mock('./protocol', async (importOriginal) => ({ ...(await importOriginal<typeof import('./protocol')>()), PREVIEW_CLASSIC_SCRIPTS: [] }));

import { installPopoverPolyfill } from '../lib/popover-jsdom-polyfill';
import { PREVIEW_META_NAME, type PreviewConfig } from './protocol';

installPopoverPolyfill();

afterEach(() => {
  document.head.replaceChildren();
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});

async function bootPreview(config: PreviewConfig): Promise<void> {
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
  const meta = document.head.appendChild(document.createElement('meta'));
  meta.name = PREVIEW_META_NAME;
  meta.content = JSON.stringify(config);
  document.body.appendChild(document.createElement('div')).id = 'widget-preview';
  await import('./main');
}

test('a sample preview of TM Mark II draws the plugin cell, never unavailable', async () => {
  await bootPreview({ key: 'core.task-manager-mk2', zone: 'home', size: { name: 'm', w: 480, h: 360 }, mode: 'sample', theme: null });
  const root = document.getElementById('widget-preview')!;
  await vi.waitFor(() => expect(root.querySelector('.oc-wshell[data-widget="core.task-manager-mk2"], .oc-cell-unavailable')).not.toBeNull(), { timeout: 20_000 });
  expect(root.querySelector('.oc-cell-unavailable')).toBeNull();
  expect(root.querySelector('.oc-wshell[data-widget="core.task-manager-mk2"]')).not.toBeNull();
}, 30_000);
