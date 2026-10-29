/** @vitest-environment jsdom */
import { beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const server = vi.hoisted(() => ({ stored: {} as Record<string, unknown> }));
vi.mock('../../sdk', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  authFetch: async (path: string, init?: { method?: string; body?: string }) => {
    expect(path).toBe('/swarm/settings');
    if (init?.method === 'PUT') {
      const change = JSON.parse(init.body!) as Record<string, unknown>;
      for (const [k, v] of Object.entries(change)) {
        const old = server.stored[k];
        server.stored[k] = v && typeof v === 'object' && old && typeof old === 'object' ? { ...old, ...v } : v;
      }
    }
    return structuredClone(server.stored);
  },
}));

const { loadSwarmSettings, saveSwarmSettings } = await import('./swarm-settings.svelte');
const { adoptLook, swarmLook, STATES } = await import('./characters');
const { colorBook } = await import('./agent-colors.svelte');
const { default: Character } = await import('./characters/Character.svelte');

describe('swarm look settings', () => {
  beforeEach(() => {
    server.stored = {};
    adoptLook({});
  });

  test('a change round-trips, and a character draws the picked shape, color mode and animation', async () => {
    expect(swarmLook.color_mode).toBe('project');
    const agent = { id: 7, rank: 'feature', company_id: 1, project_id: 3 };
    expect(colorBook([agent], null).of(agent).family).toBe('project:3');

    const workingMove = STATES.working.animation;
    expect(await saveSwarmSettings({ color_mode: 'random', shapes: { company: 'hexagon' }, animations: { working: 'none' } })).toBe(true);
    expect(await saveSwarmSettings({ shapes: { sysop: 'cloud' }, animations: { question: workingMove } })).toBe(true);
    adoptLook({});
    await loadSwarmSettings();
    expect(swarmLook.color_mode).toBe('random');
    expect(swarmLook.shapes).toEqual({ sysop: 'cloud', company: 'hexagon', project: 'square', agent: 'square' });
    expect(swarmLook.animations).toEqual({ working: 'none', question: workingMove });

    expect(colorBook([agent], null).of(agent).family).toBe('random:7');
    const pair = [agent, { id: 8, rank: 'feature', company_id: 1, project_id: 3 }];
    const source = { companies: [{ id: 1, name: 'c', hue: null }], projects: [{ id: 3, name: 'p', companyId: 1 }], sessions: [] };
    const book = colorBook(pair, source);
    expect(book.of(pair[0]!).shade!.hue).not.toBe(book.of(pair[1]!).shade!.hue);
    const draw = (props: { state: string; rank: string }) => {
      const target = document.createElement('div');
      document.body.append(target);
      const app = mount(Character, { target, props: { size: 40, still: false, ...props } });
      flushSync();
      const el = target.querySelector<HTMLElement>('[data-state]')!;
      const seen = { state: el.dataset.state, status: el.dataset.status, shape: el.dataset.shape, still: el.hasAttribute('data-still') };
      unmount(app);
      return seen;
    };
    expect(draw({ state: 'idle', rank: 'company' })).toMatchObject({ shape: 'hex' });
    expect(draw({ state: 'idle', rank: 'alpha' })).toMatchObject({ shape: 'cloud' });
    expect(draw({ state: 'idle', rank: 'feature' })).toMatchObject({ shape: 'sq' });
    expect(draw({ state: 'working', rank: 'project' })).toMatchObject({ state: 'working', status: 'working', still: true });
    expect(draw({ state: 'question', rank: 'project' })).toMatchObject({ state: 'working', status: 'question', still: false });
  });
});
