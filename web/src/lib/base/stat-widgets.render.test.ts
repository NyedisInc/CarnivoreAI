/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, test } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount, type Component } from 'svelte';

import ChartFrame from './ChartFrame.svelte';
import StatTile from './StatTile.svelte';
import { statTileClass } from './classes';

let mounted: Record<string, unknown>[] = [];

afterEach(() => {
    for (const m of mounted) unmount(m);
    mounted = [];
    document.body.innerHTML = '';
});

/** A snippet that renders fixed markup. */
const html = (markup: string) => createRawSnippet(() => ({ render: () => markup }));

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function show(component: Component<any>, props: Record<string, unknown>): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(component, { target, props }) as Record<string, unknown>);
    flushSync();
    return target;
}

const read = (path: string): string => readFileSync(path, 'utf8');

const FULL = {
    label: 'tokens', figure: '12.4k', unit: 'tok', delta: 'up 4%', deltaNote: 'vs prior', deltaTone: 'up', meter: 40,
    sub: '3 asleep', notice: 'one source failed', tone: '--oc-green',
    icon: html('<i class="glyph"></i>'), spark: html('<b class="bars"></b>'), foot: html('<dl class="readouts"></dl>'),
};

describe('StatTile parts', () => {
    test('a regular flat tile draws every part it was given', () => {
        const root = show(StatTile, { ...FULL, size: 'regular', mode: 'flat' });
        const q = (selector: string) => root.querySelector(selector);
        expect(q('.oc-stat-tile__label')?.textContent).toBe('tokens');
        expect(q('.oc-stat-tile__figure')?.textContent).toBe('12.4k');
        expect(q('.oc-stat-tile__unit')?.textContent).toBe('tok');
        expect(q('.oc-stat-tile__delta--up b')?.textContent).toBe('up 4%');
        expect(q('.oc-stat-tile__notice')?.getAttribute('role')).toBe('alert');
        expect(q('.oc-stat-tile__spark .bars')).not.toBeNull();
        expect(q('.oc-stat-tile__meter-fill')?.getAttribute('style')).toContain('40%');
        expect(q('.oc-stat-tile__sub')?.textContent).toBe('3 asleep');
        expect(q('.oc-stat-tile__extra .readouts')).not.toBeNull();
        expect(q('.glyph')).not.toBeNull();
    });

    test('a compact tile hides the change, a line tile keeps only the label and the figure', () => {
        const compact = show(StatTile, { ...FULL, size: 'compact', mode: 'flat' });
        expect(compact.querySelector('.oc-stat-tile--compact')).not.toBeNull();
        expect(compact.querySelector('.oc-stat-tile__delta')).toBeNull();
        expect(compact.querySelector('.oc-stat-tile__spark')).not.toBeNull();
        const line = show(StatTile, { ...FULL, size: 'regular', mode: 'line' });
        expect(line.querySelector('.oc-stat-tile--line')).not.toBeNull();
        expect(line.querySelector('.oc-stat-tile__figure')).not.toBeNull();
        for (const part of ['delta', 'spark', 'foot', 'notice', 'extra', 'meta']) expect(line.querySelector(`.oc-stat-tile__${part}`)).toBeNull();
    });

    test('a graph tile and a sentence figure carry their modifiers', () => {
        const graph = show(StatTile, { label: 'a', figure: 'not measured', kind: 'note', mode: 'graph' });
        expect(graph.querySelector('.oc-stat-tile--graph.oc-stat-tile--note')).not.toBeNull();
        expect(graph.querySelector('.oc-stat-tile__figure--note')).not.toBeNull();
        expect(statTileClass({ size: 'regular', mode: 'flat', kind: 'value', framed: false, display: false, editing: false })).toBe('oc-stat-tile');
    });

    test('framed draws the card edge, an unframed tile inside a card frame does not; the tone and measured size ride as variables', () => {
        const framed = show(StatTile, { label: 'a', figure: '1', tone: '--oc-cyan', figurePx: 30 });
        const root = framed.querySelector<HTMLElement>('.oc-stat-tile--framed');
        expect(root?.style.getPropertyValue('--_stat-tone')).toBe('var(--oc-cyan)');
        expect(root?.style.getPropertyValue('--_stat-figure')).toBe('30px');
        expect(show(StatTile, { label: 'a', figure: '1', framed: false }).querySelector('.oc-stat-tile--framed')).toBeNull();
    });

    test('empty replaces everything under the head', () => {
        const root = show(StatTile, { ...FULL, empty: html('<p class="nothing">no data</p>') });
        expect(root.querySelector('.nothing')).not.toBeNull();
        expect(root.querySelector('.oc-stat-tile__figure')).toBeNull();
    });
});

describe('ChartFrame', () => {
    test('is a labelled column for the card parts, with the density tier as a modifier and no title of its own', () => {
        const root = show(ChartFrame, { size: 'tile', label: 'tokens', busy: true, class: 'analytics-cell', children: html('<div class="oc-chart-frame__plot"></div>') });
        const frame = root.querySelector('section.oc-chart-frame');
        expect(frame?.classList.contains('oc-chart-frame--tile')).toBe(true);
        expect(frame?.classList.contains('analytics-cell')).toBe(true);
        expect(frame?.getAttribute('aria-label')).toBe('tokens');
        expect(frame?.getAttribute('aria-busy')).toBe('true');
        expect(frame?.querySelector('.oc-chart-frame__plot')).not.toBeNull();
        expect(frame?.querySelector('h1,h2,h3,h4,[role=heading]')).toBeNull();
    });
});

describe('one side inset', () => {
    const tile = read('src/lib/base/stat-tile.css');
    const chart = read('src/lib/base/chart-frame.css');

    test('neither stylesheet carries a raw spacing length', () => {
        for (const css of [tile, chart]) {
            const stripped = css.replace(/\/\*[\s\S]*?\*\//g, '');
            const raw = [...stripped.matchAll(/(?:padding|margin)[a-z-]*\s*:\s*([^;]+);|(?:row-|column-)?gap\s*:\s*([^;]+);/g)]
                .map((m) => (m[1] ?? m[2] ?? '').replace(/var\([^()]*\)/g, ''))
                .filter((value) => /\d+(?:\.\d+)?(?:px|rem|em)\b/.test(value));
            expect(raw).toEqual([]);
        }
    });

    test('the stat tile, the chart body and the host header title read the same inset token', () => {
        const head = read('src/opscenter/shell/WidgetHead.svelte');
        const strip = read('src/opscenter/shell/CellFrame.svelte');
        const token = read('src/opscenter/tokens.css');
        expect(token).toMatch(/--oc-widget-inset:\s*var\(--oc-space-3\);/);
        expect(head).toMatch(/\.oc-frame-title \{[^}]*padding:\s*0 var\(--oc-widget-inset\);/);
        expect(strip).toMatch(/\.oc-frame-strip \{[^}]*padding:\s*0 var\(--oc-widget-inset\);/);
        expect(tile).toMatch(/--_stat-pad-x:\s*var\(--oc-widget-inset\);/);
        expect(tile).toMatch(/--_stat-pad-y:\s*var\(--oc-space-3\);/);
        expect(tile).toMatch(/--_stat-pad-top:\s*var\(--_stat-pad-y\);/);
        expect(tile).toMatch(/\.oc-stat-tile--line\.oc-stat-tile--compact \{[^}]*--_stat-pad-y:\s*var\(--oc-space-2\);/);
        expect(token).not.toContain('--oc-widget-inset-compact');
        for (const part of ['headline', 'note', 'facts', 'context', 'list', 'plot']) {
            expect(chart).toMatch(new RegExp(`\\.oc-chart-frame__${part} \\{[^}]*var\\(--oc-widget-inset\\)`));
        }
        expect(chart).toMatch(/\.oc-chart-frame__head \{[^}]*var\(--oc-widget-inset\)/);
    });

    test('the analytics card no longer sets its own side inset', () => {
        const timeline = read('src/opscenter/cells/analytics/TimelineView.svelte');
        const style = timeline.slice(timeline.indexOf('<style'));
        expect(style).not.toMatch(/(?:padding|margin)[a-z-]*:[^;}]*\b(?:18|36)px/);
    });
});

describe('the headline clear inset', () => {
    const chart = read('src/lib/base/chart-frame.css');
    const token = read('src/opscenter/tokens.css');
    const timeline = read('src/opscenter/cells/analytics/TimelineView.svelte');

    test('the headline, the head and the empty state reserve the clear inset on the right, so no word runs under the opener', () => {
        for (const part of ['head', 'headline', 'empty']) {
            expect(chart).toMatch(new RegExp(`\\.oc-chart-frame__${part} \\{[^}]*padding:[^;]*var\\(--oc-widget-clear\\)`));
        }
        expect(chart).toMatch(/\.oc-chart-frame__headline > span \{[^}]*text-overflow:\s*ellipsis/);
    });

    test('the clear is the right inset plus a 24px opener footprint, wider than the 22px glyph box and its offset', () => {
        expect(token).toMatch(/--oc-widget-clear:\s*calc\(var\(--oc-widget-inset\) \+ var\(--oc-space-5\)\);/);
        expect(token).toMatch(/--oc-space-5:\s*24px;/);
        expect(token).toMatch(/--oc-space-2:\s*8px;/);
    });

    test('the touch opener sits flush right so its 44px glyph box stays inside the clear', () => {
        expect(timeline).toMatch(/@media \(max-width: 1023px\) \{\s*\.analytics-open \{ right: 0; \}/);
    });

    test('the bands above the plot never shrink, only the list and the plot give way', () => {
        expect(chart).toMatch(/\.oc-chart-frame__head,\s*\.oc-chart-frame__headline,\s*\.oc-chart-frame__facts,\s*\.oc-chart-frame__context \{\s*flex: none;/);
    });

    test('the top projects board is a chart frame that shows whole rows only', () => {
        const board = read('src/opscenter/viz/LeaderboardRenderer.svelte');
        expect(board).toMatch(/<ChartFrame /);
        expect(board).toMatch(/use:wholeItems/);
        expect(board).not.toMatch(/overflow-y:\s*auto/);
    });
});

