import { afterEach, beforeEach, expect, test, vi } from 'vitest';

vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-out', notice: '' },
  accessToken: () => 'specimen-token',
  hasRefreshToken: () => false,
  refreshTokens: vi.fn(),
}));

import { auth, refreshTokens } from '../../opscenter/api/auth.svelte';
import { fetchFeatureMediaBlob } from './feature-media';

beforeEach(() => { auth.state = 'signed-out'; });
afterEach(() => vi.unstubAllGlobals());

test('a signed-out specimen makes no media or refresh request', async () => {
  const fetcher = vi.fn();
  vi.stubGlobal('fetch', fetcher);
  await expect(fetchFeatureMediaBlob('widget-thumbnails', 'running-sessions.png'))
    .rejects.toThrow('not signed in');
  expect(fetcher).not.toHaveBeenCalled();
  expect(refreshTokens).not.toHaveBeenCalled();
});

test('a signed-in media request still sends its bearer token', async () => {
  auth.state = 'signed-in';
  const image = new Blob(['image']);
  const fetcher = vi.fn().mockResolvedValue({ ok: true, status: 200, blob: () => image });
  vi.stubGlobal('fetch', fetcher);
  await expect(fetchFeatureMediaBlob('widget-thumbnails', 'running-sessions.png')).resolves.toBe(image);
  expect(fetcher).toHaveBeenCalledOnce();
  const [path, options] = fetcher.mock.calls[0]!;
  expect(path).toBe('/api/v1/feature-media/widget-thumbnails/running-sessions.png');
  expect(options.headers.get('Authorization')).toBe('Bearer specimen-token');
});
