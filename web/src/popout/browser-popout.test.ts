/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => {
    localStorage.setItem('claude_tunnel_token', 'an-access-token');
    return { sockets: [] as string[] };
});

vi.mock('../opscenter/api/auth.svelte', async (importOriginal) => {
    const real = await importOriginal<typeof import('../opscenter/api/auth.svelte')>();
    return { ...real, authFetch: async (p: string) => (p === '/browsers' ? { browsers: [{ id: '0123456789abcdef', label: 'docs', url: 'https://example.com', state: 'live', viewers: 1, created_at: '', updated_at: '' }] } : {}) };
});
vi.mock('../lib/browser/browser-socket', () => ({
    openBrowserSocket: (id: string) => {
        server.sockets.push(id);
        return { send: () => {}, reopen: () => {}, close: () => {} };
    },
}));

import BrowserPopout from './BrowserPopout.svelte';
import { browsers } from '../lib/browser/api.svelte';

async function settle(): Promise<void> {
    for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
}

describe('the browser pop-out', () => {
    let app: ReturnType<typeof mount> | null = null;

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} unobserve() {} });
        server.sockets = [];
    });

    afterEach(() => {
        if (app) unmount(app);
        app = null;
        document.body.innerHTML = '';
        vi.unstubAllGlobals();
    });

    test('draws the live view of the named session over that session\'s own socket, titled with its label', async () => {
        await browsers.refresh(true);
        const target = document.createElement('div');
        document.body.appendChild(target);
        app = mount(BrowserPopout, { target, props: { browser: '0123456789abcdef' } });
        await settle();
        expect(server.sockets).toEqual(['0123456789abcdef']);
        expect(target.querySelector('[data-popout-browser="0123456789abcdef"]')).not.toBeNull();
        expect(target.querySelector('[data-widget-head] .oc-frame-name')?.textContent).toBe('docs');
    });
});
