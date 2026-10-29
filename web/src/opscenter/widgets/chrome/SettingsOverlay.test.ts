/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import SettingsOverlay from './SettingsOverlay.svelte';
import { configureSheet, openConfigure } from './configure.svelte';
import { createItemSettingsController } from '../../../lib/item-settings/item-settings-controller.svelte';
import { memoryFetcher } from '../../../lib/item-settings/memory-fetcher';
import type { Fetcher } from '../../../lib/item-settings/api';
import { CORE_MANIFESTS } from '../core-manifests';
import { installPopoverPolyfill } from '../../../lib/popover-jsdom-polyfill';
import { t } from '../../../lib/i18n/index.svelte';

installPopoverPolyfill();

const ID = 'core.activity-log';
let app: ReturnType<typeof mount> | null = null;

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

async function settle(): Promise<void> {
  for (let i = 0; i < 4; i += 1) await Promise.resolve();
  await tick();
  flushSync();
}

async function open(): Promise<unknown[]> {
  const memory = memoryFetcher({ [ID]: CORE_MANIFESTS[ID]!.settings! });
  const sent: unknown[] = [];
  const fetcher = (async (path: string, init?: RequestInit) => {
    if (init?.method === 'PATCH') sent.push(JSON.parse(String(init.body)));
    return memory(path, init);
  }) as Fetcher;
  const controller = createItemSettingsController('widget', ID, t, fetcher, async () => {});
  const anchor = document.createElement('section');
  document.body.append(anchor);
  openConfigure('activity-log');
  app = mount(SettingsOverlay, { target: document.body, props: { widgetId: ID, title: 'activity log', anchor, hasSchema: true, controller } });
  await settle();
  return sent;
}

describe('the settings overlay', () => {
  test('draws the schema under its plain heading, words not keys, with the hint', async () => {
    await open();
    const overlay = document.querySelector<HTMLElement>(`[data-settings-overlay="${ID}"]`)!;
    expect(overlay.getAttribute('role')).toBe('dialog');
    expect(overlay.querySelector('.sf__group-head')?.textContent).toBe('what to show');
    expect(overlay.querySelector('[data-setting="showSystem"] .sf__label')?.textContent).toBe('show system lines');
    expect(overlay.querySelector('[data-setting="showSystem"] .sf__hint')?.textContent).toContain('live channel');
    expect(overlay.textContent).not.toContain('showSystem');
  });

  test('a toggle applies at once; reset clears every choice in one write; done closes', async () => {
    const sent = await open();
    const reset = document.querySelector<HTMLButtonElement>('[data-configure-reset]')!;
    expect(reset.disabled).toBe(true);
    document.querySelector<HTMLElement>('[data-setting="showSystem"] [role="switch"]')!.click();
    await settle();
    expect(sent).toEqual([{ values: { showSystem: false }, expected_revision: 0 }]);
    expect(document.querySelector('[data-setting="showSystem"] [role="switch"]')?.getAttribute('aria-checked')).toBe('false');
    expect(reset.disabled).toBe(false);
    reset.click();
    await settle();
    expect(sent[1]).toEqual({ values: { showSystem: null }, expected_revision: 1 });
    expect(document.querySelector('[data-setting="showSystem"] [role="switch"]')?.getAttribute('aria-checked')).toBe('true');
    expect(configureSheet.slot).toBe('activity-log');
    document.querySelector<HTMLElement>('[data-configure-done]')!.click();
    expect(configureSheet.slot).toBeNull();
    expect(sent).toHaveLength(2);
  });
});
