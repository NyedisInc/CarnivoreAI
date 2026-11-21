/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import type { RowHost } from './row-host';
import { buildRowPlan, type SessionRowPlan } from './row-plan';
import SessionRow from './SessionRow.svelte';

const BLOCKED = 'macos blocked codex 0.170 helpers: approve them in system settings > privacy & security';
const FAILED = 'codex 0.170 helpers are not answering: codex tool calls will time out';

function row(over: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        name: 'carnivore_c', label: 'c', created_by_cloude: true, status: 'working', unread: false,
        agent_family: 'codex', session_id: 'ses_c', session_uuid: 'su-c', kind: 'agent',
        last_work_at: new Date(Date.now() - 60_000).toISOString(),
        host_key: 'local', host_label: 'this machine', host_state: 'up',
        ...over,
    };
}

const helpers = (verdict: string) => ({ codex_helpers: { verdict, version: '0.170.0', text: 'x', checked_at: '2026-11-18T00:00:00Z' } });
const HOST = { actions: { offersMenu: () => false, specs: () => [] } } as unknown as RowHost;

let target: HTMLElement | null = null;
let app: unknown = null;

afterEach(() => {
    if (app) unmount(app as never);
    target?.remove();
    app = null;
    target = null;
});

function draw(r: Record<string, unknown>, density: string): HTMLElement {
    const plan = buildRowPlan(r as never, density, 'p:1', null, HOST) as SessionRowPlan;
    target = document.body.appendChild(document.createElement('div'));
    app = mount(SessionRow, { target, props: { p: plan } as never });
    flushSync();
    return target.firstElementChild as HTMLElement;
}

const reason = (el: HTMLElement) => el.querySelector('[data-flag="codex_helpers"]');

describe('the codex helper reason on a row', () => {
    for (const density of ['compact', 'cozy', 'detailed']) {
        it(`a blocked codex row says why, in the bad tone, at ${density}`, () => {
            const el = draw(row(helpers('blocked')), density);
            const line = reason(el);
            expect(line?.textContent).toBe(BLOCKED);
            expect(line?.getAttribute('data-tone')).toBe('bad');
            expect(el.getAttribute('data-row-flag')).toBe('bad');
        });
    }

    it('a host failure names the version too', () => {
        expect(reason(draw(row(helpers('host_failed')), 'compact'))?.textContent).toBe(FAILED);
    });

    it('nothing is drawn for ok, not applicable, a null field or a claude row', () => {
        for (const over of [helpers('ok'), helpers('not_applicable'), { codex_helpers: null }, {}]) {
            const el = draw(row(over), 'compact');
            expect(reason(el)).toBeNull();
            expect(el.hasAttribute('data-row-flag')).toBe(false);
            unmount(app as never);
            app = null;
            target?.remove();
        }
        expect(reason(draw(row({ ...helpers('blocked'), agent_family: 'claude' }), 'detailed'))).toBeNull();
    });
});
