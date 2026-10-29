import { beforeEach, expect, test, vi } from 'vitest';

vi.mock('../../opscenter/api/auth.svelte', () => ({
    API_BASE: '/api/v1',
    auth: { state: 'signed-in', notice: '' },
    authFetchBlob: vi.fn(),
}));
import { auth, authFetchBlob } from '../../opscenter/api/auth.svelte';
import { heroImageObjectUrl } from './image-blob';

beforeEach(() => {
    vi.clearAllMocks();
    auth.state = 'signed-in';
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:hero' }));
});

test('a signed-in fetch asks for the path under /api/v1 and answers an object URL', async () => {
    vi.mocked(authFetchBlob).mockResolvedValue(new Blob(['x']));
    expect(await heroImageObjectUrl('/api/v1/companies/1/image?rev=a')).toBe('blob:hero');
    expect(authFetchBlob).toHaveBeenCalledWith('/companies/1/image?rev=a');
});

test('signed out sends no request and answers null; a failure is not cached', async () => {
    auth.state = 'signed-out';
    expect(await heroImageObjectUrl('/api/v1/companies/2/image?rev=a')).toBeNull();
    expect(authFetchBlob).not.toHaveBeenCalled();
    auth.state = 'signed-in';
    vi.mocked(authFetchBlob).mockResolvedValue(new Blob(['y']));
    expect(await heroImageObjectUrl('/api/v1/companies/2/image?rev=a')).toBe('blob:hero');
});
