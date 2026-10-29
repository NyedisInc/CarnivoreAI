import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { identParts } from './report-format';
import { onComputerValue } from './item-model';

const css = (name: string): string => readFileSync(new URL(`./${name}`, import.meta.url), 'utf8');

function phoneBlocks(source: string): string {
    const out: string[] = [];
    const head = '@media (max-width: 719px), (pointer: coarse) {';
    let from = source.indexOf(head);
    while (from !== -1) {
        let depth = 0;
        let end = from + head.length - 1;
        for (let i = end; i < source.length; i++) {
            if (source[i] === '{') depth++;
            if (source[i] === '}' && --depth === 0) { end = i; break; }
        }
        out.push(source.slice(from, end + 1));
        from = source.indexOf(head, end);
    }
    return out.join('\n');
}

function tapped(file: string, selector: string): boolean {
    const rules = phoneBlocks(css(file));
    return rules.split('}').some((rule) => {
        const [heads = '', body = ''] = rule.split('{').slice(-2);
        return heads.split(',').some((h) => h.trim().endsWith(selector)) && /min-height:\s*var\(--oc-tap\)/.test(body);
    });
}

describe('phone tap targets (ruling b: every standalone control 44 high)', () => {
    it.each([
        ['side.css', 'button.d-ev__btn'],
        ['side.css', '.d-fold > summary'],
        ['checks.css', '.d-chk__h'],
        ['checks.css', '.d-more [data-btn]'],
        ['checks.css', '.pp-ck__unread [data-btn]'],
        ['detail.css', '.d-det > summary'],
        ['detail.css', '.d-fields [data-field]'],
        ['detail.css', '.d-act [data-field]'],
        ['list.css', '.d-filter input'],
        ['list.css', '.d-empty--fail button'],
        ['wizard.css', '.d-hero .oc-pick'],
        ['wizard.css', '.d-regi .fields__tick'],
        ['wizard.css', '.d-wiz__terms'],
    ])('%s: %s has min-height var(--oc-tap) in the phone rule', (file, selector) => {
        expect(tapped(file, selector)).toBe(true);
    });

    it('the check can go red: a selector no phone rule names is not tapped', () => {
        expect(tapped('side.css', '.d-no-such-control')).toBe(false);
    });
});

describe('identifiers never split (D28)', () => {
    it('.pp-tok and a lone identifier value carry nowrap', () => {
        expect(css('panel.css')).toMatch(/\.pp-tok,\s*dd\.pp-ident\s*\{\s*white-space:\s*nowrap;/);
    });

    it('keeps a hyphenated name whole and lets a path break only after a slash', () => {
        const parts = identParts('in the catalog as acme/bad-skill 1.0.0');
        expect(parts.map((p) => p.text).join('')).toBe('in the catalog as acme/bad-skill 1.0.0');
        expect(parts.filter((p) => p.tok).map((p) => p.text)).toEqual(['acme/bad-skill']);
        expect(parts.every((p) => !p.wbr)).toBe(true);
        expect(identParts('file-2.sh line 17').filter((p) => p.tok).map((p) => p.text)).toEqual(['file-2.sh']);
    });
});

describe('X6 round: identifiers, phone targets, fold geometry, step glyph, retry bar', () => {
    it('X6-10: publisher/name is one token with no break, a real path still wraps after a slash, every token is nowrap', () => {
        const pair = identParts('in the catalog as acme/old-notes 2.0.0');
        expect(pair.filter((p) => p.tok)).toEqual([{ text: 'acme/old-notes', tok: true, wbr: false }]);
        const path = identParts('secret_found in scripts/render.sh');
        expect(path.filter((p) => p.tok).map((p) => p.text)).toEqual(['scripts/', 'render.sh']);
        expect(path.find((p) => p.text === 'scripts/')?.wbr).toBe(true);
        expect(path.find((p) => p.text === 'render.sh')?.wbr).toBe(false);
        expect(identParts('a/b/c-d').map((p) => p.text)).toEqual(['a/', 'b/', 'c-d']);
        expect(css('panel.css')).toMatch(/\.pp-tok,\s*dd\.pp-ident\s*\{[^}]*white-space:\s*nowrap/);
    });

    it('X6-11: the name headings clip with an ellipsis inside themselves and the full name is the own text of the element', () => {
        expect(css('detail.css')).toMatch(/\.d-name\s*\{[^}]*white-space:\s*nowrap;[^}]*overflow:\s*hidden;[^}]*text-overflow:\s*ellipsis/);
        expect(css('side.css')).toMatch(/\.d-card \.catalog-card__title\s*\{[^}]*white-space:\s*nowrap;[^}]*overflow:\s*hidden;[^}]*text-overflow:\s*ellipsis/);
        expect(css('DossierHead.svelte')).toMatch(/<h2 class="d-name">\{rec\.name\}<\/h2>/);
    });

    it('X6-7: a retry inside .d-note is 44 by 44 on the phone', () => {
        const rules = phoneBlocks(css('detail.css'));
        expect(rules).toMatch(/\.d-note button\s*\{[^}]*min-height:\s*var\(--oc-tap\);[^}]*min-width:\s*var\(--oc-tap\)/);
    });

    it('X6-16: the fold sign keeps its trailing space in a flex summary', () => {
        expect(css('side.css')).toMatch(/\.d-fold > summary::before\s*\{[^}]*white-space:\s*pre/);
    });

    it('X7-7: the fold row chevron sits on the summary line, open or closed', () => {
        const rules = phoneBlocks(css('side.css'));
        const mark = rules.match(/:has\(\.d-fold\) > \.d-ev__mark\s*\{([^}]*)\}/)?.[1] ?? '';
        expect(mark).toMatch(/align-items:\s*flex-start/);
        expect(mark).toMatch(/padding-top:\s*calc\(var\(--oc-tap\) \/ 2 - var\(--oc-pp-space-7\)\)/);
        expect(mark).not.toMatch(/min-height/);
        expect(mark).not.toMatch(/align-items:\s*center/);
        expect(rules).toMatch(/:has\(\.d-fold\) > \.d-ev__mark::after\s*\{[^}]*top:\s*calc\(var\(--oc-tap\) \/ 2 \+ var\(--oc-pp-space-7\) \+ var\(--oc-space-1\)\)/);
    });

    it('X7-2: the summary row is a wrapping flex row and a cell fits its content', () => {
        const src = css('wizard.css');
        const sum = src.match(/\.d-sum\s*\{([^}]*)\}/)?.[1] ?? '';
        expect(sum).toMatch(/display:\s*flex/);
        expect(sum).toMatch(/flex-wrap:\s*wrap/);
        expect(sum).not.toMatch(/grid-template-columns/);
        const cell = src.match(/\.d-sum > div\s*\{([^}]*)\}/)?.[1] ?? '';
        expect(cell).toMatch(/flex:\s*1 1 120px/);
        expect(cell).toMatch(/max-width:\s*100%/);
        expect(cell).not.toMatch(/min-width/);
        expect(src).toMatch(/\.d-sum dd\.pp-ident\s*\{[^}]*overflow:\s*hidden;[^}]*text-overflow:\s*ellipsis/);
        expect(css('panel.css')).toMatch(/dd\.pp-ident\s*\{\s*white-space:\s*nowrap;/);
    });

    it('X7-4: the local check heading wraps at spaces, never an ellipsis; the shared name keeps its ellipsis', () => {
        expect(css('checks.css')).toMatch(/\.pp-ck \.d-name\s*\{\s*white-space:\s*normal;\s*overflow:\s*visible;\s*text-overflow:\s*clip;\s*overflow-wrap:\s*normal;\s*\}/);
        expect(css('detail.css')).toMatch(/\.d-name\s*\{[^}]*white-space:\s*nowrap;[^}]*overflow:\s*hidden;[^}]*text-overflow:\s*ellipsis/);
    });

    it('X7-6: the checks retry rule sits in the phone block', () => {
        expect(phoneBlocks(css('checks.css'))).toMatch(/\.pp-ck__unread \[data-btn\]\s*\{[^}]*min-width:\s*var\(--oc-tap\)/);
    });

    it('X7-8: a signed-out or handle-less strip text takes its own row on the phone', () => {
        const src = css('page.css');
        expect(src.slice(src.indexOf('@container pp (max-width: 719px)'))).toMatch(/\.d-strip:has\(\.d-strip__h\[data-own\]\)\s*\{[^}]*flex:\s*1 0 100%;[^}]*order:\s*3/);
    });

    it('X6-18: the WHAT cell no longer spans the whole summary row', () => {
        expect(css('wizard.css')).not.toMatch(/dd\.pp-ident\)\s*\{\s*grid-column:\s*1\s*\/\s*-1/);
    });

    it('X6-17: the step 2 placeholder icon is drawn at 22 px', () => {
        const src = css('ImageStep.svelte');
        expect(src).toMatch(/<Icon name=\{kindIcon\(markKind\(kind\)\) \?\? 'grid'\} size=\{22\}/);
        expect(src).not.toMatch(/<KindMark/);
    });

    it('X6-24: the failed report retry sits in a content width wrapper', () => {
        expect(css('FixList.svelte')).toMatch(/<div class="pp-foot"><Button size="sm"[^]*?<\/Button><\/div>/);
    });

    it('X6-22: ON THIS COMPUTER is a dash when the folder list failed and the record has no folder', () => {
        expect(onComputerValue({ folderListFailed: true, hasFolder: false, declared: '', none: 'none' })).toBe('-');
        expect(onComputerValue({ folderListFailed: false, hasFolder: false, declared: '', none: 'none' })).toBe('none');
        expect(onComputerValue({ folderListFailed: true, hasFolder: true, declared: '1.2.0', none: 'none' })).toBe('1.2.0');
    });
});
