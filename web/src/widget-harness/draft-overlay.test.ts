import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { draftOverlay, isSvelteStyleRequest } from '../../vite.widget-draft.plugin';

let root = '';
let repo = '';
let draft = '';
const CELL = 'web/src/opscenter/cells/notes/Cell.svelte';

beforeEach(() => {
    root = mkdtempSync(join(tmpdir(), 'draft-overlay-'));
    repo = join(root, 'repo');
    draft = join(root, 'draft');
    mkdirSync(join(draft, 'files', 'web/src/opscenter/cells/notes'), { recursive: true });
    writeFileSync(join(draft, 'draft.json'), JSON.stringify({ kind: 'revision' }));
    writeFileSync(join(draft, 'files', CELL), '<p>draft</p><style>p{color:red}</style>');
});
afterEach(() => rmSync(root, { recursive: true, force: true }));

type Hooks = { resolveId: (s: string, i?: string) => unknown; load: (id: string) => unknown };

describe('draft overlay and the component style module', () => {
    it('recognises the svelte style request', () => {
        expect(isSvelteStyleRequest(`${join(repo, CELL)}?svelte&type=style&lang.css`)).toBe(true);
        expect(isSvelteStyleRequest(join(repo, CELL))).toBe(false);
    });

    it('stands in for the component itself', () => {
        const hooks = draftOverlay(draft, repo) as unknown as Hooks;
        expect(hooks.resolveId(join(repo, CELL))).toBe(join(repo, CELL));
        expect(String(hooks.load(join(repo, CELL)))).toContain('<p>draft</p>');
    });

    it('returns null for the style request in both hooks, so the draft styles ship', () => {
        const hooks = draftOverlay(draft, repo) as unknown as Hooks;
        const style = `${join(repo, CELL)}?svelte&type=style&lang.css`;
        expect(hooks.resolveId(style)).toBeNull();
        expect(hooks.resolveId('./Cell.svelte?svelte&type=style&lang.css', join(repo, CELL))).toBeNull();
        expect(hooks.load(style)).toBeNull();
    });
});
