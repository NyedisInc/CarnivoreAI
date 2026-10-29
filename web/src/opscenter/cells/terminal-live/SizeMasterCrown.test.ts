/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import SizeMasterCrown from './SizeMasterCrown.svelte';

const authFetch = vi.fn();
vi.mock('../../api/auth.svelte', () => ({ authFetch: (...args: unknown[]) => authFetch(...args) }));

const MINE = 'tab-mine-000001';
const OTHER = 'tab-other-00002';
const mounted: ReturnType<typeof mount>[] = [];

beforeEach(() => {
  (globalThis as Record<string, unknown>).TerminalSizeMaster = { clientId: () => MINE };
});
afterEach(async () => {
  for (const component of mounted.splice(0)) await unmount(component);
  document.body.replaceChildren();
  delete (globalThis as Record<string, unknown>).TerminalSizeMaster;
  authFetch.mockReset();
});

function crown(sessionId: string): HTMLButtonElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(SizeMasterCrown, { target, props: { sessionId } }));
  flushSync();
  return target.querySelector('[data-tool="size-master"]') as HTMLButtonElement;
}

function announce(sessionId: string, master: string | null): void {
  window.dispatchEvent(new CustomEvent('cloude:size-master', { detail: { sessionId, master } }));
  flushSync();
}

test('no master, then this window, then another: none, master (lit), watcher', () => {
  const button = crown('s1');
  announce('s1', null);
  expect(button.dataset.sizeMaster).toBe('none');
  expect(button.getAttribute('aria-pressed')).toBe('false');
  announce('s1', MINE);
  expect(button.dataset.sizeMaster).toBe('master');
  expect(button.getAttribute('aria-pressed')).toBe('true');
  expect(button.getAttribute('aria-label')).toContain('size master');
  announce('s1', OTHER);
  expect(button.dataset.sizeMaster).toBe('watcher');
  expect(button.getAttribute('aria-label')).toContain('watcher');
});

test('an event for another session leaves this crown alone', () => {
  const button = crown('s2');
  announce('s2', null);
  announce('other-session', MINE);
  expect(button.dataset.sizeMaster).toBe('none');
});

test('a click claims with this tab id; a click while lit releases only its own claim', async () => {
  const button = crown('s3');
  announce('s3', null);
  authFetch.mockResolvedValueOnce({ session_id: 's3', master: MINE, master_attached: true });
  button.click();
  await vi.waitFor(() => expect(button.dataset.sizeMaster).toBe('master'));
  expect(authFetch).toHaveBeenLastCalledWith('/sessions/s3/size-master',
    { method: 'PUT', body: JSON.stringify({ client_id: MINE }) });

  authFetch.mockResolvedValueOnce({ session_id: 's3', master: null, master_attached: false });
  button.click();
  await vi.waitFor(() => expect(button.dataset.sizeMaster).toBe('none'));
  expect(authFetch).toHaveBeenLastCalledWith(`/sessions/s3/size-master?client_id=${MINE}`,
    { method: 'DELETE' });
});

test('a watcher click takes the crown from the other window', async () => {
  const button = crown('s4');
  announce('s4', OTHER);
  authFetch.mockResolvedValueOnce({ session_id: 's4', master: MINE, master_attached: true });
  button.click();
  await vi.waitFor(() => expect(button.dataset.sizeMaster).toBe('master'));
  expect(authFetch.mock.calls[0]?.[1]?.method).toBe('PUT');
});

test('a refused claim leaves the crown as the server last said', async () => {
  const button = crown('s5');
  announce('s5', OTHER);
  const error = vi.spyOn(console, 'error').mockImplementation(() => {});
  authFetch.mockRejectedValueOnce(new Error('unknown session'));
  button.click();
  await vi.waitFor(() => expect(error).toHaveBeenCalled());
  expect(button.dataset.sizeMaster).toBe('watcher');
  error.mockRestore();
});
