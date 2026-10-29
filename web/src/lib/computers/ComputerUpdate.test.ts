/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import ComputerUpdate from './ComputerUpdate.svelte';
import { setLocale, t } from '../i18n/index.svelte';

setLocale('en');

const mounted: ReturnType<typeof mount>[] = [];
afterEach(() => {
  mounted.splice(0).forEach((m) => unmount(m));
  document.body.innerHTML = '';
});

const STATUS = { attached: true, state: 'available', current_version: '1.17.0', latest_version: '1.17.1', percent: null, detail: null, auto_update: false };

async function render(answer: unknown, hostKey = 'peer-studio') {
  const calls: { path: string; method: string; body: unknown }[] = [];
  const fetcher = (async (path: string, init?: RequestInit) => {
    calls.push({ path, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : null });
    return structuredClone(answer);
  }) as never;
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(ComputerUpdate, { target, props: { hostKey, fetcher } }));
  await new Promise((r) => setTimeout(r, 0));
  flushSync();
  return { root: target, calls };
}
const el = (root: HTMLElement, name: string) => root.querySelector<HTMLElement>(`[data-cmp="${name}"]`);

describe('ComputerUpdate', () => {
  test('a paired computer shows its version, state, update now, and the switch OFF', async () => {
    const { root, calls } = await render({ status: 'ok', update: STATUS });
    expect(calls[0]?.path).toBe('/app-update/computer/peer-studio');
    expect(el(root, 'app-version')!.textContent).toContain('1.17.0');
    expect(el(root, 'update-state')!.textContent).toContain('update available: 1.17.1');
    expect(el(root, 'update-auto')!.getAttribute('aria-checked')).toBe('false');
    expect(el(root, 'update-now')).not.toBeNull();
    expect(root.textContent).not.toContain('?');
  });

  test('update now and the switch send only their own calls, never a feed', async () => {
    const { root, calls } = await render({ status: 'ok', update: STATUS });
    el(root, 'update-now')!.click();
    await new Promise((r) => setTimeout(r, 0));
    el(root, 'update-auto')!.click();
    await new Promise((r) => setTimeout(r, 0));
    expect(calls.slice(1).map((c) => [c.method, c.path, c.body])).toEqual([
      ['POST', '/app-update/computer/peer-studio/install', null],
      ['PUT', '/app-update/computer/peer-studio/auto-update', { enabled: true }],
    ]);
  });

  test('an old computer reads as plain text to update by hand, not an error', async () => {
    const { root } = await render({ status: 'unsupported' });
    const note = el(root, 'update-unsupported')!;
    expect(note.textContent).toContain(t('computers.update.unsupported'));
    expect(note.textContent).toContain('update it by hand once');
    expect(root.querySelector('[role="alert"]')).toBeNull();
    expect(el(root, 'update-now')).toBeNull();
  });

  test('this computer reads the local route', async () => {
    const { root, calls } = await render(STATUS, '');
    expect(calls[0]?.path).toBe('/app-update');
    expect(el(root, 'app-version')!.textContent).toContain('1.17.0');
  });
});
