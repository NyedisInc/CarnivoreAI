import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

let calls: Array<{ method: string; url: string; body: unknown }> = [];
let rows: Array<{ id: number; name: string; project_count: number; has_image: boolean; image_rev: string | null }> = [];

beforeEach(() => {
  vi.useFakeTimers();
  calls = [];
  rows = [
    { id: 2, name: 'beta', project_count: 1, has_image: false, image_rev: null },
    { id: 1, name: 'Acme', project_count: 0, has_image: true, image_rev: '77' },
  ];
  const map = new Map<string, string>([['claude_tunnel_token', 'an-access-token']]);
  (globalThis as { localStorage?: unknown }).localStorage = {
    getItem: (k: string): string | null => map.get(k) ?? null,
    setItem: (k: string, v: string): void => void map.set(k, v),
    removeItem: (k: string): void => void map.delete(k),
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ method: init?.method ?? 'GET', url, body: typeof init?.body === 'string' ? JSON.parse(init.body) : null });
      return new Response(JSON.stringify(init?.method === 'DELETE' ? { deleted: true, orphaned: 2 } : { companies: rows }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }),
  );
  vi.resetModules();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  delete (globalThis as { localStorage?: unknown }).localStorage;
});

describe('companies client', () => {
  it('sends each documented request', async () => {
    const api = await import('./api');
    await api.createCompany('Acme');
    await api.renameCompany(4, 'Acme Inc');
    await api.deleteCompany(4);
    await api.setProjectCompany('my project', 4);
    await api.unassignProjectCompany('my project');
    const seen = calls.map((c) => [c.method, c.url.replace(/^.*\/api\/v1/, ''), c.body]);
    expect(seen).toEqual([
      ['POST', '/companies', { name: 'Acme' }],
      ['PATCH', '/companies/4', { name: 'Acme Inc' }],
      ['DELETE', '/companies/4', null],
      ['PUT', '/projects/my%20project/company', { company_id: 4 }],
      ['PUT', '/projects/my%20project/company', { company_id: null }],
    ]);
  });
});

describe('hero image client', () => {
  it('uploads multipart, removes, and builds revisioned urls', async () => {
    const api = await import('./api');
    const blob = new Blob([new Uint8Array([1, 2, 3])], { type: 'image/png' });
    await api.uploadCompanyImage(4, blob);
    await api.removeCompanyImage(4);
    await api.uploadProjectImage('my project', blob);
    await api.removeProjectImage('my project');
    const urls = calls.map((c) => [c.method, c.url.replace(/^.*\/api\/v1/, '')]);
    expect(urls).toEqual([
      ['PUT', '/companies/4/image'],
      ['DELETE', '/companies/4/image'],
      ['PUT', '/projects/my%20project/image'],
      ['DELETE', '/projects/my%20project/image'],
    ]);
    expect(api.companyImageUrl({ id: 1, has_image: true, image_rev: '77' })).toBe('/api/v1/companies/1/image?rev=77');
    expect(api.companyImageUrl({ id: 1, has_image: false, image_rev: null })).toBeNull();
    expect(api.projectImageUrl({ name: 'a b', has_image: true, image_rev: '5' })).toBe('/api/v1/projects/a%20b/image?rev=5');
    expect(api.projectImageUrl({ name: 'a', has_image: false })).toBeNull();
  });

  it('sends the upload as FormData without a JSON content type', async () => {
    const api = await import('./api');
    await api.uploadCompanyImage(4, new Blob([new Uint8Array([1])]));
    const init = (fetch as unknown as { mock: { calls: Array<[string, RequestInit]> } }).mock.calls[0]![1];
    expect(init.body).toBeInstanceOf(FormData);
    expect(new Headers(init.headers).has('Content-Type')).toBe(false);
  });
});

describe('companies store', () => {
  it('sorts A-Z regardless of server order', async () => {
    const { sortedCompanies } = await import('./companies.svelte');
    expect(sortedCompanies(rows).map((c) => c.name)).toEqual(['Acme', 'beta']);
    expect(sortedCompanies(null)).toEqual([]);
  });

  it('re-reads on a companies frame and polls nothing while the topic is live', async () => {
    const { resourcePush } = await import('../resource-push/boot');
    const store = resourcePush().store;
    const mod = await import('./companies.svelte');
    await vi.advanceTimersByTimeAsync(0);
    const reads = () => calls.filter((c) => c.method === 'GET' && c.url.endsWith('/companies')).length;
    expect(reads()).toBe(1);
    expect(mod.companies.list.map((c) => c.name)).toEqual(['Acme', 'beta']);
    expect(mod.companies.ready).toBe(true);

    store.hello({ resource_topics: ['companies'] });
    await vi.advanceTimersByTimeAsync(0);
    const afterHello = reads();
    await vi.advanceTimersByTimeAsync(10 * mod.COMPANIES_POLL_MS);
    expect(reads()).toBe(afterHello);

    rows = [{ id: 1, name: 'Acme', project_count: 0, has_image: false, image_rev: null }];
    store.frame({ topics: ['companies'] });
    await vi.advanceTimersByTimeAsync(0);
    expect(reads()).toBe(afterHello + 1);
    expect(mod.companies.list.map((c) => c.name)).toEqual(['Acme']);
  });
});
