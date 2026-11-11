/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const net = vi.hoisted(() => ({ authFetch: vi.fn(), cplugEnabled: vi.fn() }));
vi.mock('../../sdk', async (importOriginal) => ({ ...(await importOriginal<typeof import('../../sdk')>()), ...net, cplugSetting: () => true }));

import VisitorsModal from './VisitorsModal.svelte';
import { followVisitors } from './visitors-feed.svelte';

let app: ReturnType<typeof mount> | null = null;
const settle = async (): Promise<void> => { for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); flushSync(); } };

beforeEach(() => {
  net.authFetch.mockResolvedValue({
    responses: [], present: [1], viewing: 2,
    visitors: [{ label: 'u1', number: 1, revision: 'r1', updated_at: 5, print: 'aaaa1111' }, { label: 'u2', number: 2, revision: 'r1', updated_at: 6, print: 'bbbb2222' }],
  });
});
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; vi.clearAllMocks(); });

describe('presence in the shared feed and the window', () => {
  it('marks the rows of present visitors and counts the rest', async () => {
    const follow = followVisitors('nav');
    await follow.refresh();
    expect(follow.feed.visitors.map((r) => [r.number, r.present])).toEqual([[1, true], [2, false]]);
    expect(follow.feed.viewing).toBe(2);
    follow.stop();
  });

  it('the window tags a present visitor and says how many more are viewing', async () => {
    app = mount(VisitorsModal, { target: document.body, props: { slug: 'nav', close: () => undefined } });
    await settle();
    expect(document.querySelector('[data-visitor-present="u1"]')).not.toBeNull();
    expect(document.querySelector('[data-visitor-present="u2"]')).toBeNull();
    expect(document.querySelector('[data-visitors-viewing]')?.textContent).toBe('2 more viewing now, no answers yet');
  });
});
