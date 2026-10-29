/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const calls: Array<{ method: string; path: string; body: Record<string, unknown> | null }> = [];
let skillsReply: unknown;
let firesReply: unknown;
let scoutReply: unknown = { state: 'none', suggestions: [] };
let onChanged: (() => void) | null = null;

vi.mock('../../opscenter/api/auth.svelte', async (orig) => {
    const real = (await orig()) as Record<string, unknown>;
    return {
        ...real,
        authFetch: async (path: string, init: RequestInit = {}) => {
            const body = init.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
            calls.push({ method: init.method ?? 'GET', path, body });
            if (path.endsWith('/skills/scout')) return scoutReply;
            if (path.endsWith('/skill-fires')) return firesReply;
            if (path.endsWith('/skills')) return skillsReply;
            if (path === '/skills/overrides') {
                return { ...body, wrote: true, restart_required: body?.['harness'] === 'codex', reload_hint: null };
            }
            throw new Error(`unexpected ${path}`);
        },
    };
});
vi.mock('../../opscenter/api/events.svelte', () => ({
    subscribe: (_k: string, handler: () => void) => {
        onChanged = handler;
        return () => {
            onChanged = null;
        };
    },
}));

import SessionSkillsPanel from './SessionSkillsPanel.svelte';
import { isOn, stateFor, switchTarget } from './session-skills';
import type { SessionSkill } from '../skills-page/skills-types';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const skill = (over: Partial<SessionSkill> & Pick<SessionSkill, 'name'>): SessionSkill => ({
    location_id: `personal-claude:${over.name}`,
    scope: 'personal',
    state: 'on',
    state_source: null,
    model_sees: true,
    reason: null,
    description_tokens_est: 40,
    tokens_est: 40,
    shadowed_by: null,
    ...over,
});

const CLAUDE = (): unknown => ({
    state: 'ok',
    family: 'claude',
    profile: { source: 'default', directory: '/home/x/.claude' },
    working_dir: '/work/lab',
    skills: [
        skill({ name: 'sme' }),
        skill({ name: 'noisy', state: 'off', state_source: 'local', model_sees: false, reason: 'off', tokens_est: 0 }),
        skill({ name: 'plug', scope: 'plugin', location_id: 'plugin-claude:plug' }),
        skill({ name: 'dup', scope: 'project', shadowed_by: 'personal-claude:dup', model_sees: false, tokens_est: 0 }),
    ],
    budget_tokens_est: 80,
    tokens_label: 'est.',
    restart_required: false,
    reload_hint: null,
});

let mounted: Record<string, unknown> | null = null;

async function settle(): Promise<void> {
    for (let i = 0; i < 8; i += 1) await Promise.resolve();
    await tick();
    flushSync();
    for (let i = 0; i < 8; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}

async function panel(): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(SessionSkillsPanel, { target, props: { sessionId: 'ses_1', slot: 'terminal:row:1', onClose: vi.fn() } });
    await settle();
    return target;
}

beforeEach(() => {
    calls.length = 0;
    onChanged = null;
    skillsReply = CLAUDE();
    firesReply = {
        state: 'measured',
        fired: 2,
        recent: [
            { skill: 'sme', at: '2026-09-28T10:00:00Z', source: 'tool_use', harness: 'claude', profile: 'default' },
            { skill: 'progress', at: null, source: 'slash', harness: 'claude', profile: 'default' },
        ],
    };
});
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

test('lists the effective skills with state and cost, the folder, and the recent fires', async () => {
    const root = await panel();
    expect(Array.from(root.querySelectorAll('[data-session-skill]')).map((r) => (r as HTMLElement).dataset.sessionSkill)).toEqual(['sme', 'noisy', 'plug', 'dup']);
    expect(root.querySelector('[data-session-skills-summary]')?.textContent).toContain('est. 80 tokens');
    expect(root.textContent).toContain('folder /work/lab');
    expect(root.querySelector('[data-session-skill="dup"]')?.textContent).toContain('shadowed');
    expect(Array.from(root.querySelectorAll('[data-skill-fire-source]')).map((r) => (r as HTMLElement).dataset.skillFireSource)).toEqual(['tool_use', 'slash']);
    expect(root.querySelector('[data-session-skills-writes]')?.textContent).toContain('.claude/settings.local.json');
});

test('a claude switch writes local in the session folder; a plugin and a shadowed copy have none', async () => {
    const root = await panel();
    expect(root.querySelector('[data-session-skill-switch="plug"]')).toBeNull();
    expect(root.querySelector('[data-session-skill-switch="dup"]')).toBeNull();
    (root.querySelector('[data-session-skill-switch="sme"]') as HTMLElement).click();
    await settle();
    const put = calls.find((c) => c.method === 'PUT')!;
    expect(put.body).toEqual({ harness: 'claude', file: 'local', skill: 'sme', state: 'off', project_path: '/work/lab' });
    expect(calls.filter((c) => c.path === '/sessions/ses_1/skills').length).toBe(2);
    expect(root.querySelector('[data-session-skills-hint]')?.textContent).toContain('next skill call');
});

test('turning a locally-off skill back on removes the local key', async () => {
    const root = await panel();
    (root.querySelector('[data-session-skill-switch="noisy"]') as HTMLElement).click();
    await settle();
    expect(calls.find((c) => c.method === 'PUT')!.body?.['state']).toBeNull();
});

test('a codex session says a change writes the codex config and needs a restart', async () => {
    skillsReply = {
        ...(CLAUDE() as object),
        family: 'codex',
        restart_required: true,
        skills: [skill({ name: 'sme', location_id: 'personal-codex:sme' })],
    };
    const root = await panel();
    expect(root.querySelector('[data-session-skills-writes]')?.textContent).toContain('codex config');
    (root.querySelector('[data-session-skill-switch="sme"]') as HTMLElement).click();
    await settle();
    expect(calls.find((c) => c.method === 'PUT')!.body).toEqual({ harness: 'codex', file: 'user', skill: 'sme', state: 'off' });
    expect(root.querySelector('[data-session-skills-hint]')?.textContent).toContain('restart this session');
});

test('an unsupported agent says so and draws no table', async () => {
    skillsReply = { state: 'unsupported', family: 'shell', detail: 'x' };
    const root = await panel();
    expect(root.querySelector('[data-session-skills-unsupported]')).not.toBeNull();
    expect(root.querySelector('[data-session-skill]')).toBeNull();
});

test('a skills.changed frame re-reads the skills', async () => {
    await panel();
    const before = calls.filter((c) => c.path === '/sessions/ses_1/skills').length;
    onChanged!();
    await settle();
    expect(calls.filter((c) => c.path === '/sessions/ses_1/skills').length).toBe(before + 1);
});

test('the pure rules: targets, on and the state to send', () => {
    expect(switchTarget(skill({ name: 'a', scope: 'system' }), 'codex', '/p')).toBeNull();
    expect(switchTarget(skill({ name: 'a', scope: 'project' }), 'codex', '/p')).toEqual({ harness: 'codex', file: 'project', projectPath: '/p' });
    expect(isOn(skill({ name: 'a', state: 'name-only' }))).toBe(true);
    const t = switchTarget(skill({ name: 'a' }), 'claude', '/p')!;
    expect(stateFor(skill({ name: 'a', state: 'off', state_source: 'user' }), t, true)).toBe('on');
    expect(stateFor(skill({ name: 'a' }), t, true)).toBeUndefined();
});
