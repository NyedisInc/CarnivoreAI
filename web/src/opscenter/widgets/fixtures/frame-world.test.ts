/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ACCESS_KEY, installApiInterceptor, isolateWorld, type ApiRequest } from './frame-world';

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

describe('installApiInterceptor', () => {
  it('answers a same-origin /api/ request itself, with the method upper-cased and /api/v1 removed', async () => {
    const seen: ApiRequest[] = [];
    installApiInterceptor('http://app.test/', 'http://app.test', async (request) => {
      seen.push(request);
      return new Response('{}');
    });
    await fetch('/api/v1/notes?x=1', { method: 'post' });
    expect(seen).toHaveLength(1);
    expect(seen[0]).toMatchObject({ method: 'POST', path: '/notes' });
    expect(seen[0]!.url.search).toBe('?x=1');
  });

  it('sends everything else on to the network fetch', async () => {
    const network = vi.fn(async () => new Response('net'));
    globalThis.fetch = network as unknown as typeof fetch;
    installApiInterceptor('http://app.test/', 'http://app.test', async () => new Response('stub'));
    expect(await (await fetch('/themes/x.json')).text()).toBe('net');
    expect(await (await fetch('http://other.test/api/v1/a')).text()).toBe('net');
    expect(network).toHaveBeenCalledTimes(2);
  });
});

describe('isolateWorld', () => {
  it('holds a placeholder token in its own memory and starts empty when not seeded', () => {
    globalThis.localStorage.setItem(ACCESS_KEY, 'real-app-token');
    isolateWorld({ seedStorage: false, placeholderToken: 'placeholder', freeze: false });
    expect(globalThis.localStorage.getItem(ACCESS_KEY)).toBe('placeholder');
  });

  it('keeps a seeded token rather than overwriting it, and sets none when asked for none', () => {
    isolateWorld({ seedStorage: true, placeholderToken: 'placeholder', freeze: false });
    expect(globalThis.localStorage.getItem(ACCESS_KEY)).toBe('placeholder');
    isolateWorld({ seedStorage: false, placeholderToken: null, freeze: false });
    expect(globalThis.localStorage.getItem(ACCESS_KEY)).toBeNull();
  });
});
