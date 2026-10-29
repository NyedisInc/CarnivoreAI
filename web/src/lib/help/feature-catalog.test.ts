import { beforeEach, describe, expect, it, vi } from 'vitest';

import { loadFeatureCatalog, resetFeatureCatalog } from './feature-catalog';

const body = { available: true, areas: [], catalog: [], changes: [] };

beforeEach(() => resetFeatureCatalog());

describe('loadFeatureCatalog', () => {
  it('two mounts opening the help panel share one fetch of the same document (u139-02)', async () => {
    const fetcher = vi.fn(async () => body);
    const [a, b] = await Promise.all([loadFeatureCatalog(fetcher as never), loadFeatureCatalog(fetcher as never)]);
    await loadFeatureCatalog(fetcher as never);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledWith('/feature-catalog');
    expect(a).toBe(b);
  });

  it('a failed load is forgotten, so the next open tries again', async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new Error('down')).mockResolvedValueOnce(body);
    await expect(loadFeatureCatalog(fetcher as never)).rejects.toThrow('down');
    await expect(loadFeatureCatalog(fetcher as never)).resolves.toEqual(body);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
