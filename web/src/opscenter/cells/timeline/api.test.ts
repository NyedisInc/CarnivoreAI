import { beforeEach, describe, expect, test, vi } from 'vitest';

const auth = vi.hoisted(() => ({ authFetch: vi.fn() }));
vi.mock('../../api/auth.svelte', async (actual) => ({ ...(await actual<typeof import('../../api/auth.svelte')>()), ...auth }));

import { openRestorePoint, restorePointPath } from './api';

beforeEach(() => {
  auth.authFetch.mockReset();
  auth.authFetch.mockResolvedValue({ transcript_status: 'written', session: { status: 'started', detail: '' } });
});

describe('open a copy', () => {
  test('the path is the save plugin route addressed by conversation, each segment encoded', () => {
    expect(restorePointPath('conv b', 'p/1')).toBe('/cplugs/save/conversations/conv%20b/points/p%2F1/restore');
  });

  test('it posts to that path with the save plugin body', async () => {
    await openRestorePoint('conv-b', '20261010T112500Z-kill');
    expect(auth.authFetch).toHaveBeenCalledTimes(1);
    const [path, init] = auth.authFetch.mock.calls[0]!;
    expect(path).toBe('/cplugs/save/conversations/conv-b/points/20261010T112500Z-kill/restore');
    expect(init).toMatchObject({ method: 'POST', body: '{}' });
  });
});
