/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const list = vi.hoisted(() => ({ listBlueprints: vi.fn() }));
vi.mock('../blueprints/api', () => list);

import TargetBlueprint from './TargetBlueprint.svelte';
import { ApiError } from '../../opscenter/api/auth.svelte';
import type { PlacementApi } from './placement-api';

const member = (label: string, host_key?: string) => ({ label, family: 'claude', model: null, folder: { mode: 'existing', path: '/w' }, skills: [], opening_prompt: null, host_key });
const bp = (...sessions: unknown[]) => ({ blueprint_uuid: 'bp1', name: 'one', spec: { version: 1, name: 'one', shape_template: null, sessions } });

let host: HTMLElement;
let app: ReturnType<typeof mount> | null = null;
beforeEach(() => { host = document.createElement('div'); document.body.append(host); });
afterEach(() => { if (app) unmount(app); app = null; host.remove(); vi.clearAllMocks(); });

async function show(blueprint: unknown, api: PlacementApi, target: Record<string, unknown> = { kind: 'blueprint_launch', blueprint_uuid: 'bp1', members: null }, automationId: string | null = 'aut_9'): Promise<void> {
  list.listBlueprints.mockResolvedValue({ status: 'ok', blueprints: [blueprint] });
  app = mount(TargetBlueprint, { target: host, props: { target, automationId: automationId ?? undefined, api } });
  for (let i = 0; i < 10; i += 1) { await tick(); flushSync(); }
}
const fake = (over: Partial<PlacementApi> = {}): PlacementApi & { read: ReturnType<typeof vi.fn>; write: ReturnType<typeof vi.fn> } => ({
  read: vi.fn().mockResolvedValue({ placement: 'here', applies: true }),
  write: vi.fn().mockResolvedValue({ placement: 'auto', applies: true }),
  ...over,
}) as never;
const row = (): HTMLElement | null => host.querySelector('[data-automation-placement]');
const option = (v: string): HTMLElement => host.querySelector(`[data-automation-placement-option="${v}"]`) as HTMLElement;

describe('the computer row', () => {
  test('shows for a saved blueprint with a member that has no computer of its own', async () => {
    await show(bp(member('a')), fake());
    expect(row()).not.toBeNull();
    expect(option('here').getAttribute('aria-checked')).toBe('true');
  });

  test('is absent when every member names a computer, when the route says it does not apply, and for a new automation', async () => {
    await show(bp(member('a', 'peer-1')), fake());
    expect(row()).toBeNull();
    unmount(app!); app = null; host.innerHTML = '';
    await show(bp(member('a')), fake({ read: vi.fn().mockResolvedValue({ placement: 'here', applies: false }) }));
    expect(row()).toBeNull();
    unmount(app!); app = null; host.innerHTML = '';
    const api = fake();
    await show(bp(member('a')), api, undefined, null);
    expect(row()).toBeNull();
    expect(api.read).not.toHaveBeenCalled();
  });

  test('picking auto sends one write with the automation id and leaves the target alone', async () => {
    const api = fake();
    const target = { kind: 'blueprint_launch', blueprint_uuid: 'bp1', members: null };
    await show(bp(member('a')), api, target);
    option('auto').click();
    for (let i = 0; i < 6; i += 1) { await tick(); flushSync(); }
    expect(api.write).toHaveBeenCalledTimes(1);
    expect(api.write).toHaveBeenCalledWith('aut_9', 'auto');
    expect(target).toEqual({ kind: 'blueprint_launch', blueprint_uuid: 'bp1', members: null });
    expect(option('auto').getAttribute('aria-checked')).toBe('true');
  });

  test('a refusal shows its sentence and the pick goes back', async () => {
    const api = fake({ write: vi.fn().mockRejectedValue(new ApiError('x', 422, null, { detail: { code: 'placement_unsupported' } })) });
    await show(bp(member('a')), api);
    option('auto').click();
    for (let i = 0; i < 6; i += 1) { await tick(); flushSync(); }
    expect(host.querySelector('[data-automation-placement-problem]')?.textContent).toContain('auto cannot be set on this automation.');
    expect(option('here').getAttribute('aria-checked')).toBe('true');
  });
});
