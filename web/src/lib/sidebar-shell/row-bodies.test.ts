/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import { indexLeaders } from './leaders';
import type { RowHost } from './row-host';
import { buildRowPlan, type SessionRowPlan } from './row-plan';
import SessionRow from './SessionRow.svelte';

const iso = (secsAgo: number) => new Date(Date.now() - secsAgo * 1000).toISOString();
const inSecs = (secs: number) => new Date(Date.now() + secs * 1000).toISOString();

function row(over: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        name: 'cloude_a', label: 'a', created_by_cloude: true, status: 'working', unread: false,
        agent_family: 'claude', session_id: 'ses_a', session_uuid: 'su-a', kind: 'agent',
        running_model: 'claude-opus-5', running_model_effort: 'high', running_model_tier: 5,
        running_context_used_pct: 71, subagents_running: 0, subagents_total: 0, background_open: 0,
        timers_live: 0, workflow_active: false, last_work_at: iso(120),
        host_key: 'local', host_label: 'this machine', host_state: 'up',
        ...over,
    };
}

const HOST = {
    actions: { offersMenu: () => false, specs: () => [{ attrs: { type: 'button', class: 'session-sidebar-row-delete' }, text: 'restart' }] },
} as unknown as RowHost;

let target: HTMLElement | null = null;
let app: unknown = null;

afterEach(() => {
    if (app) unmount(app as never);
    target?.remove();
    app = null;
    target = null;
});

function draw(r: Record<string, unknown>, density: string, tweak?: (p: SessionRowPlan) => void): HTMLElement {
    const plan = buildRowPlan(r as never, density, 'p:1', null, HOST) as SessionRowPlan;
    if (tweak) tweak(plan);
    target = document.body.appendChild(document.createElement('div'));
    app = mount(SessionRow, { target, props: { p: plan } });
    flushSync();
    return target.querySelector('.session-sidebar-row') as HTMLElement;
}

const text = (el: Element | null | undefined) => (el?.textContent ?? '').replace(/\s+/g, ' ').trim();
const right = (el: HTMLElement) => el.querySelector('.session-sidebar-row-main .session-row-body__right');

describe('compact is unchanged', () => {
    it('draws no body, no right-hand value and keeps its chips', () => {
        const el = draw(row({ subagents_running: 2, subagents_total: 3 }), 'compact');
        expect(el.hasAttribute('data-row-body')).toBe(false);
        expect(el.querySelector('.session-row-body, .session-row-body__right')).toBeNull();
        expect(el.querySelector('.session-sidebar-row-main .session-sidebar-row-model')).not.toBeNull();
    });
});

describe('cozy: the meter', () => {
    it('line one ends in the controls, line two is the model, the live work as counts, then the effort at the right', () => {
        const el = draw(row({
            subagents_running: 3, subagents_total: 5, background_open: 2, timers_live: 1, timers_next_fire_at: inSecs(14 * 60),
        }), 'cozy');
        expect(el.getAttribute('data-row-body')).toBe('cozy');
        expect(right(el)).toBeNull();
        expect(el.querySelector('.session-row-body__right')).toBeNull();
        const body = el.querySelector('.session-row-body--cozy')!;
        expect(body.querySelector('.session-sidebar-row-model')?.getAttribute('data-model-tier')).toBe('5');
        expect(text(body.querySelector('.session-row-body__model'))).toBe('opus-5');
        const effort = body.querySelector('.session-row-body__effort')!;
        expect(effort.hasAttribute('aria-label')).toBe(false);
        expect(text(effort.querySelector('.oc-visually-hidden'))).toBe('effort');
        expect(effort.lastChild?.textContent?.trim()).toBe('high');
        expect(text(effort)).toBe('effort high');
        expect(body.lastElementChild).toBe(body.querySelector('.session-row-body__effort'));
        const parts = Array.from(body.querySelectorAll('.session-row-live__part'));
        expect(parts.map((p) => p.getAttribute('data-live'))).toEqual(['agents', 'shells', 'timers']);
        expect(parts.map((p) => text(p))).toEqual(['3/5', '2', '14m']);
        expect(parts[0]?.getAttribute('data-subagents-session-id')).toBe('ses_a');
        expect(parts[2]?.getAttribute('data-timers-session-id')).toBe('ses_a');
        expect(el.querySelector('.subagent-count--button, .timer-chip, .session-sidebar-row-when, .session-sidebar-row-agents-icon')).toBeNull();
        expect(el.querySelector('.session-sidebar-row-main .session-sidebar-row-model')).toBeNull();
        expect(el.getAttribute('title')).toBeNull();
    });

    it('draws no context percent at any tier; the gauge along the bottom edge carries it', () => {
        for (const pct of [83, 96]) {
            const el = draw(row({ running_context_used_pct: pct }), 'cozy');
            expect(el.querySelector('.session-row-body__right')).toBeNull();
            expect(text(el)).not.toContain(`${pct}%`);
            expect(el.querySelector('.session-sidebar-row-context')).not.toBeNull();
        }
    });

    it('never says "no live work" at cozy, and draws no counts when nothing runs or the counts are unmeasured (detailed keeps its words)', () => {
        const idle = draw(row(), 'cozy');
        expect(idle.querySelector('.session-row-live')).toBeNull();
        expect(text(idle)).not.toContain('no live work');
        expect(text(draw(row(), 'detailed').querySelector('.session-row-live'))).toBe('no live work');
        const unmeasured = draw(row({ subagents_running: null, background_open: null, timers_live: null }), 'cozy');
        expect(unmeasured.querySelector('.session-row-live')).toBeNull();
        const parked = draw(row({ parked_summary: 'background shell b1 parked' }), 'cozy');
        const glyph = parked.querySelector('.session-row-live__part[data-live="shells"]');
        expect(glyph?.getAttribute('title')).toBe('background shell b1 parked');
        expect(parked.querySelector('.session-row-live__none, .session-row-live__count')).toBeNull();
    });

    it('a dead row says when the process exited and carries its restart; an asleep row says when it last worked', () => {
        const dead = draw(row({ status: 'dead', last_work_at: iso(2 * 3600) }), 'cozy');
        expect(text(dead.querySelector('.session-row-body__ended'))).toBe('process exited 2h ago');
        expect(dead.querySelector('.session-row-body .session-sidebar-row-delete')).not.toBeNull();
        expect(dead.querySelector('.session-sidebar-row-controls-cluster .session-sidebar-row-delete')).toBeNull();
        expect(right(dead)).toBeNull();
        const asleep = draw(row({ status: 'asleep', asleep: true, last_work_at: iso(86400 + 60) }), 'cozy');
        expect(text(asleep.querySelector('.session-row-body__ended'))).toBe('asleep, worked 1d ago');
        expect(right(asleep)).toBeNull();
    });

    it('an unknown effort leaves the slot out entirely', () => {
        const el = draw(row({ running_model_effort: null }), 'cozy');
        expect(el.querySelector('.session-row-body__effort')).toBeNull();
        expect(text(el.querySelector('.session-row-body__model'))).toBe('opus-5');
    });
});

describe('detailed: the triage stack', () => {
    it('a calm row is two lines: state word, then live work and last worked', () => {
        const el = draw(row({ subagents_running: 3, subagents_total: 5, background_open: 2 }), 'detailed');
        expect(el.getAttribute('data-row-body')).toBe('detailed');
        expect(el.hasAttribute('data-row-flag')).toBe(false);
        expect(text(right(el))).toBe('working');
        expect(right(el)?.getAttribute('data-tone')).toBe('ok');
        const lines = el.querySelectorAll('.session-row-body--detailed > .session-row-body__line');
        expect(lines.length).toBe(1);
        expect(text(lines[0]?.querySelector('.session-row-live'))).toBe('3/5agents2shells');
        expect(text(lines[0]?.querySelector('.session-row-body__when'))).toBe('2m ago');
        expect(el.querySelector('.session-sidebar-row-meta, .session-row__subagent-count')).toBeNull();
    });

    it('stacks every active flag, loudest first, in its hue; the hairline takes the loudest', () => {
        const el = draw(row({
            status: 'question', host_key: 'peer-studio', host_label: 'studio', host_state: 'disconnected',
            agent_update: { running: '2.1.290', installed: '2.1.301', ready: true }, running_context_used_pct: 83,
        }), 'detailed');
        const flags = Array.from(el.querySelectorAll('.session-row-body__flag'));
        expect(flags.map((f) => f.getAttribute('data-flag'))).toEqual(['permission', 'host', 'update', 'context']);
        expect(flags.map((f) => f.getAttribute('data-tone'))).toEqual(['warn', 'bad', 'info', 'ctx4']);
        expect(flags.map((f) => text(f))).toEqual([
            'your turn - the agent needs your permission', 'studio offline',
            'update ready 2.1.290 to 2.1.301', 'context 83% full',
        ]);
        expect(el.getAttribute('data-row-flag')).toBe('warn');
    });

    it('a dead row is its exited flag with the restart; an asleep row says when it worked', () => {
        const dead = draw(row({ status: 'dead', last_work_at: iso(2 * 3600) }), 'detailed');
        expect(text(right(dead))).toBe('dead');
        const flag = dead.querySelector('.session-row-body__flag[data-flag="exited"]');
        expect(text(flag?.querySelector('.session-row-body__flag-words'))).toBe('process exited 2h ago');
        expect(flag?.querySelector('.session-sidebar-row-delete')).not.toBeNull();
        expect(dead.querySelector('.session-row-body__foot')).toBeNull();
        const asleep = draw(row({ status: 'asleep', asleep: true, last_work_at: iso(86400 + 60) }), 'detailed');
        expect(right(asleep)).toBeNull();
        expect(text(asleep.querySelector('.session-row-body__ended'))).toBe('asleep, worked 1d ago');
    });
});

describe('the rank tag', () => {
    it('a Swarm task agent is tagged from the Swarm roster at cozy and detailed', () => {
        const idx = indexLeaders([{ id: 9, rank: 'task', display_name: 'fix', session_row_id: 7 }]);
        expect(idx.workerRank?.({ name: 'x', session_row_id: 7 })).toBe('task');
        expect(idx.workerRank?.({ name: 'x', session_row_id: 8 })).toBeNull();
        for (const density of ['cozy', 'detailed']) {
            const el = draw(row({ host_key: 'peer-studio', host_label: 'studio' }), density, (p) => { p.body!.rankTag = 'task'; });
            const main = Array.from(el.querySelector('.session-sidebar-row-main')!.children).map((c) => c.className);
            const at = (cls: string) => main.findIndex((c) => c.includes(cls));
            expect(at('session-row-body__rank')).toBeGreaterThan(at('session-sidebar-row-name'));
            expect(at('session-sidebar-row-host')).toBeGreaterThan(at('session-row-body__rank'));
            if (density === 'detailed') expect(at('session-row-body__right')).toBeGreaterThan(at('session-sidebar-row-host'));
            else expect(at('session-row-body__right')).toBe(-1);
        }
    });
});
