import { afterEach, describe, expect, test, vi } from 'vitest';

import '../../lib/plugins/builtin';
import { cplugEnablement } from './enablement.svelte';
import { runCplugCardAction, startCplugs, startEnabled } from './readers';
import type { CplugWeb } from '../sdk';
import { registerSwarmFace, swarmFace } from '../sdk/swarm-face.svelte';
import { swarmRosterAgents } from '../sdk/swarm-roster.svelte';
import { swarmRoster } from '../huddle/agents/agent-roster.svelte';
import type { Component } from 'svelte';

const context = { flags: {}, refresh: vi.fn() };
const row = { name: 'cloude_api', unread: false, sessionId: 'ses_1' };

afterEach(() => {
  cplugEnablement.enabled = {};
  delete (globalThis as { API?: unknown }).API;
});

describe('runCplugCardAction', () => {
  test('runs the plugin\'s own card action while it is on (the default)', async () => {
    const setSessionUnread = vi.fn(async () => ({}));
    (globalThis as { API?: unknown }).API = { setSessionUnread };
    expect(await runCplugCardAction('unread', row, context)).toBe(true);
    expect(setSessionUnread).toHaveBeenCalledWith('cloude_api', true);
  });

  test('NEGATIVE CONTROL: answers false and runs nothing once the plugin is switched off', async () => {
    const setSessionUnread = vi.fn(async () => ({}));
    (globalThis as { API?: unknown }).API = { setSessionUnread };
    cplugEnablement.enabled = { unread: false };
    expect(await runCplugCardAction('unread', row, context)).toBe(false);
    expect(setSessionUnread).not.toHaveBeenCalled();
  });

  test('a plugin with no card action, or no plugin at all, runs nothing', async () => {
    expect(await runCplugCardAction('huddle', row, context)).toBe(false);
    expect(await runCplugCardAction('nope', row, context)).toBe(false);
  });
});

describe('startCplugs stops a plugin that is off', () => {
  test('the Task Manager takes its Swarm member face back when it is switched off, and puts it back when it is on', () => {
    const face = (() => {}) as unknown as Component<never>;
    registerSwarmFace(face as never);
    cplugEnablement.enabled = { huddle: false };
    startCplugs();
    expect(swarmFace.component).toBeNull();
    cplugEnablement.enabled = { huddle: true };
    startCplugs();
    expect(swarmFace.component).not.toBeNull();
  });

  test('the Task Manager registers its Swarm roster reader when it is on, and takes it back when it is switched off (#2662)', () => {
    swarmRoster.agents = [{ id: 7, rank: 'feature', session_uuid: 'u-7' } as never];
    cplugEnablement.enabled = { huddle: true };
    startCplugs();
    expect(swarmRosterAgents().map((agent) => agent.id)).toEqual([7]);
    cplugEnablement.enabled = { huddle: false };
    startCplugs();
    expect(swarmRosterAgents()).toEqual([]);
    swarmRoster.agents = [];
  });
});

describe('startEnabled isolates one plugin from the next', () => {
  const plugin = (id: string, hooks: Pick<CplugWeb, 'start' | 'stop'>): CplugWeb =>
    ({ id, manifest: { id, defaults: { enabled: true } } as unknown as CplugWeb['manifest'], ...hooks });

  test('a throwing stop on the first plugin still starts the second, and the failure is logged with the plugin id', () => {
    const second = vi.fn();
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    cplugEnablement.enabled = { first: false, second: true };
    startEnabled([plugin('first', { stop: () => { throw new Error('boom'); } }), plugin('second', { start: second })]);
    expect(second).toHaveBeenCalledTimes(1);
    expect(error.mock.calls.some((c) => String(c[0]).includes('first'))).toBe(true);
    error.mockRestore();
  });

  test('a throwing start on the first plugin still starts the second', () => {
    const second = vi.fn();
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    cplugEnablement.enabled = { first: true, second: true };
    startEnabled([plugin('first', { start: () => { throw new Error('boom'); } }), plugin('second', { start: second })]);
    expect(second).toHaveBeenCalledTimes(1);
    error.mockRestore();
  });
});
