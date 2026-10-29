/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('../../opscenter/api/auth.svelte', () => ({
    auth: { state: 'signed-in' },
    initAuth: async () => {},
    ApiError: class ApiError extends Error {},
    authFetch: async () => null,
}));

import PipelineStatusPanel from './PipelineStatusPanel.svelte';
import { setLocale } from '../i18n/index.svelte';
import type { Fetcher, PipelineStatus, PluginStatus, RecentRun } from './api';
import { detailLines, pluginIcon, pluginSquares, squareState } from './squares';


setLocale('en');

const squaresCss = readFileSync(join(process.cwd(), 'src/lib/pipeline-status/pipeline-squares.css'), 'utf8');

const NOW = Date.now() / 1000;

const plugin = (over: Partial<PluginStatus> = {}): PluginStatus =>
    ({ lag: { files: 0, seconds: 0 }, failures: 0, last_error: null, rebuilding: false, last_delivery_at: null, runs: 0, ...over });

const run = (id: string, ago: number, over: Partial<RecentRun> = {}): RecentRun => ({
    plugin: id, kind: 'delivery', scope: 'machine', session_uuid: null, session: null, project_id: null, project: null,
    conversation_id: 'c', family: 'claude', trigger: 'live', finished_at: NOW - ago, duration_ms: 3, runs: 2, events: 1,
    outcome: 'ok', error: null, ...over,
});

function fourStates(over: Partial<PipelineStatus> = {}): PipelineStatus {
    return {
        state: 'behind', lag: { files: 4, seconds: 30 }, last_delivery_at: null, stalled_since: null, rebuilding: ['words'],
        plugins: {
            stats: plugin({ last_delivery_at: NOW - 12, runs: 7 }),
            deepsearch: plugin({ lag: { files: 4, seconds: 30 } }),
            summary: plugin({ failures: 2, last_error: 'KeyError', runs: 1 }),
            words: plugin({ rebuilding: true }),
        },
        recent: [run('stats', 12), run('stats', 300, { runs: 5 }), run('summary', 60, { outcome: 'failed', error: 'KeyError' })],
        running: [],
        queue: { items: [], total: 0 },
        ...over,
    };
}

const apps: ReturnType<typeof mount>[] = [];
beforeEach(() => { document.body.innerHTML = ''; });
afterEach(() => { for (const app of apps.splice(0)) unmount(app); document.body.innerHTML = ''; });

async function settle(): Promise<void> {
    for (let i = 0; i < 10; i += 1) {
        await Promise.resolve();
        await tick();
    }
    flushSync();
}

async function compactPanel(body: PipelineStatus): Promise<{ target: HTMLElement; calls: string[] }> {
    const calls: string[] = [];
    const fetcher = (async (path: string, init?: RequestInit) => {
        calls.push(`${init?.method ?? 'GET'} ${path}`);
        return path === '/pipeline/status' ? body : { plugin: 'stats' };
    }) as unknown as Fetcher;
    const target = document.createElement('div');
    document.body.appendChild(target);
    apps.push(mount(PipelineStatusPanel, { target, props: { fetcher, compact: true } }));
    await settle();
    return { target, calls };
}

const square = (target: HTMLElement, id: string) => target.querySelector(`[data-ps-square="${id}"] [data-ps="square"]`) as HTMLButtonElement;
function enter(target: HTMLElement, id: string, type = 'mouse'): void {
    target.querySelector(`[data-ps-square="${id}"]`)!.dispatchEvent(new PointerEvent('pointerenter', { pointerType: type }));
    flushSync();
}

function tabTo(el: HTMLElement): void {
    (document.activeElement ?? document.body).dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    el.focus();
    flushSync();
}

function tap(target: HTMLElement, id: string, type: string): void {
    enter(target, id, type);
    square(target, id).focus();
    square(target, id).click();
    flushSync();
}

const detail = (target: HTMLElement) => target.querySelector('[data-ps="detail"]');
const facts = (target: HTMLElement) =>
    Object.fromEntries([...target.querySelectorAll('[data-ps-fact]')].map((el) => [el.getAttribute('data-ps-fact'), el.textContent?.trim()]));

describe('the square model', () => {
    test('a contributed square draws its contributor\'s manifest icon, a registry square its own', () => {
        const status = fourStates({ recent: [run('backups', 5, { scope: 'plugin', contributor: 'save' })] });
        const squares = pluginSquares(status);
        expect(squares.find((square) => square.id === 'backups')?.icon).toBe(pluginIcon('save'));
        expect(pluginIcon('save')).toBe('archive');
        expect(pluginIcon('save')).not.toBe(pluginIcon('stats'));
        expect(squares.find((square) => square.id === 'stats')?.icon).toBe(pluginIcon('stats'));
    });
    test('a square state follows the deleted widget: ok, behind, failing, off; a rebuild is behind', () => {
        expect(squareState('caught_up', plugin())).toBe('ok');
        expect(squareState('behind', plugin({ lag: { files: 1, seconds: 2 } }))).toBe('behind');
        expect(squareState('behind', plugin({ failures: 1 }))).toBe('failing');
        expect(squareState('stalled', plugin({ lag: { files: 1, seconds: 2 } }))).toBe('failing');
        expect(squareState('stalled', plugin())).toBe('ok');
        expect(squareState('rebuilding', plugin({ rebuilding: true }))).toBe('behind');
        expect(squareState('off', plugin({ failures: 3 }))).toBe('off');
    });

    test('the last delivery and the runs are the engine\'s own per-plugin figures, never the chart rows', () => {
        const status = fourStates({ recent: [run('stats', 5, { outcome: 'failed', error: 'KeyError', runs: 1 })] });
        const [stats, , summary] = pluginSquares(status);
        expect(stats?.lastDeliveryAt).toBe(NOW - 12);
        expect(stats?.runs).toBe(7);
        expect(summary?.lastDeliveryAt).toBeNull();
        expect(summary?.runs).toBe(1);
        expect(detailLines(summary!, NOW).map((line) => line.key)).toEqual([
            'pipeline.square.no_backlog', 'pipeline.square.no_delivery', 'pipeline.square.failing', 'pipeline.square.runs',
        ]);
    });

    test('a square wears its plugin\'s manifest icon, and a plugin with no manifest draws the chart', () => {
        expect(pluginIcon('deepsearch')).toBe('deep-search');
        expect(pluginIcon('stats')).toBe('chart');
    });

    test('the stylesheet draws each state by shape and token, as the deleted widget did', () => {
        const css = squaresCss.replace(/\/\*[\s\S]*?\*\//g, '');
        const rule = (selector: string): string => {
            const at = css.indexOf(`${selector} {`);
            expect(at, selector).toBeGreaterThanOrEqual(0);
            return css.slice(at, css.indexOf('}', at));
        };
        const square = rule('.ps-sq__square');
        expect(square).toMatch(/width:\s*28px/);
        expect(square).toMatch(/height:\s*28px/);
        const mark = rule('.ps-sq__mark');
        expect(mark).toMatch(/border-radius:\s*50%/);
        expect(mark).toMatch(/background:\s*currentColor/);
        expect(mark).toMatch(/position:\s*absolute/);
        expect(rule(".ps-sq__mark[data-mark='behind']")).toMatch(/background:\s*transparent;\s*border:\s*1\.5px solid currentColor/);
        const failing = rule(".ps-sq__mark[data-mark='failing']");
        expect(failing).toMatch(/border-radius:\s*0/);
        expect(failing).toMatch(/rotate\(45deg\)/);
        expect(rule(".ps-sq__mark[data-mark='off']")).toMatch(/height:\s*2px/);
        expect(rule(".ps-sq__square[data-state='ok']")).toMatch(/color:\s*var\(--oc-green\)/);
        expect(rule(".ps-sq__square[data-state='behind']")).toMatch(/color:\s*var\(--oc-yellow\)/);
        expect(rule(".ps-sq__square[data-state='failing']")).toMatch(/color:\s*var\(--oc-coral\)/);
        expect(square).toMatch(/color:\s*var\(--oc-text-dim\)/);
    });
});

describe('the status squares', () => {
    test('one square per plugin the engine reports, in its order, with the status line beside the row', async () => {
        const { target } = await compactPanel(fourStates());
        const ids = [...target.querySelectorAll('[data-ps-square]')].map((el) => el.getAttribute('data-ps-square'));
        expect(ids).toEqual(['stats', 'deepsearch', 'summary', 'words']);
        const top = target.querySelector('[data-ps="top"]');
        expect(top?.querySelector('[data-ps="squares"]')).not.toBeNull();
        expect(top?.querySelector('[data-ps="line"] [data-ps="state"]')?.textContent?.trim()).toBe('behind: 4 files, 0m 30s');
        expect(target.querySelector('[data-ps="rows"]')).toBeNull();
        expect(square(target, 'deepsearch').querySelector('svg')?.getAttribute('data-icon')).toBe('deep-search');
        expect(square(target, 'stats').querySelector('svg')?.getAttribute('data-icon')).toBe('chart');
        expect(square(target, 'stats').textContent?.trim()).toBe('');
    });

    test('each state wears its own shape mark, and a rebuild says the word', async () => {
        const { target } = await compactPanel(fourStates());
        const mark = (id: string) => target.querySelector(`[data-ps-square="${id}"] .ps-sq__mark`)?.getAttribute('data-mark');
        expect([mark('stats'), mark('deepsearch'), mark('summary'), mark('words')]).toEqual(['ok', 'behind', 'failing', 'behind']);
        expect(target.querySelector('[data-ps-square="words"] [data-ps="rebuilding"]')?.textContent?.trim()).toBe('rebuilding');
        expect(target.querySelector('[data-ps-square="stats"] [data-ps="rebuilding"]')).toBeNull();
        expect(square(target, 'deepsearch').getAttribute('aria-label')).toBe('deep search, behind');
        expect(square(target, 'stats').getAttribute('aria-label')).toBe('stats, caught up');
    });

    test('an engine not started answers only its state: no row draws and the status line says off', async () => {
        const { target } = await compactPanel({ state: 'off' } as unknown as PipelineStatus);
        expect(target.querySelector('[data-ps="squares"]')).toBeNull();
        expect(target.querySelector('[data-ps="top"] [data-ps="line"] [data-ps="state"]')?.textContent?.trim()).toBe('the pipeline is not running');
    });

    test('an engine reporting plugins while off draws each as the off dash', async () => {
        const { target } = await compactPanel(fourStates({ state: 'off' }));
        const marks = [...target.querySelectorAll('.ps-sq__mark')].map((el) => el.getAttribute('data-mark'));
        expect(marks).toEqual(['off', 'off', 'off', 'off']);
    });

    test('a mouse hovering a square shows its detail: backlog and lag, last delivery, last error, runs; leaving closes it', async () => {
        const { target } = await compactPanel(fourStates());
        expect(detail(target)).toBeNull();
        enter(target, 'deepsearch', 'touch');
        expect(detail(target)).toBeNull();
        enter(target, 'deepsearch');
        expect(detail(target)?.getAttribute('data-ps-detail')).toBe('deepsearch');
        expect(facts(target)).toEqual({
            backlog: '4 files waiting, oldest 0m 30s', delivery: 'no delivery since the server started', error: 'no errors',
            runs: '0 runs since the server started',
        });
        enter(target, 'stats');
        expect(facts(target)).toMatchObject({ backlog: 'nothing waiting', delivery: 'last delivery 12s ago', runs: '7 runs since the server started' });
        target.querySelector('[data-ps="squares"]')!.dispatchEvent(new PointerEvent('pointerleave', { pointerType: 'mouse' }));
        flushSync();
        expect(detail(target)).toBeNull();
    });

    test('keyboard focus shows the detail; Escape closes it', async () => {
        const { target } = await compactPanel(fourStates());
        tabTo(square(target, 'summary'));
        const shown = detail(target);
        expect(shown?.getAttribute('data-ps-detail')).toBe('summary');
        expect(shown?.getAttribute('role')).toBe('tooltip');
        expect(facts(target).error).toBe('2 failing, last error KeyError');
        expect(target.querySelector('[data-ps="detail-state"]')?.textContent?.trim()).toBe('failing');
        square(target, 'summary').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        flushSync();
        expect(detail(target)).toBeNull();
    });

    test('the squares carry no rebuild control; keyboard focus on a square still opens its detail', async () => {
        const { target, calls } = await compactPanel(fourStates());
        expect(target.querySelectorAll('[data-ps="rebuild"]')).toHaveLength(0);
        expect(target.querySelectorAll('[data-ps-square] button')).toHaveLength(4);
        expect(target.querySelector('[data-ps="rebuild-panel"]')).toBeNull();
        tabTo(square(target, 'stats'));
        expect(detail(target)?.getAttribute('data-ps-detail')).toBe('stats');
        expect(calls.filter((call) => call.startsWith('POST'))).toEqual([]);
    });

    test('every square is always described by a hidden copy of its detail, open or not', async () => {
        const { target } = await compactPanel(fourStates());
        expect(detail(target)).toBeNull();
        const id = square(target, 'summary').getAttribute('aria-describedby');
        const desc = id ? document.getElementById(id) : null;
        expect(desc?.classList.contains('oc-visually-hidden')).toBe(true);
        expect(desc?.textContent?.trim()).toBe(
            'nothing waiting; no delivery since the server started; 2 failing, last error KeyError; 1 runs since the server started');
        expect(square(target, 'stats').getAttribute('aria-describedby')).not.toBe(id);
    });

    test('a tap pins the detail open, a second tap closes it, though the tap also hovered and focused it', async () => {
        const { target } = await compactPanel(fourStates());
        tap(target, 'deepsearch', 'touch');
        expect(detail(target)?.getAttribute('data-ps-detail')).toBe('deepsearch');
        expect(square(target, 'deepsearch').getAttribute('aria-expanded')).toBe('true');
        tap(target, 'deepsearch', 'touch');
        expect(detail(target)).toBeNull();
        tap(target, 'stats', 'mouse');
        expect(detail(target)?.getAttribute('data-ps-detail')).toBe('stats');
        tap(target, 'stats', 'mouse');
        expect(detail(target)).toBeNull();
    });

    test('a press outside closes a detail held open by a click', async () => {
        const { target } = await compactPanel(fourStates());
        tap(target, 'stats', 'mouse');
        expect(detail(target)).not.toBeNull();
        document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
        flushSync();
        expect(detail(target)).toBeNull();
    });
});
