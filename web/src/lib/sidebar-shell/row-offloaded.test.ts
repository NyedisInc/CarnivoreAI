/** @vitest-environment jsdom */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as Store from '../drawer/store';
import { addRows } from '../drawer/asleep';
import { buildListPlan, type PaintInput } from './plan';
import type { LegacyDrawer, SidebarRow } from './legacy';
import { restoreOffloadedRow } from './row-restore';
import { bandEvents } from './row-events';

const promptRestore = vi.fn(async (_target: { sessionUuid?: string; label?: string }) => true);
vi.mock('../offload-prompt/offload-prompt', () => ({ promptRestore: (t: { sessionUuid?: string; label?: string }) => promptRestore(t) }));
vi.mock('./company-source.svelte', () => ({ companySource: () => ({ companies: [], companyOf: () => null }), watchCompanies: () => {} }));
vi.mock('./leaders-source.svelte', async () => {
    const real = await import('./leaders');
    return { leaderIndex: () => real.indexLeaders([]), watchLeaders: () => {}, leaderRoster: () => [], projectNameOf: () => null };
});

const stubs = (): LegacyDrawer => ({ projectHeader: { ledHtml: () => '', iconHtml: () => '', iconForBand: () => null } });
const input = (rows: SidebarRow[]): PaintInput => ({ rows, density: 'compact', listing: { ok: true }, missing: [], arrangement: null, opts: { query: '' } });

interface Chip { text?: string; attrs: Record<string, string> }
interface DrawnRow { key: string; offloaded?: Chip; restore?: Chip }

function drawn(rows: SidebarRow[]): Record<string, DrawnRow> {
    const plan = buildListPlan(stubs(), input(rows))!;
    const out: Record<string, DrawnRow> = {};
    const walk = (node: unknown): void => {
        if (Array.isArray(node)) { node.forEach(walk); return; }
        if (!node || typeof node !== 'object') return;
        const o = node as Record<string, unknown>;
        if (o.type === 'session' && typeof o.key === 'string') out[o.key] = o as unknown as DrawnRow;
        Object.values(o).forEach(walk);
    };
    walk(plan.parts);
    return out;
}

function sleepers(): SidebarRow[] {
    const rows: Array<Record<string, unknown>> = [];
    addRows(rows, [
        { asleep: true, tmux_name: 'carnivore_vault', session_uuid: 'u-vault', offloaded: true, project_id: 5, project_name: 'p', agent_family: 'claude' },
        { asleep: true, tmux_name: 'carnivore_plain', session_uuid: 'u-plain', offloaded: false, project_id: 5, project_name: 'p', agent_family: 'claude' },
    ]);
    return rows as SidebarRow[];
}

beforeEach(() => {
    (globalThis as { SessionLabel?: unknown }).SessionLabel = { resolve: (r: { label?: string | null }) => r.label ?? null };
    localStorage.clear();
    Store.load();
    promptRestore.mockClear();
});

describe('the sleeping row of an offloaded conversation', () => {
    it('wears the tag and the restore button; a plain sleeper wears neither (red when the flag never reaches the row or the plan ignores it)', () => {
        const rows = drawn(sleepers());
        const vault = rows['carnivore_vault']!;
        expect(vault.offloaded?.text).toBe('offloaded');
        expect(vault.offloaded?.attrs['data-tag']).toBe('offloaded');
        expect(vault.restore?.text).toBe('restore');
        expect(vault.restore?.attrs['data-restore-offloaded']).toBe('u-vault');
        expect(rows['carnivore_plain']!.offloaded).toBeUndefined();
        expect(rows['carnivore_plain']!.restore).toBeUndefined();
    });

    it('draws the restore button always: no hover-only class or hidden attribute (red when it is revealed on hover)', () => {
        const restore = drawn(sleepers())['carnivore_vault']!.restore!;
        expect(restore.attrs.type).toBe('button');
        expect(restore.attrs.hidden).toBeUndefined();
        expect(restore.attrs.class ?? '').not.toMatch(/hover/);
    });

    it('a restore click opens the prompt for that session and wakes nothing (red when it calls the wake, or names no session)', async () => {
        const wake = vi.fn();
        (globalThis as { SessionSidebarWake?: unknown }).SessionSidebarWake = wake;
        const fetchAndRender = vi.fn(async () => {});
        const button = document.createElement('button');
        button.setAttribute('data-restore-offloaded', 'u-vault');
        const ctrl = { rows: () => [{ name: 'carnivore_vault', session_uuid: 'u-vault', label: 'vault work' }], _fetchAndRender: fetchAndRender };
        expect(await restoreOffloadedRow(ctrl as never, button, null)).toBe(true);
        expect(promptRestore).toHaveBeenCalledWith({ sessionUuid: 'u-vault', label: 'vault work' });
        expect(fetchAndRender).toHaveBeenCalledOnce();
        expect(wake).not.toHaveBeenCalled();
    });

    it('a cancelled prompt re-reads nothing (red when the drawer repaints as if it restored)', async () => {
        promptRestore.mockResolvedValueOnce(false);
        const fetchAndRender = vi.fn(async () => {});
        const button = document.createElement('button');
        button.setAttribute('data-restore-offloaded', 'u-vault');
        expect(await restoreOffloadedRow({ rows: () => [], _fetchAndRender: fetchAndRender } as never, button, null)).toBe(false);
        expect(fetchAndRender).not.toHaveBeenCalled();
    });

    it('Enter and Space on the restore button restore and neither open nor arm the row; the button is in the tab order (red when the row keys swallow it)', () => {
        const restore = vi.fn();
        const band = document.createElement('div');
        band.className = 'session-sidebar-group';
        band.innerHTML = '<div class="session-sidebar-row" data-name="carnivore_vault" data-session-uuid="u-vault" tabindex="0"><button type="button" data-restore-offloaded="u-vault">restore</button></div>';
        document.body.appendChild(band);
        const detach = (bandEvents() as (n: HTMLElement) => () => void)(band);
        const button = band.querySelector<HTMLButtonElement>('[data-restore-offloaded]')!;
        expect(button.tabIndex).toBe(0);
        button.addEventListener('click', restore);
        for (const key of ['Enter', ' ']) {
            const down = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
            button.dispatchEvent(down);
            expect(down.defaultPrevented).toBe(false);
            button.click();
        }
        expect(restore).toHaveBeenCalledTimes(2);
        expect(drawn(sleepers())['carnivore_vault']!.restore!.attrs.tabindex).toBeUndefined();
        detach();
        band.remove();
    });
});
