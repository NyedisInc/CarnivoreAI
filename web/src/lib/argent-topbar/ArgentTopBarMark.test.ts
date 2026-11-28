/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import ArgentTopBarMark from './ArgentTopBarMark.svelte';

let cmp: ReturnType<typeof mount> | null = null;
afterEach(() => { if (cmp) unmount(cmp); cmp = null; document.body.innerHTML = ''; });

async function draw(feature_on: boolean, state: string, fail = false, tether = true) {
  const fetcher = vi.fn(async () => { if (fail) throw new Error('x'); return { feature_on, settings: { enabled: tether }, login: { state, display_name: 'Alice' } }; });
  cmp = mount(ArgentTopBarMark, { target: document.body, props: { fetcher: fetcher as never } });
  await new Promise((r) => setTimeout(r, 0));
  flushSync();
  return document.querySelector<HTMLButtonElement>('[data-argent-topbar]');
}

test('logged in: drawn with its spoken name', async () => {
  const b = await draw(true, 'logged_in');
  expect(b?.getAttribute('aria-label')).toBe('connected to argent as Alice');
});
test('tether on: normal look', async () => {
  expect((await draw(true, 'logged_in'))?.dataset.tether).toBe('on');
});
test('tether off: shown, muted, says so', async () => {
  const b = await draw(true, 'logged_in', false, false);
  expect(b?.dataset.tether).toBe('off');
  expect(b?.getAttribute('aria-label')).toBe('connected to argent as Alice, tethering off');
});
test('login soon: still drawn', async () => { expect(await draw(true, 'login_soon')).not.toBeNull(); });
test.each(['logged_out', 'login_expired', 'pending'])('%s: nothing', async (s) => { expect(await draw(true, s)).toBeNull(); });
test('feature off: nothing', async () => { expect(await draw(false, 'logged_in')).toBeNull(); });
test('failed read: nothing', async () => { expect(await draw(true, 'logged_in', true)).toBeNull(); });
