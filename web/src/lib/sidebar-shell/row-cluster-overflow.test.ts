/* nothing at all */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, test } from 'vitest';

const REPO = path.resolve(process.cwd(), '..');
const CSS_PATH = path.join(REPO, 'client', 'css', 'session-sidebar-rows.css');

interface Rule {
    selector: string;
    body: string;
}

function rules(source: string): Rule[] {
    const clean = source.replace(/\/\*[\s\S]*?\*\//g, '');
    const out: Rule[] = [];
    const re = /([^{}]+)\{([^{}]*)\}/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(clean)) !== null) {
        const selector = m[1]!.trim().replace(/\s+/g, ' ');
        if (!selector || selector.startsWith('@')) continue;
        out.push({ selector, body: m[2] ?? '' });
    }
    return out;
}

function bySelector(ruleList: Rule[], wanted: string): Rule[] {
    return ruleList.filter((r) => r.selector.split(',').some((s) => s.trim() === wanted));
}

function decl(body: string, prop: string): string | null {
    const m = body.match(new RegExp(`(?:^|;)\\s*${prop}\\s*:\\s*([^;]+)`, 'i'));
    return m ? m[1]!.trim() : null;
}

function containerMaxWidth(source: string, selector: string): number | null {
    const blocks = source.matchAll(/@container\s+sidebar-row\s*\(max-width:\s*(\d+)px\)\s*\{([\s\S]*?)\n\}/g);
    for (const b of blocks) {
        if (b[2]!.includes(selector)) return Number(b[1]);
    }
    return null;
}

describe('the sidebar row is a queried container and floors its own name', () => {
    const cssSource = fs.readFileSync(CSS_PATH, 'utf8');
    const parsed = rules(cssSource);

    test('.session-sidebar-row establishes the queried container', () => {
        const row = bySelector(parsed, '.session-sidebar-row');
        expect(row.length).toBeGreaterThan(0);
        expect(decl(row[0]!.body, 'container-type')).toBe('inline-size');
        expect(decl(row[0]!.body, 'container-name')).toBe('sidebar-row');
    });

    test('.session-sidebar-row-name floors at 8ch, never 0', () => {
        const name = bySelector(parsed, '.session-sidebar-row-name');
        expect(name.length).toBeGreaterThan(0);
        expect(decl(name[0]!.body, 'min-width')).toBe('8ch');
    });

    test('the pin and the kebab trigger are never in the drop order (flex-shrink stays 0 elsewhere)', () => {
        expect(containerMaxWidth(cssSource, '.session-sidebar-row-pin')).toBeNull();
        expect(containerMaxWidth(cssSource, '.session-row-menu-trigger')).toBeNull();
    });
});

describe('the overflow drop order: lowest value first, cup last', () => {
    const cssSource = fs.readFileSync(CSS_PATH, 'utf8');
    const parsed = rules(cssSource);

    const countsAt = containerMaxWidth(cssSource, '.subagent-count--button');
    const cupAt = containerMaxWidth(cssSource, '.session-sidebar-row-keep-awake');

    test('the counts and the cup keep their width thresholds, counts first', () => {
        expect(countsAt, 'the cozy/detailed plain-text counts must drop before any icon').not.toBeNull();
        expect(cupAt, 'the keep-awake cup must have a drop threshold').not.toBeNull();
        expect(countsAt!).toBeGreaterThan(cupAt!);
    });

    test('the detailed bare count also drops with the cozy chips, not on its own schedule', () => {
        expect(containerMaxWidth(cssSource, '.session-row__subagent-count')).toBe(countsAt);
        expect(containerMaxWidth(cssSource, '.timer-chip--button')).toBe(countsAt);
    });

    test('the three icons have NO width threshold: a quiet row keeps them (issue #1211)', () => {
        for (const icon of ['timers', 'shells', 'agents']) {
            expect(containerMaxWidth(cssSource, `.session-sidebar-row-${icon}-icon`), icon).toBeNull();
        }
    });

    test('the optional group wraps onto an unpainted line, and the cluster lets it shrink', () => {
        const group = bySelector(parsed, '.session-sidebar-row-optional-icons');
        expect(group.length).toBe(1);
        expect(decl(group[0]!.body, 'flex-wrap')).toBe('wrap');
        expect(decl(group[0]!.body, 'overflow')).toBe('hidden');
        expect(decl(group[0]!.body, 'height')).toBe('16px');
        expect(decl(group[0]!.body, 'min-width')).toBe('0');
        const cluster = bySelector(parsed, '.session-sidebar-row-controls-cluster');
        expect(decl(cluster[0]!.body, 'flex-shrink')).toBe('1');
        expect(decl(cluster[0]!.body, 'min-width')).toBe('0');
    });
});
