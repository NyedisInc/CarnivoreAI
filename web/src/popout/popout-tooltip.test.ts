/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';

vi.mock('./live', async (real) => ({ ...(await real<object>()), bootPopoutLive: () => {} }));
vi.mock('../lib/listing-push/boot', async (real) => ({ ...(await real<object>()), bootListingPush: () => {} }));
vi.mock('../lib/mount', async (real) => ({ ...(await real<object>()), mountPanel: () => null }));

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = '';
});

test('booting the pop-out installs the shared tooltip: a cut-off title shows its full text after the delay', async () => {
  vi.useFakeTimers();
  const { SHOW_DELAY_MS } = await import('../lib/tooltip/tooltip');
  await import('./main');
  const title = document.createElement('span');
  title.textContent = 'a long title the pop-out cuts off';
  title.setAttribute('data-tooltip', 'a long title the pop-out cuts off, in full');
  document.body.appendChild(title);
  title.dispatchEvent(new MouseEvent('pointerover', { bubbles: true }));
  vi.advanceTimersByTime(SHOW_DELAY_MS + 10);
  const bubble = document.querySelector<HTMLElement>('.cc-tooltip');
  expect(bubble, 'the one tooltip bubble exists in the pop-out').not.toBeNull();
  expect(bubble?.hidden).toBe(false);
  expect(bubble?.textContent).toBe('a long title the pop-out cuts off, in full');
});
