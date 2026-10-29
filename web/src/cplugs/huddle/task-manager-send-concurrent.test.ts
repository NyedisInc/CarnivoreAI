/** @vitest-environment jsdom */
import { describe, expect, test, vi } from 'vitest';

const server = vi.hoisted(() => ({ sends: [] as string[], release: null as null | (() => void) }));

vi.mock('../sdk', async (importOriginal) => {
  const real = await importOriginal<typeof import('../sdk')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      if (path === '/cplugs/huddle/send') {
        const body = JSON.parse(String(init.body)) as { lists: string[] };
        server.sends.push(body.lists.join(','));
        return { results: body.lists.map((list) => ({ list, status: 'sent', target: list === '18' ? 'ses_new' : undefined })) };
      }
      return {};
    },
  };
});

vi.mock('./task-manager-send-start', async (importOriginal) => {
  const real = await importOriginal<typeof import('./task-manager-send-start')>();
  return {
    ...real,
    startSessionFor: async () => ({ session: 'ses_new', failure: null }),
    waitUntilReady: () => new Promise<boolean>((resolve) => { server.release = () => resolve(true); }),
  };
});

vi.mock('./huddle.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('./huddle.svelte')>();
  return { ...real, refreshLists: async () => undefined };
});

import { pickFor, resetSendPicks, sendLists } from './huddle-send-many.svelte';
import { START_NEW } from './task-manager-send-start';

describe('sendLists with a start-new pick', () => {
  test('the list with a live session is told while the new session is still starting', async () => {
    resetSendPicks();
    pickFor('18', START_NEW);
    const done = sendLists(['12', '18']);
    for (let i = 0; i < 20; i += 1) await Promise.resolve();
    expect(server.sends).toEqual(['12']);
    server.release?.();
    await done;
    expect(server.sends).toEqual(['12', '18']);
    resetSendPicks();
  });
});
