/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { t } from '../i18n/index.svelte';
import * as Rename from './rename';
import { rename as renameBrowser } from './browser-rows';

vi.mock('./browser-rows', () => ({ isBrowserName: (n: string) => n.startsWith('browser:'), rename: vi.fn(async () => ({})) }));

type Win = Record<string, any>;
const win = globalThis as unknown as Win;
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');

/** A label that exercises the point: a space, a colon, a dot, a quote, a dollar. */
const RICH_LABEL = 'Media Compression: v1.2 "final" $5';

let sent: Array<Record<string, unknown>>;

function loadScripts(files: string[]): void {
    const log = console.log;
    console.log = () => {};
    try {
        for (const f of files) new Function(fs.readFileSync(path.join(repoRoot, 'client', 'js', f), 'utf8'))();
    } finally {
        console.log = log;
    }
}

async function settle(): Promise<void> {
    for (let i = 0; i < 4; i += 1) await new Promise((r) => setTimeout(r, 0));
}

async function drive(root: Element, opts: { type?: string | null; key?: string } = {}): Promise<HTMLInputElement> {
    const input = root.querySelector<HTMLInputElement>('.session-sidebar-rename-input');
    expect(input, 'the editor must have opened').not.toBeNull();
    if (opts.type !== undefined && opts.type !== null) input!.value = opts.type;
    input!.dispatchEvent(new KeyboardEvent('keydown', { key: opts.key ?? 'Enter', bubbles: true, cancelable: true }));
    await settle();
    return input!;
}

function buildRow(label: string | null, id = 'sess-1'): HTMLElement {
    const rowEl = document.createElement('div');
    rowEl.className = 'session-sidebar-row';
    rowEl.dataset.name = 'cloude_Media_Compression_v1_2_final_5';
    rowEl.dataset.sessionId = id;
    rowEl.setAttribute('data-rename-state', 'renameable');
    const nameEl = document.createElement('span');
    nameEl.setAttribute('data-row-name', '');
    nameEl.textContent = label || 'cloude_Media';
    rowEl.append(nameEl);
    document.body.append(rowEl);
    return rowEl;
}

function buildHeading(kind: string, label: string, menuAttr: string, menuValue: string) {
    const headerrow = document.createElement('div');
    headerrow.className = 'session-sidebar-group__headerrow';
    headerrow.dataset.bandKind = kind;
    headerrow.innerHTML = `<button class="session-sidebar-group__header"><span class="session-sidebar-group__label"></span></button>`
        + `<button class="session-sidebar-group__menu" ${menuAttr}="${menuValue}"></button>`;
    const labelEl = headerrow.querySelector<HTMLElement>('.session-sidebar-group__label')!;
    labelEl.textContent = label;
    document.body.append(headerrow);
    return { headerrow, labelEl, kebab: headerrow.querySelector<HTMLElement>('.session-sidebar-group__menu')! };
}

beforeAll(() => {
    win.CloudeTr = t;
    win.CloudeI18n = { t };
    loadScripts(['session-label.js']);
});

beforeEach(() => {
    sent = [];
    document.body.innerHTML = '<div id="session-sidebar-live"></div>';
    Rename.afterRender();
    win.TextPromptModal = { open() { throw new Error('must not open the text prompt modal'); } };
    win.API = {
        renameSession: async (sessionId: string, value: string) => { sent.push({ sessionId, value }); return {}; },
        renameSessionGroup: async (uuid: string, name: string) => {
            if (win.__fail) throw new Error(win.__fail);
            sent.push({ kind: 'group', uuid, name });
            return { groups: [{ group_uuid: uuid, name }] };
        },
        updateProject: async (name: string, body: Record<string, unknown>) => {
            if (win.__fail) throw new Error(win.__fail);
            sent.push({ kind: 'project', name, newName: body.newName, keys: Object.keys(body) });
            return { name: body.newName };
        },
    };
    win.WriteFailureNotice = { report: () => {} };
    win.SessionSidebarGroupStore = {
        isUsable: () => true, apply: () => {}, projectBandKeyFor: (id: number) => `p:${id}`,
        groupByUuid: (u: string) => (u === 'g1' ? { group_uuid: 'g1', name: 'Focus' } : null),
    };
    win.SessionSidebarKindGroups = { isAgentKind: () => true };
    win.SessionSidebar = { _rows: [{ name: 'c_a', project_id: 3, project_name: 'Api' }], _lastSig: null, forceRefresh: vi.fn(async () => {}) };
    delete win.__fail;
});

afterEach(() => { Rename.afterRender(); });

const live = (): string => document.getElementById('session-sidebar-live')!.textContent || '';

describe('a row\'s editor edits the LABEL, never the tmux handle', () => {
    it('seeds itself with the label the user is looking at, capped at the label length', () => {
        const row = buildRow(RICH_LABEL);
        Rename.beginEdit(row);
        const input = row.querySelector<HTMLInputElement>('.session-sidebar-rename-input')!;
        expect(input.value).toBe(RICH_LABEL);
        expect(input.getAttribute('maxlength')).toBe(String(win.SessionLabel.LABEL_MAX_CHARS));
        expect(row.getAttribute('data-editing')).toBe('1');
    });

    it('DECISIVE: renaming a labelled session stores the new label under the session id, and refreshes the drawer', async () => {
        const row = buildRow(RICH_LABEL);
        Rename.beginEdit(row);
        await drive(row, { type: 'Archive Sweep' });
        expect(sent).toEqual([{ sessionId: 'sess-1', value: 'Archive Sweep' }]);
        expect(win.SessionSidebar.forceRefresh).toHaveBeenCalledTimes(1);
        expect(row.querySelector('.session-sidebar-rename-edit')).toBeNull();
        expect(live()).toBe(t('sidebar.rename.done', { name: RICH_LABEL, value: 'Archive Sweep' }));
    });

    it('the seed is the label, so an edit builds on the label and never on a handle', async () => {
        const row = buildRow('Archive_Sweep');
        Rename.beginEdit(row);
        const input = row.querySelector<HTMLInputElement>('.session-sidebar-rename-input')!;
        input.value = `${input.value}_v2`;
        await drive(row);
        expect(sent.map((s) => s.value)).toEqual(['Archive_Sweep_v2']);
    });

    it('dismissing UNCHANGED, Escape, and a blank box all write nothing', async () => {
        for (const opts of [{ type: null }, { type: 'typed then abandoned', key: 'Escape' }, { type: '   ' }]) {
            const row = buildRow(RICH_LABEL);
            Rename.beginEdit(row);
            await drive(row, opts);
            expect(sent, JSON.stringify(opts)).toEqual([]);
            expect(row.querySelector('.session-sidebar-rename-edit')).toBeNull();
            expect((row.querySelector('[data-row-name]') as HTMLElement).hidden).toBe(false);
            row.remove();
        }
    });

    it('a label with punctuation reaches the server; a control character is refused locally and keeps the text', async () => {
        let row = buildRow('old');
        Rename.beginEdit(row);
        await drive(row, { type: RICH_LABEL });
        expect(sent.map((s) => s.value)).toEqual([RICH_LABEL]);
        sent = [];
        row = buildRow(RICH_LABEL, 'sess-2');
        Rename.beginEdit(row);
        const input = await drive(row, { type: 'two\u0007lines' });
        expect(sent).toEqual([]);
        expect(input.value).toBe('two\u0007lines');
        expect(Rename.validateLabel('a\nb').ok).toBe(false);
        expect(row.querySelector('.session-sidebar-rename-error')).not.toBeNull();
    });

    it('a failed write puts the editor back with the typed text and the reason, and the name unchanged', async () => {
        win.API.renameSession = async () => { throw new Error('name already used'); };
        const row = buildRow('old');
        Rename.beginEdit(row);
        const input = await drive(row, { type: 'Fresh Name' });
        const err = row.querySelector<HTMLElement>('.session-sidebar-rename-error')!;
        expect(err.hidden).toBe(false);
        expect(err.textContent).toContain('name already used');
        expect(input.value).toBe('Fresh Name');
        expect(live()).toContain('name already used');
        expect(Rename.isEditing()).toBe(true);
        win.API.renameSession = async (sessionId: string, value: string) => { sent.push({ sessionId, value }); return {}; };
        await drive(row);
        expect(sent).toEqual([{ sessionId: 'sess-1', value: 'Fresh Name' }]);
    });

    it('openEditor refuses to open a second editor over the first', () => {
        const a = buildHeading('group', 'A', 'data-group-menu', 'g1');
        const b = buildHeading('group', 'B', 'data-group-menu', 'g2');
        const opts = (el: HTMLElement) => ({ hostEl: el, nameEl: el.querySelector<HTMLElement>('.session-sidebar-group__label')!, seed: 'x', save: async () => ({}) });
        expect(Rename.openEditor(opts(a.headerrow))).toBe(true);
        expect(Rename.openEditor(opts(b.headerrow))).toBe(false);
        expect(b.headerrow.querySelector('.session-sidebar-rename-edit')).toBeNull();
    });

    it('a state other than renameable opens nothing, says why and marks the row', () => {
        const row = buildRow('old');
        row.setAttribute('data-rename-state', 'unavailable');
        expect(Rename.beginEdit(row)).toBe(false);
        expect(row.getAttribute('data-rename-refused')).toBe('1');
        expect(live()).toBe(t('sidebar.row.rename.refused'));
        expect(row.querySelector('.session-sidebar-rename-edit')).toBeNull();
    });

    it('a browser row saves through the browsers module and a Layout row through the Layouts one', async () => {
        const rename = vi.mocked(renameBrowser);
        const row = buildRow('b');
        row.dataset.name = 'browser:7';
        Rename.beginEdit(row);
        await drive(row, { type: 'Docs' });
        expect(rename).toHaveBeenCalledWith('sess-1', 'Docs');
        expect(sent).toEqual([]);
    });

    it('F2 opens it, anything else does not, and one editor at a time', () => {
        const row = buildRow('old');
        const other = new KeyboardEvent('keydown', { key: 'Enter' });
        expect(Rename.onRowKeydown(other, row)).toBe(false);
        expect(Rename.onRowKeydown(new KeyboardEvent('keydown', { key: 'F2' }), row)).toBe(true);
        expect(Rename.isEditing()).toBe(true);
        expect(Rename.beginEdit(buildRow('second', 'sess-9'))).toBe(false);
    });

    it('a click inside an open editor is claimed (and stopped); one outside it is not', () => {
        const row = buildRow('old');
        Rename.beginEdit(row);
        const inside = new MouseEvent('click', { bubbles: true, cancelable: true });
        Object.defineProperty(inside, 'target', { value: row.querySelector('.session-sidebar-rename-input') });
        const stop = vi.spyOn(inside, 'stopPropagation');
        expect(Rename.onListClick(inside)).toBe(true);
        expect(stop).toHaveBeenCalled();
        const outside = new MouseEvent('click', { bubbles: true });
        Object.defineProperty(outside, 'target', { value: row });
        expect(Rename.onListClick(outside)).toBe(false);
    });

    it('a repaint that destroys the editor does not leave the module believing an edit is open', () => {
        const row = buildRow('old');
        Rename.beginEdit(row);
        row.remove();
        Rename.afterRender();
        expect(Rename.isEditing()).toBe(false);
    });
});

function openOnHeading(
    h: { headerrow: HTMLElement; labelEl: HTMLElement }, seed: string,
    save: (value: string) => Promise<unknown>, successText?: (value: string) => string,
): boolean {
    return Rename.openEditor({ hostEl: h.headerrow, nameEl: h.labelEl, seed, ariaLabel: `Rename ${seed}`, save, successText });
}

describe('a group heading and a project heading rename through the SAME editor core', () => {
    it('opens the shared editor seeded with the heading name, never the modal', () => {
        const h = buildHeading('group', 'Focus', 'data-group-menu', 'g1');
        expect(openOnHeading(h, 'Focus', async () => ({}))).toBe(true);
        expect(h.headerrow.querySelector<HTMLInputElement>('.session-sidebar-rename-input')!.value).toBe('Focus');
        expect(h.headerrow.getAttribute('data-editing')).toBe('1');
    });

    it('DECISIVE: Enter calls the save with the typed value and says the success sentence', async () => {
        const h = buildHeading('group', 'Focus', 'data-group-menu', 'g1');
        openOnHeading(h, 'Focus', (value) => win.API.renameSessionGroup('g1', value), (value) => `group renamed to ${value}`);
        await drive(h.headerrow, { type: 'Deep Work' });
        expect(sent).toEqual([{ kind: 'group', uuid: 'g1', name: 'Deep Work' }]);
        expect(live()).toBe('group renamed to Deep Work');
        expect(h.headerrow.querySelector('.session-sidebar-rename-edit')).toBeNull();
    });

    it('Escape and an empty submit send nothing and restore the name', async () => {
        for (const opts of [{ type: 'abandoned', key: 'Escape' }, { type: '   ' }]) {
            const h = buildHeading('group', 'Focus', 'data-group-menu', 'g1');
            openOnHeading(h, 'Focus', (value) => win.API.renameSessionGroup('g1', value));
            await drive(h.headerrow, opts);
            expect(sent).toEqual([]);
            expect(h.labelEl.hidden).toBe(false);
            expect(h.labelEl.textContent).toBe('Focus');
            h.headerrow.remove();
        }
    });

    it('a rejected save shows the reason inline and stays open with the typed text', async () => {
        win.__fail = 'name already used';
        const h = buildHeading('group', 'Focus', 'data-group-menu', 'g1');
        openOnHeading(h, 'Focus', (value) => win.API.renameSessionGroup('g1', value));
        const input = await drive(h.headerrow, { type: 'Deep Work' });
        expect(sent).toEqual([]);
        expect(h.headerrow.querySelector('.session-sidebar-rename-edit')).not.toBeNull();
        expect(h.headerrow.querySelector('.session-sidebar-rename-error')!.textContent).toContain('name already used');
        expect(input.value).toBe('Deep Work');
    });

    it('a project heading saves through its own route and a rejection reads inline', async () => {
        const h = buildHeading('project', 'Api', 'data-project-menu', 'p:3');
        openOnHeading(h, 'Api', (value) => win.API.updateProject('Api', { newName: value }));
        await drive(h.headerrow, { type: 'API v2' });
        expect(sent).toEqual([{ kind: 'project', name: 'Api', newName: 'API v2', keys: ['newName'] }]);
        win.__fail = 'a project named "API v2" already exists';
        const again = buildHeading('project', 'Api', 'data-project-menu', 'p:3');
        openOnHeading(again, 'Api', (value) => win.API.updateProject('Api', { newName: value }));
        await drive(again.headerrow, { type: 'API v2' });
        expect(again.headerrow.querySelector('.session-sidebar-rename-error')!.textContent).toContain('already exists');
    });
});
