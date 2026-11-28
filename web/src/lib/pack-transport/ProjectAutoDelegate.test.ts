/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const machine = (id: string, over: Record<string, unknown> = {}) => ({
  install_id: id, label: id, is_self: false, is_master: false, paired: true, state: 'connected', capabilities: ['pack.jobs'], specs: null, snapshot: null, age_seconds: 1, ...over,
});
const roster = [
  machine('mac', { is_self: true, state: 'self' }), machine('studio'), machine('odin'),
  machine('loki', { state: 'disconnected' }), machine('old', { capabilities: [] }),
  machine('nowork', { snapshot: { restrictions: { may_host_agents: false } } }),
];

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string) => {
    if (path === '/pack/machines') return { master_install_id: 'mac', self_install_id: 'mac', settings: { placement_mode: 'stats', auto_distribute: false }, disagreement: null, machines: roster };
    return [];
  },
}));

import { auth } from '../../opscenter/api/auth.svelte';
import { packMachines } from '../pack-machines/pack-machines-store.svelte';
import ProjectAutoDelegate from './ProjectAutoDelegate.svelte';
import type { AutoDelegateApi, AutoDelegateBody, AutoDelegateView } from './auto-delegate-api';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const home = (over: Partial<AutoDelegateView> = {}): AutoDelegateView => ({
  role: 'home', this_computer: { install_id: 'mac', label: 'mac' }, is_repo: true, live_jobs: 0, auto_delegate: false, never_use: [], copies: [],
  copy_run: { running: false, refused: {}, error: null }, ...over,
});

const puts: AutoDelegateBody[] = [];
let answer: AutoDelegateView = home();
let refuse: Error | null = null;
let putAnswer: AutoDelegateView | null = null;
const api: AutoDelegateApi = {
  get: async () => { if (refuse) throw refuse; return answer; },
  recentJobs: async () => [],
  put: async (_name, body) => {
    puts.push(body);
    if (refuse) throw refuse;
    answer = putAnswer ?? { ...answer, auto_delegate: body.on, never_use: body.never_use ?? answer.never_use };
    return answer;
  },
};

const mounted: ReturnType<typeof mount>[] = [];
const settle = async (): Promise<void> => { await new Promise((r) => setTimeout(r, 0)); flushSync(); };
async function render(): Promise<HTMLElement> {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(ProjectAutoDelegate, { target, props: { name: 'notes', api } }));
  await packMachines.refresh(true);
  await settle();
  await settle();
  return target;
}
const q = (sel: string): HTMLElement | null => document.body.querySelector<HTMLElement>(sel);
const qa = (sel: string): HTMLElement[] => [...document.body.querySelectorAll<HTMLElement>(sel)];
const hintOf = (id: string): string => q(`[data-computer="${id}"] .oc-list__secondary`)?.textContent ?? '';
const flipSwitch = async (): Promise<void> => { q('[data-ad="switch"]')!.click(); await settle(); await settle(); };

beforeEach(() => { auth.state = 'signed-in'; puts.length = 0; answer = home(); refuse = null; putAnswer = null; });
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});

describe('the block states', () => {
  test('a computer the server lists in no_work, or a takes-work-off one that is offline, says only that it takes no work and is not waited on', async () => {
    answer = home({ auto_delegate: true, no_work: ['studio', 'loki', 'nowork'] });
    await render();
    expect(hintOf('studio')).toBe('does not take work');
    expect(hintOf('loki')).toBe('does not take work');
    expect(hintOf('nowork')).toBe('does not take work');
    expect(hintOf('odin')).not.toContain('does not take work');
  });

  test('a refused read: the engine down, and any other failure, show in words with no switch', async () => {
    refuse = new Error('jobs are not ready yet. try again in a moment.');
    await render();
    expect(q('[data-ad="error"]')!.textContent).toContain('not ready');
    expect(q('[data-ad="switch"]')).toBeNull();
  });

  test('a copy and a moved-away project each show one note and no switch', async () => {
    answer = { role: 'copy', home_computer: 'studio' };
    await render();
    expect(q('[data-ad="copy-here"]')!.textContent).toContain('set on studio');
    expect(q('[data-ad="switch"]')).toBeNull();
    await unmount(mounted.pop()!);
    document.body.replaceChildren();
    answer = { role: 'moved', moved_to: 'odin' };
    await render();
    expect(q('[data-ad="moved"]')!.textContent).toContain('moved to odin');
    expect(q('[data-ad="computer"]')).toBeNull();
  });

  test('not a repo: the switch is disabled and off, one note, no list', async () => {
    answer = home({ is_repo: false });
    await render();
    expect((q('[data-ad="switch"]') as HTMLButtonElement).disabled).toBe(true);
    expect(q('[data-ad="switch"]')!.getAttribute('aria-checked')).toBe('false');
    expect(q('[data-ad="not-repo"]')).not.toBeNull();
    expect(q('[data-ad="computer"]')).toBeNull();
  });

  test('off shows its hint and the list; on shows its hint; a running job disables the switch', async () => {
    await render();
    expect(q('[data-tile="auto-delegate"] .dk-sum')!.textContent).toContain('nothing from this project is handed to another computer');
    expect(document.body.querySelectorAll('[data-ad="computer"]').length).toBe(5);
    await unmount(mounted.pop()!);
    document.body.replaceChildren();
    answer = home({ auto_delegate: true, live_jobs: 1 });
    await render();
    expect(q('[data-tile="auto-delegate"] .dk-sum')!.textContent).toContain('heavy commands may go to the ticked computers');
    expect((q('[data-ad="switch"]') as HTMLButtonElement).disabled).toBe(true);
    expect(q('[data-ad="jobs-running"]')).not.toBeNull();
  });
});

describe('the computer rows', () => {
  test('each state line, in the order the rules run', async () => {
    answer = home({
      auto_delegate: true, never_use: ['odin'],
      copies: [{ install_id: 'odin', label: 'odin', auto: true }, { install_id: 'nowork', label: 'nowork', auto: false }],
      copy_run: { running: true, refused: { studio: 'project_name_taken' }, error: null },
    });
    await render();
    expect(hintOf('odin')).toBe('never used for this project, still has a copy');
    expect(hintOf('loki')).toBe('not connected');
    expect(hintOf('old')).toBe('remote carnivore needs update');
    expect((q('[data-computer="old"] input') as HTMLInputElement).checked).toBe(false);
    expect((q('[data-computer="old"] input') as HTMLInputElement).disabled).toBe(true);
    expect(hintOf('studio')).toBe('could not copy: a different project there already has this name.');
    expect(hintOf('nowork')).toBe('does not take work');
    expect((q('[data-computer="odin"] input') as HTMLInputElement).checked).toBe(false);
    expect((q('[data-computer="studio"] input') as HTMLInputElement).checked).toBe(true);
  });

  test('copying, has a copy, no copy, never, generic refusal, and no work with no copy', async () => {
    answer = home({
      auto_delegate: true, never_use: ['loki'],
      copies: [{ install_id: 'odin', label: 'odin', auto: true }],
      copy_run: { running: true, refused: { old: 'weird_code' }, error: null },
    });
    await render();
    expect(hintOf('studio')).toBe('copying');
    expect(hintOf('odin')).toBe('');
    expect(hintOf('loki')).toBe('never used for this project');
    expect(hintOf('nowork')).toBe('does not take work');
    expect((q('[data-ad="copy-now"]') as HTMLButtonElement).disabled).toBe(true);
    await unmount(mounted.pop()!);
    document.body.replaceChildren();
    answer = home({ auto_delegate: true, copy_run: { running: false, refused: { studio: 'weird_code' }, error: null } });
    await render();
    expect(hintOf('studio')).toBe('could not copy here');
    expect(hintOf('odin')).toBe('');
    expect(hintOf('studio')).not.toContain('has a copy');
  });

  test('no other paired computer shows its note in place of the list', async () => {
    const saved = roster.splice(1);
    await render();
    expect(q('[data-ad="no-computers"]')).not.toBeNull();
    roster.push(...saved);
  });
});

describe('the writes, byte for byte', () => {
  test('turn on, copy now, untick, tick back, and untick while off', async () => {
    await render();
    await flipSwitch();
    expect(puts.at(-1)).toEqual({ on: true });
    expect(q('[data-ad="copy-now"]')).not.toBeNull();
    q('[data-ad="copy-now"]')!.click();
    await settle();
    expect(puts.at(-1)).toEqual({ on: true });
    q('[data-computer="studio"] input')!.click();
    await settle();
    await settle();
    expect(puts.at(-1)).toEqual({ on: true, never_use: ['studio'] });
    q('[data-computer="studio"] input')!.click();
    await settle();
    await settle();
    expect(puts.at(-1)).toEqual({ on: true, never_use: [] });
    await unmount(mounted.pop()!);
    document.body.replaceChildren();
    answer = home({ never_use: ['studio'] });
    await render();
    q('[data-computer="odin"] input')!.click();
    await settle();
    await settle();
    expect(puts.at(-1)).toEqual({ on: false, never_use: ['studio', 'odin'] });
  });

  test('a stored label entry is dropped with the id when the computer is ticked back', async () => {
    answer = home({ auto_delegate: true, never_use: ['studio', 'x'] });
    await render();
    q('[data-computer="studio"] input')!.click();
    await settle();
    await settle();
    expect(puts.at(-1)).toEqual({ on: true, never_use: ['x'] });
  });

  test('a refused write shows its sentence and the switch shows what the server holds', async () => {
    await render();
    refuse = new Error('auto-delegate needs the project folder to be the top of a git repository.');
    await flipSwitch();
    expect(q('[data-ad="error"]')!.textContent).toContain('top of a git repository');
    expect(q('[data-ad="switch"]')!.getAttribute('aria-checked')).toBe('false');
  });
});

describe('turning off with no dialog', () => {
  const withCopies = (): AutoDelegateView => home({
    auto_delegate: true, copies: [{ install_id: 'studio', label: 'studio', auto: true, root: '/work/notes' }, { install_id: 'odin', label: 'odin', auto: false, root: '/odin/notes' }],
  });

  test('off sends the keep-copies body at once; the auto copy gets a row and a trash that sends delete_only for that copy; a hand-made copy gets none', async () => {
    answer = withCopies();
    await render();
    await flipSwitch();
    expect(puts).toEqual([{ on: false }]);
    expect(q('[data-ad="switch"]')!.getAttribute('aria-checked')).toBe('false');
    const rows = qa('[data-ad="leftover"]');
    expect(rows.length).toBe(1);
    expect(rows[0]!.textContent).toContain('studio');
    expect(rows[0]!.textContent).toContain('/work/notes');
    q('[data-ad="leftover-trash"]')!.click();
    await settle();
    await settle();
    expect(puts[1]).toEqual({ on: false, delete_copies: true, delete_only: ['studio'] });
  });

  test('a kept copy stays listed and says why in one line', async () => {
    answer = withCopies();
    await render();
    await flipSwitch();
    putAnswer = { ...answer, kept: [{ label: 'studio', code: 'unseen_commits', root: '/work/notes' }] };
    q('[data-ad="leftover-trash"]')!.click();
    await settle();
    await settle();
    expect(q('[data-ad="note"]')!.textContent).toContain('commits the master does not have');
    expect(qa('[data-ad="leftover"]').length).toBe(1);
  });
  test('P20 9d: with the mesh switch on a copy refusal has plain words and a member with no row gets one line; with it off today\'s words stay', async () => {
    const run = { running: false, refused: { studio: 'member_link_off', charlie: 'not_linked' }, error: null };
    answer = home({ auto_delegate: true, copy_run: run });
    roster.push(machine('charlie', { paired: false, state: 'reported_connected' }));
    try {
      await render();
      expect(hintOf('studio')).toBe('could not copy here');
      expect(q('[data-ad="member-refused"]')).toBeNull();
      await unmount(mounted.pop()!);
      document.body.replaceChildren();
      roster[0]!.capabilities = ['pack.mesh_v1'];
      await render();
      expect(hintOf('studio')).toBe('could not copy: its link switch is off');
      const lines = qa('[data-ad="member-refused"]');
      expect(lines).toHaveLength(1);
      expect(lines[0]!.textContent).toContain('charlie could not copy: no link to it from here right now');
    } finally {
      roster[0]!.capabilities = ['pack.jobs'];
      roster.pop();
    }
  });
});
