import { afterEach, beforeEach, expect, test, vi } from 'vitest';

vi.mock('../../opscenter/api/auth.svelte', () => ({
  API_BASE: '/api/v1',
  auth: { state: 'signed-out', notice: '' },
  authFetchBlob: vi.fn(),
}));

import { auth, authFetchBlob } from '../../opscenter/api/auth.svelte';
import { fetchFeatureMediaBlob } from './feature-media';

beforeEach(() => { auth.state = 'signed-out'; });
afterEach(() => vi.clearAllMocks());

test('a signed-out specimen makes no media or refresh request', async () => {
  await expect(fetchFeatureMediaBlob('widget-thumbnails', 'running-sessions.png'))
    .rejects.toThrow('not signed in');
  expect(authFetchBlob).not.toHaveBeenCalled();
});

test('a signed-in media request goes through the one authenticated blob path', async () => {
  auth.state = 'signed-in';
  const image = new Blob(['image']);
  vi.mocked(authFetchBlob).mockResolvedValue(image);
  await expect(fetchFeatureMediaBlob('widget-thumbnails', 'running-sessions.png')).resolves.toBe(image);
  expect(authFetchBlob).toHaveBeenCalledWith('/feature-media/widget-thumbnails/running-sessions.png');
});
