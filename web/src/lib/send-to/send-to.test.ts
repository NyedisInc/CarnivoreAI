/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const calls: { path: string; body: Record<string, unknown> }[] = [];
let verdict: Record<string, unknown>;

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string, init?: RequestInit) => {
    calls.push({ path, body: init?.body ? JSON.parse(String(init.body)) : {} });
    if (path.endsWith('/send/check')) return verdict;
    if (path.endsWith('/send')) return { op_id: 'op1', state: 'waiting', machine: 'studio', mode: 'move' };
    if (path === '/pack/ops') return { ops: [] };
    throw new Error(`unexpected ${path}`);
  },
}));

import { auth } from '../../opscenter/api/auth.svelte';
import { setLocale } from '../i18n/index.svelte';
import type { PackMachine } from '../pack-machines/pack-machines-store.svelte';
import { computerNodes } from './host';
import SendToModal from './SendToModal.svelte';

setLocale('en');

const RULES = { may_install_tools: true, may_receive_credentials: true, may_update_carnivore: true, may_host_agents: true,
  may_receive_projects: true, max_agents: null, allowed_projects: [], allowed_companies: [] };
const machine = (id: string, over: Record<string, unknown> = {}): PackMachine => ({ install_id: id, label: id, is_self: false, is_master: false,
  paired: true, state: 'connected', capabilities: [], specs: null, age_seconds: 1,
  snapshot: { load: {}, battery: null, reserve: { level: 'away', cpu_pct: 1, mem_pct: 1, source: 's' }, restrictions: RULES }, ...over }) as unknown as PackMachine;
const ok = { ok: true };
const ALL_OK = { move: ok, copy: ok, fresh: ok, project_on_target: true, project_addable: ok };

const mounted: ReturnType<typeof mount>[] = [];
beforeEach(() => { auth.state = 'signed-in'; calls.length = 0; verdict = ALL_OK; });
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});
const tick = async () => { await new Promise((r) => setTimeout(r, 0)); flushSync(); };

async function open(projectName: string | null = 'trader') {
  const root = document.createElement('div');
  document.body.append(root);
  const onClose = vi.fn();
  mounted.push(mount(SendToModal, { target: root, props: { uuid: 'u1', name: 'api', machine: machine('studio'), projectName, onClose } }));
  await tick();
  return { root, onClose };
}
const q = <T extends HTMLElement = HTMLElement>(sel: string): T | null => document.querySelector<T>(sel);

describe('the send-to submenu', () => {
  test('lists every computer but this one, with the blocked reasons', () => {
    const nodes = computerNodes([
      machine('mac', { is_self: true }), machine('studio'), machine('away', { state: 'offline' }), machine('new', { paired: false }),
      machine('closed', { snapshot: { restrictions: { ...RULES, may_host_agents: false } } }),
    ], { sessionUuid: 'u1', name: 'api', projectName: async () => null }, () => {});
    expect(nodes.map((n) => n.id)).toEqual(['studio', 'away', 'new', 'closed']);
    expect(nodes.every((n) => n.icon === 'wolf')).toBe(true);
    expect(nodes[0]?.blocked).toBeUndefined();
    expect(nodes[1]?.blocked).toBe('not connected');
    expect(nodes[2]?.blocked).toBe('not paired');
    expect(nodes[3]?.blocked).toBe('does not host agents');
  });

  test('with no other computer there is one blocked row', () => {
    const nodes = computerNodes([machine('mac', { is_self: true })], { sessionUuid: 'u1', name: 'api', projectName: async () => null }, () => {});
    expect(nodes).toHaveLength(1);
    expect(nodes[0]?.blocked).toBe('no other computers in the pack');
  });
});

describe('the send-to modal', () => {
  test('shows four options, defaults to move, and posts move', async () => {
    await open();
    expect(document.querySelectorAll('[data-choice]')).toHaveLength(4);
    expect(q('[data-send="title"]')?.textContent).toBe('send api to studio');
    expect(q('[data-send="with-project"]')).toBeNull();
    q<HTMLButtonElement>('[data-send="go"]')!.click();
    await tick();
    const post = calls.find((c) => c.path === '/sessions/u1/send');
    expect(post?.body).toEqual({ machine: 'studio', mode: 'move', with_project: false });
  });

  test('the stop-running box is off every time, a running agent blocks the move until it is ticked, and the flag rides only when ticked', async () => {
    const why = 'api is running; the move will not start until it stops or you tick stop running agents now';
    verdict = { ...ALL_OK, running: true, move: { ok: false, reason: 'agents_running', detail: why } };
    await open();
    const box = () => q<HTMLButtonElement>('[data-send="stop-running"] button')!;
    expect(box().getAttribute('aria-checked')).toBe('false');
    expect(q('[data-send="why"]')?.textContent).toBe(why);
    verdict = { ...ALL_OK, running: true };
    box().click();
    await tick();
    expect(calls.filter((c) => c.path.endsWith('/send/check')).at(-1)?.body).toEqual({ machine: 'studio', stop_running: true });
    expect(q<HTMLInputElement>('[data-choice="move"]')!.checked).toBe(true);
    q<HTMLButtonElement>('[data-send="go"]')!.click();
    await tick();
    expect(calls.find((c) => c.path === '/sessions/u1/send')?.body).toEqual({ machine: 'studio', mode: 'move', with_project: false, stop_running: true });
  });

  test('a blocked option is inert with its reason, and the default moves to the first usable one', async () => {
    verdict = { ...ALL_OK, move: { ok: false, reason: 'no_conversation' }, copy: { ok: false, reason: 'no_conversation' } };
    await open();
    expect(q<HTMLInputElement>('[data-choice="move"]')!.disabled).toBe(true);
    expect(q('[data-send="why"]')?.textContent).toBe('it has no conversation yet.');
    expect(q<HTMLInputElement>('[data-choice="fresh"]')!.checked).toBe(true);
    q<HTMLButtonElement>('[data-send="go"]')!.click();
    await tick();
    expect(calls.find((c) => c.path === '/sessions/u1/send')?.body.mode).toBe('fresh');
  });

  test('the project box shows only when the project is missing and addable, ticked, and rides with_project', async () => {
    const gone = { ok: false, reason: 'project_not_on_target' };
    verdict = { move: gone, copy: gone, fresh: gone, project_on_target: false, project_addable: ok };
    await open();
    expect(q('[data-send="with-project"]')).not.toBeNull();
    expect(q<HTMLInputElement>('[data-choice="copy"]')!.disabled).toBe(false);
    q<HTMLInputElement>('[data-choice="copy"]')!.click();
    q<HTMLButtonElement>('[data-send="go"]')!.click();
    await tick();
    expect(calls.find((c) => c.path === '/sessions/u1/send')?.body).toEqual({ machine: 'studio', mode: 'copy', with_project: true });
  });

  test('a missing project that cannot be added blocks the options and shows no box', async () => {
    const gone = { ok: false, reason: 'project_not_on_target' };
    verdict = { move: gone, copy: gone, fresh: gone, project_on_target: false, project_addable: { ok: false, reason: 'not_project_home' } };
    await open(null);
    expect(q('[data-send="with-project"]')).toBeNull();
    expect(q<HTMLInputElement>('[data-choice="move"]')!.disabled).toBe(true);
    expect(q<HTMLButtonElement>('[data-send="go"]')!.disabled).toBe(true);
  });

  test('move the whole project is blocked for an agent with no project', async () => {
    await open(null);
    expect(q<HTMLInputElement>('[data-choice="project"]')!.disabled).toBe(true);
  });

  test('a started send hands the op to the status toast and closes at once; the dialog never follows it', async () => {
    const { onClose } = await open();
    q<HTMLButtonElement>('[data-send="go"]')!.click();
    await vi.waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(calls.some((c) => c.path.startsWith('/pack/ops/op1'))).toBe(false);
    expect(calls.some((c) => c.path === '/pack/ops')).toBe(true);
  });
});

describe('the send dialog verdict (#2579)', () => {
  const detail = 'studio runs an older carnivore and cannot take DrMario (nested repo); update studio, then send again';
  const refused = { ok: false, reason: 'content_not_carried', detail };
  const carry = {
    units: [{ kind: 'repo', path: '.', state: 'dirty' }, { kind: 'repo', path: 'PillPanic', state: 'dirty' }, { kind: 'worktree', path: '/w/x', state: 'outside the folder' }],
    left_behind: [{ what: 'DrMario/build', why: 'ignored content is never carried', size: 1000 }, { what: 'DrMario/.cache', why: 'ignored content is never carried', size: null }],
    total_bytes: 1288490189,
  };

  test('a target that cannot carry the folder shows ONE verdict with the fix, quiet reasons and no warning-colored stays-behind rows', async () => {
    verdict = { move: refused, copy: refused, fresh: refused, project_on_target: true, project_addable: ok, carry };
    const m = machine('studio', { host_key: 'peer-studio', snapshot: { restrictions: RULES, app_version: '1.16.3' } });
    const root = document.createElement('div');
    document.body.append(root);
    mounted.push(mount(SendToModal, { target: root, props: { uuid: 'u1', name: 'api', machine: m, projectName: 'trader', onClose: vi.fn() } }));
    await tick();
    expect(document.querySelectorAll('[data-send="verdict"]')).toHaveLength(1);
    const v = q('[data-send="verdict"]')!;
    expect(v.getAttribute('data-state')).toBe('blocked');
    expect(v.textContent).toContain("can't send yet. studio runs carnivore 1.16.3");
    expect(v.textContent).toContain('nested repos, worktrees outside the folder');
    expect(v.textContent).toContain('update studio, then send.');
    expect(q('[data-send="update"]')).not.toBeNull();
    expect([...document.querySelectorAll('[data-send="why"]')].filter((e) => e.textContent !== 'see the note above.' && !/project/.test(e.textContent ?? ''))).toHaveLength(0);
    expect(q<HTMLButtonElement>('[data-send="go"]')!.disabled).toBe(true);
    expect(q('[data-send="go"]')!.getAttribute('title')).toContain("can't send yet");
    const rows = [...document.querySelectorAll('[data-carry="comes"]')].map((e) => e.textContent);
    expect(rows).toEqual(['the project folder', 'PillPanic', '/w/x']);
    expect(q('[data-carry="total"]')!.textContent).toBe('about 1.2 gb to send');
    const text = q('[data-send="carry"]')!.textContent ?? '';
    expect(text).not.toMatch(/uncommitted|outside the folder|ignored|stay behind/);
  });

  test('a target that can take it says ready with the repo count', async () => {
    verdict = { ...ALL_OK, carry };
    await open();
    const v = q('[data-send="verdict"]')!;
    expect(v.getAttribute('data-state')).toBe('ready');
    expect(v.textContent?.trim()).toBe('ready: 2 repos go to studio');
    expect(q('[data-send="update"]')).toBeNull();
    expect(q<HTMLButtonElement>('[data-send="go"]')!.disabled).toBe(false);
  });

  test('copy refused because the conversation is already there says so in plain words', async () => {
    verdict = { ...ALL_OK, copy: { ok: false, reason: 'conversation_already_here' } };
    await open();
    expect(q('[data-send="why"]')?.textContent).toContain('studio already has a copy of this conversation');
  });
});

