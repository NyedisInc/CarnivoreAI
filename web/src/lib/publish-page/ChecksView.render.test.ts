/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { ReportGate, SubmissionReport } from '../catalog/publish';
import { createActions } from './actions';
import { parseMine } from './api';
import ChecksView from './ChecksView.svelte';
import { FILL_MS } from './checks-model';
import type { PageHost } from './host';
import { createPageStore } from './page-store.svelte';
import { GATE_IDS } from './report-format';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null): string => i18n.t(key, params);

let app: Record<string, unknown> | null = null;
beforeEach(() => vi.useFakeTimers());
afterEach(() => {
    if (app) unmount(app as never);
    app = null;
    document.body.innerHTML = '';
    vi.useRealTimers();
});

const gate = (id: string): ReportGate => ({ id, result: 'pass', code: '', fix: '', findings: [] }) as unknown as ReportGate;
const report = (): SubmissionReport => ({ outcome: '', gates: GATE_IDS.map(gate) }) as unknown as SubmissionReport;

describe('the rail fill', () => {
    it('keeps stepping when a second read replaces the report object (X7-9)', () => {
        const fake = {} as unknown as PageHost;
        const store = createPageStore({ host: fake, navigate: vi.fn(), t });
        const actions = createActions({ store, host: fake, t });
        store.mine = parseMine({ submissions: [{ submission_id: 'ab12', status: 'approved', gate_state: 'passed', kind: 'skill', name: 'notes', version: '1.0.0', created_at: '2026-10-05T00:00:00Z' }] });
        store.signedIn = true;
        store.mid = { ev: 'ab12:gates' };
        store.railFill['ab12'] = true;
        store.reports['ab12'] = report();
        const target = document.createElement('div');
        document.body.appendChild(target);
        app = mount(ChecksView, { target, props: { store, actions, t } as never }) as never;
        flushSync();
        const running = (): number => target.querySelectorAll('.d-tick[data-result="running"]').length;
        expect(running()).toBe(GATE_IDS.length);
        vi.advanceTimersByTime(50);
        store.reports['ab12'] = report();
        flushSync();
        expect(running()).toBe(GATE_IDS.length);
        vi.advanceTimersByTime(FILL_MS);
        flushSync();
        expect(running()).toBe(GATE_IDS.length - 1);
        vi.advanceTimersByTime(FILL_MS * 3);
        flushSync();
        expect(running()).toBe(GATE_IDS.length - 4);
        vi.advanceTimersByTime(FILL_MS * GATE_IDS.length);
        flushSync();
        expect(running()).toBe(0);
    });
});
