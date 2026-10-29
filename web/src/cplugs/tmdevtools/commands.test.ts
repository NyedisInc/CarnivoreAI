/** @vitest-environment jsdom */
import { beforeEach, describe, expect, test, vi } from 'vitest';

const server = vi.hoisted(() => ({
  commands: [] as Record<string, unknown>[],
  latest: 0,
  paths: [] as string[],
  listener: null as null | ((topics: string[]) => void),
  view: { scrollTop: vi.fn(async () => {}), fold: vi.fn(async () => {}) },
}));

vi.mock('../sdk', async (importOriginal) => {
  const real = await importOriginal<typeof import('../sdk')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      server.paths.push(path);
      const after = Number(new URL(path, 'http://x').searchParams.get('after') ?? -1);
      return { commands: server.commands.filter((c) => (c.seq as number) > after), latest: server.latest };
    },
    resourcePush: () => ({ onChange: (fn: (topics: string[]) => void) => { server.listener = fn; } }),
    taskManagerView: () => server.view,
  };
});

import { COMMAND_FAMILY, readCommands, resetCommands, startCommands } from './commands';

beforeEach(() => {
  resetCommands();
  server.commands = [];
  server.latest = 0;
  server.paths = [];
  server.view.scrollTop.mockClear();
  server.view.fold.mockClear();
});

describe('task-manager-dev-tools commands', () => {
  test('a pushed scroll and fold reach the view once, in order', async () => {
    startCommands();
    await vi.waitFor(() => expect(server.paths.length).toBe(1));
    server.commands = [{ seq: 1, kind: 'scroll_top', list: '12' }, { seq: 2, kind: 'fold', action: 'fold', items: [], groups: [4], project: null }];
    server.latest = 2;
    server.listener?.([`${COMMAND_FAMILY}`]);
    await vi.waitFor(() => expect(server.view.fold).toHaveBeenCalledTimes(1));
    expect(server.view.scrollTop).toHaveBeenCalledWith('12');
    expect(server.view.fold).toHaveBeenCalledWith({ action: 'fold', items: [], groups: [4], project: null });
    await readCommands();
    expect(server.view.scrollTop).toHaveBeenCalledTimes(1);
    expect(server.paths.at(-1)).toContain('after=2');
  });

  test('another plugin topic does nothing', async () => {
    startCommands();
    await vi.waitFor(() => expect(server.paths.length).toBe(1));
    server.listener?.(['cplug.huddle.focus']);
    expect(server.paths.length).toBe(1);
  });

  test('a restarted server counting from 1 again is still heard', async () => {
    server.commands = [{ seq: 5, kind: 'scroll_top' }];
    server.latest = 5;
    await readCommands();
    expect(server.view.scrollTop).toHaveBeenCalledTimes(1);
    server.commands = [{ seq: 1, kind: 'scroll_top' }];
    server.latest = 1;
    await readCommands();
    expect(server.view.scrollTop).toHaveBeenCalledTimes(2);
  });
});
