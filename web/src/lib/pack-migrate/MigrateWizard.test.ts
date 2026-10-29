/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const calls: { path: string; init?: RequestInit }[] = [];
let roster: unknown;
let opStep = 'code';
let opState = 'applying';
let opDetail: Record<string, unknown> = {};
let opChildren: unknown[] = [];
let extraChecks: unknown[] = [];

const PLAN = {
  kind: 'project', name: 'trader', machine: 'studio', can_apply: true, blocking: [], plan_fingerprint: 'fp1',
  projects: [{ project: 'trader', rung: 'git', rung_reason: 'the other computer clones it from the remote', one_way: false,
    target_root: '/Users/alex/trader', checks: [{ name: 'no_live_sessions', ok: true, detail: 'nothing is running under this project', blocking: true }],
    blocking: [], summary: { sessions: 2, agents: 1, cards: 3, transcript_files: 4 }, publish_card: null }],
};

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    if (path === '/pack/machines') return roster;
    if (path === '/projects/trader/migrate') return JSON.parse(String(init?.body)).apply ? { op_id: 'op1', state: 'applying' } : { ...PLAN, projects: PLAN.projects.map((p) => ({ ...p, checks: [...p.checks, ...extraChecks] })) };
    if (path === '/pack/ops/op1') return { id: 'op1', state: opState, step: opStep, error_code: null, detail: opDetail, children: opChildren,
      steps: ['prepare', 'code', 'rows', 'transcripts', 'verify', 'flip'] };
    throw new Error(`unexpected ${path}`);
  },
}));

import { auth } from '../../opscenter/api/auth.svelte';
import { packMachines } from '../pack-machines/pack-machines-store.svelte';
import { resourcePush } from '../resource-push/boot';
import { setLocale } from '../i18n/index.svelte';
import MigrateWizard from './MigrateWizard.svelte';
import { closeMigrate, openMigrate } from './migrate-store.svelte';

setLocale('en');

const RULES = { may_install_tools: true, may_receive_credentials: true, may_update_carnivore: true, may_host_agents: true,
  may_receive_projects: true, max_agents: null, allowed_projects: [], allowed_companies: [] };
const snap = (rules: Record<string, unknown>) => ({ load: {}, battery: null, reserve: { level: 'away', cpu_pct: 1, mem_pct: 1, source: 's' }, restrictions: { ...RULES, ...rules } });
const machine = (id: string, over: Record<string, unknown> = {}) => ({ install_id: id, label: id, is_self: false, is_master: false, paired: true,
  state: 'connected', capabilities: [], specs: null, snapshot: snap({}), age_seconds: 1, ...over });

const mounted: ReturnType<typeof mount>[] = [];
beforeEach(() => { auth.state = 'signed-in'; calls.length = 0; opStep = 'code'; opState = 'applying'; opDetail = {}; opChildren = []; extraChecks = []; });
afterEach(async () => {
  closeMigrate();
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});

const tick = async () => { await new Promise((r) => setTimeout(r, 0)); flushSync(); };

describe('the migrate wizard', () => {
  test('posts the chosen computer and project, quotes the fingerprint, and follows a pushed pack_ops frame', async () => {
    roster = { master_install_id: 'mac', self_install_id: 'mac', settings: {}, disagreement: null, machines: [
      machine('mac', { is_self: true, state: 'self' }), machine('studio'), machine('closed', { snapshot: snap({ may_receive_projects: false }) })] };
    const root = document.createElement('div');
    document.body.append(root);
    mounted.push(mount(MigrateWizard, { target: root }));
    await packMachines.refresh(true);
    openMigrate({ kind: 'project', name: 'trader' });
    await tick();

    const refused = root.querySelector<HTMLElement>('[data-machine="closed"]')!;
    expect(refused.querySelector<HTMLButtonElement>('[data-mw="pick"]')!.disabled).toBe(true);
    expect(refused.querySelector('[data-mw="reason"]')!.textContent).toContain('does not accept projects');

    root.querySelector<HTMLButtonElement>('[data-machine="studio"] [data-mw="pick"]')!.click();
    await tick();
    const plan = calls.find((c) => c.path === '/projects/trader/migrate')!;
    expect(JSON.parse(String(plan.init?.body))).toEqual({ machine: 'studio' });
    expect(root.querySelector('[data-mw="rung"]')!.textContent).toBe('git remote');

    root.querySelector<HTMLButtonElement>('[data-mw="confirm"]')!.click();
    await tick();
    const applied = calls.filter((c) => c.path === '/projects/trader/migrate').at(-1)!;
    expect(JSON.parse(String(applied.init?.body))).toEqual({ machine: 'studio', apply: true, plan_fingerprint: 'fp1' });
    expect(root.querySelector('[data-step="code"]')!.getAttribute('data-state')).toBe('current');

    resourcePush().store.hello({ resource_topics: ['pack_ops'] });
    await tick();
    opStep = 'verify';
    await tick();
    expect(root.querySelector('[data-step="verify"]')!.getAttribute('data-state')).toBe('pending');
    resourcePush().store.frame({ topics: ['pack_ops:op1'] });
    await tick();
    expect(root.querySelector('[data-step="verify"]')!.getAttribute('data-state')).toBe('current');
    expect(root.querySelector('[data-step="code"]')!.getAttribute('data-state')).toBe('done');
  });

  test('the result screen names the task files the other computer could not carry', async () => {
    roster = { master_install_id: 'mac', self_install_id: 'mac', settings: {}, disagreement: null, machines: [machine('mac', { is_self: true, state: 'self' }), machine('studio')] };
    opState = 'flipped';
    opDetail = { summary: { task_files_not_copied: ['shot.png', 'notes.pdf'] } };
    const root = document.createElement('div');
    document.body.append(root);
    mounted.push(mount(MigrateWizard, { target: root }));
    await packMachines.refresh(true);
    openMigrate({ kind: 'project', name: 'trader' });
    await tick();
    root.querySelector<HTMLButtonElement>('[data-machine="studio"] [data-mw="pick"]')!.click();
    await tick();
    root.querySelector<HTMLButtonElement>('[data-mw="confirm"]')!.click();
    await tick();
    expect(root.querySelector('[data-mw="done"]')).not.toBeNull();
    const names = [...root.querySelectorAll('[data-mw="file-lost"]')].map((n) => n.textContent);
    expect(names).toEqual(['shot.png', 'notes.pdf']);
    expect(root.querySelector('[data-mw="files-lost"]')!.textContent).toContain('2');
  });

  test('seven same-named files show as seven, and a long list ends with an and-N-more line', async () => {
    roster = { master_install_id: 'mac', self_install_id: 'mac', settings: {}, disagreement: null, machines: [machine('mac', { is_self: true, state: 'self' }), machine('studio')] };
    opState = 'flipped';
    opDetail = { summary: { task_files_not_copied: [...Array(7).fill('image.png'), ...Array.from({ length: 18 }, (_, i) => `f${i}.png`)] } };
    const root = document.createElement('div');
    document.body.append(root);
    mounted.push(mount(MigrateWizard, { target: root }));
    await packMachines.refresh(true);
    openMigrate({ kind: 'project', name: 'trader' });
    await tick();
    root.querySelector<HTMLButtonElement>('[data-machine="studio"] [data-mw="pick"]')!.click();
    await tick();
    root.querySelector<HTMLButtonElement>('[data-mw="confirm"]')!.click();
    await tick();
    expect(root.querySelectorAll('[data-mw="file-lost"]')).toHaveLength(20);
    expect(root.querySelector('[data-mw="files-lost"]')!.textContent).toContain('25');
    expect(root.querySelector('[data-mw="files-lost-more"]')!.textContent).toBe('and 5 more');
  });

  test('the plan step lists the task files the other computer will not carry, capped, before the owner confirms', async () => {
    roster = { master_install_id: 'mac', self_install_id: 'mac', settings: {}, disagreement: null, machines: [machine('mac', { is_self: true, state: 'self' }), machine('studio')] };
    extraChecks = [{ name: 'task_files_not_carried', ok: false, blocking: false, detail: '25 attached task file(s) will not be carried: studio does not have them',
      files: [...Array(7).fill('image.png'), ...Array.from({ length: 13 }, (_, i) => `f${i}.png`)], files_more: 5 }];
    const root = document.createElement('div');
    document.body.append(root);
    mounted.push(mount(MigrateWizard, { target: root }));
    await packMachines.refresh(true);
    openMigrate({ kind: 'project', name: 'trader' });
    await tick();
    root.querySelector<HTMLButtonElement>('[data-machine="studio"] [data-mw="pick"]')!.click();
    await tick();
    expect(root.querySelector('[data-mw="done"]')).toBeNull();
    expect(root.querySelectorAll('[data-mw="plan-file"]')).toHaveLength(20);
    expect(root.querySelector('[data-mw="plan-files-more"]')!.textContent).toBe('and 5 more');
    expect(root.querySelector<HTMLButtonElement>('[data-mw="confirm"]')!.disabled).toBe(false);
  });

  test('a check that could not run shows its note even with no names to list', async () => {
    roster = { master_install_id: 'mac', self_install_id: 'mac', settings: {}, disagreement: null, machines: [machine('mac', { is_self: true, state: 'self' }), machine('studio')] };
    extraChecks = [{ name: 'task_files_not_carried', ok: false, blocking: false, detail: 'some task files could not be checked, so some may not be carried',
      files: [], files_more: 0, files_unchecked: 0, files_check_failed: true }];
    const root = document.createElement('div');
    document.body.append(root);
    mounted.push(mount(MigrateWizard, { target: root }));
    await packMachines.refresh(true);
    openMigrate({ kind: 'project', name: 'trader' });
    await tick();
    root.querySelector<HTMLButtonElement>('[data-machine="studio"] [data-mw="pick"]')!.click();
    await tick();
    expect(root.textContent).toContain('some task files could not be checked');
    expect(root.querySelector('[data-mw="plan-files"]')).toBeNull();
  });

  test('a plan with no dropped files shows no file list', async () => {
    roster = { master_install_id: 'mac', self_install_id: 'mac', settings: {}, disagreement: null, machines: [machine('mac', { is_self: true, state: 'self' }), machine('studio')] };
    const root = document.createElement('div');
    document.body.append(root);
    mounted.push(mount(MigrateWizard, { target: root }));
    await packMachines.refresh(true);
    openMigrate({ kind: 'project', name: 'trader' });
    await tick();
    root.querySelector<HTMLButtonElement>('[data-machine="studio"] [data-mw="pick"]')!.click();
    await tick();
    expect(root.querySelector('[data-mw="plan-files"]')).toBeNull();
  });
});
