/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');
const CSS_DIR = path.join(ROOT, 'client', 'css');
const band = fs.readFileSync(path.join(CSS_DIR, 'session-sidebar-band-structure.css'), 'utf8');

function indentSelectors(rules: string): string[] {
    const m = rules.match(/\n([^{}]+)\{\s*padding-inline-start:\s*var\(--sidebar-tree-step\);\s*\}/);
    expect(m, 'the one tree indent rule').not.toBeNull();
    return (m![1] ?? '').split(',').map((x) => x.trim());
}

function depthOf(el: Element, padded: string): number {
    let n = 0;
    for (let p = el.parentElement; p; p = p.parentElement) if (p.matches(padded)) n += 1;
    return n;
}

const band_ = (inner: string, cls = ''): string =>
    `<div class="session-sidebar-group ${cls}"><div class="session-sidebar-group__headerrow"></div><div class="session-sidebar-group__body">${inner}</div></div>`;
const row = '<div class="session-sidebar-row"></div>';

describe('the drawer tree indent', () => {
    const selectors = indentSelectors(band);
    const padded = selectors.join(', ');
    const leaderOff = /\.session-sidebar-leader > \.session-sidebar-group__body \{\s*padding-inline-start:\s*0;/;

    it('declares one step token and one indent rule, in tokens only', () => {
        expect(band.match(/--sidebar-tree-step:/g)).toHaveLength(1);
        expect(band).toMatch(/--sidebar-tree-step:\s*var\(--oc-space-2\);/);
        expect(band.match(/padding-inline-start:\s*var\(--sidebar-tree-step\)/g)).toHaveLength(1);
        expect(band).toMatch(leaderOff);
    });

    it('leaves no other left indent on a sidebar row, body or band', () => {
        const offenders: string[] = [];
        for (const f of fs.readdirSync(CSS_DIR).filter((n) => n.startsWith('session-sidebar') && n.endsWith('.css'))) {
            const css = fs.readFileSync(path.join(CSS_DIR, f), 'utf8');
            for (const m of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
                const sel = (m[1] ?? '').replace(/\/\*[\s\S]*?\*\//g, '');
                if (!/(group__body|-row\b|session-sidebar-group\b|group--nested|company|layout__members)/.test(sel)) continue;
                if (/(^|[\s,])\.session-sidebar-row-\w+/.test(sel) && !/__body\s*>\s*\.session-sidebar-row\b/.test(sel)) continue;
                if (/(margin-left|padding-left)\s*:\s*(?!0\b|auto)/.test(m[2] ?? '') && /group__body|group--nested|company|layout__members|> \.session-sidebar-row\b/.test(sel)) offenders.push(`${f}: ${sel.trim()}`);
            }
        }
        expect(offenders).toEqual([]);
    });

    it('starts every heading, row, agents fold and layout member of depth N at N steps', () => {
        document.body.innerHTML = band_(
            band_(
                band_(
                    row + band_(row, 'session-sidebar-group--nested') + band_(row, 'agents'),
                    'project',
                ),
                'company',
            ),
            'companies',
        ) + `<div class="session-sidebar-group__body"><div class="session-sidebar-layout__members" id="lm">${row}</div></div>`;
        const depthsOf = (sel: string): number[] => Array.from(document.querySelectorAll(sel)).map((e) => depthOf(e, padded));
        expect(depthsOf('.session-sidebar-group__headerrow')).toEqual([0, 1, 2, 3, 3]);
        expect(depthsOf('.session-sidebar-row')).toEqual([3, 4, 4, 1]);
        expect(depthOf(document.querySelector('#lm')!, padded)).toBe(0);
        expect(depthOf(document.querySelector('#lm .session-sidebar-row')!, padded)).toBe(1);
    });

    it('insets each divider to the level it sits at: left 0 inside the padded parent body', () => {
        const rule = band.match(/\.session-sidebar-company \+ \.session-sidebar-company::before,[\s\S]*?\{([^}]*)\}/) ?? [];
        const ruleBody = rule[1] ?? '';
        expect(ruleBody).toMatch(/left:\s*0;/);
        expect(ruleBody).toMatch(/right:\s*var\(--sidebar-tree-step\)/);
    });
});
