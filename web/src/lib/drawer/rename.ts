import { t } from '../i18n/index.svelte';
import { drawerEnv } from './env';
import * as Layouts from './layouts-model';
import { isBrowserName, rename as renameBrowser } from './browser-rows';

interface LabelRule {
    validate(raw: string | null): LabelVerdict;
    LABEL_MAX_CHARS?: number;
}
export type LabelVerdict = { ok: true; value: string } | { ok: false; reason: string };

export interface EditorOptions {
    hostEl: Element;
    nameEl: HTMLElement;
    seed: string;
    ariaLabel?: string;
    save(value: string): Promise<unknown>;
    successText?(value: string): string;
    afterSuccess?(result: unknown, value: string): void | Promise<void>;
}

interface Editor extends EditorOptions {
    wrap: HTMLElement;
    input: HTMLInputElement;
    err: HTMLElement;
    settled: boolean;
}

interface RenameEnv {
    SessionLabel?: LabelRule;
    SessionSidebar?: { listEl: HTMLElement | null; forceRefresh(): Promise<void> };
    CloudeWeb?: { sidebarShell?: { owns?(t: unknown): boolean; beginRowRename?(row: Element): boolean; isEditing?(): boolean } };
    API?: { renameSession(id: string, value: string): Promise<unknown> };
}

const FALLBACK_LABEL_MAX = 200;

let current: Editor | null = null;

function env(): RenameEnv {
    return drawerEnv() as RenameEnv;
}

function announce(text: string): void {
    const region = document.getElementById('session-sidebar-live');
    if (region) region.textContent = text;
}

export function validateLabel(raw: string | null): LabelVerdict {
    const rule = env().SessionLabel;
    return rule && rule.validate ? rule.validate(raw) : { ok: false, reason: t('sidebar.heading.rename.no_rule') };
}

export function isEditing(): boolean {
    if (current !== null) return true;
    const shell = env().CloudeWeb?.sidebarShell;
    return !!(shell && typeof shell.isEditing === 'function' && shell.isEditing());
}

export function onListClick(e: MouseEvent): boolean {
    if (!isEditing()) return false;
    const target = e.target;
    const inside = target instanceof Element ? target.closest('.session-sidebar-rename-edit') : null;
    if (!inside) return false;
    e.stopPropagation();
    return true;
}

function buildEditorDom(o: EditorOptions): Pick<Editor, 'wrap' | 'input' | 'err'> {
    const wrap = document.createElement('span');
    wrap.className = 'session-sidebar-rename-edit';
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'oc-field session-sidebar-rename-input';
    input.value = o.seed;
    input.setAttribute('aria-label', o.ariaLabel || t('sidebar.rename.aria', { name: o.seed }));
    input.setAttribute('maxlength', String(env().SessionLabel?.LABEL_MAX_CHARS || FALLBACK_LABEL_MAX));
    const err = document.createElement('span');
    err.className = 'session-sidebar-rename-error';
    err.hidden = true;
    err.setAttribute('role', 'alert');
    wrap.append(input, err);
    o.nameEl.insertAdjacentElement('afterend', wrap);
    return { wrap, input, err };
}

export function openEditor(o: EditorOptions): boolean {
    if (isEditing()) return false;
    o.hostEl.setAttribute('data-editing', '1');
    o.nameEl.hidden = true;
    const ed: Editor = { ...o, ...buildEditorDom(o), settled: false };
    current = ed;
    ed.input.addEventListener('keydown', (e) => onEditKeydown(e, ed));
    ed.input.addEventListener('keyup', (e) => {
        e.stopPropagation();
        if (e.key === ' ') e.preventDefault();
    });
    ed.input.addEventListener('blur', () => { void commit(ed); });
    ed.input.focus();
    ed.input.select();
    announce(t('sidebar.heading.rename.editing', { name: o.seed }));
    return true;
}

function onEditKeydown(e: KeyboardEvent, ed: Editor): void {
    e.stopPropagation();
    if (e.key === 'Enter') {
        e.preventDefault();
        void commit(ed);
    } else if (e.key === 'Escape') {
        e.preventDefault();
        cancel(ed);
    }
}

function teardown(ed: Editor): void {
    ed.settled = true;
    current = null;
    ed.wrap.parentNode?.removeChild(ed.wrap);
    ed.nameEl.hidden = false;
    ed.hostEl.removeAttribute('data-editing');
}

function cancel(ed: Editor): void {
    if (ed.settled) return;
    teardown(ed);
    announce(t('sidebar.heading.rename.canceled', { name: ed.seed }));
}

function showError(ed: Editor, text: string): void {
    ed.err.textContent = text;
    ed.err.hidden = false;
    ed.input.focus();
    ed.input.select();
}

async function commit(ed: Editor): Promise<void> {
    if (ed.settled) return;
    const raw = (ed.input.value || '').trim();
    if (!raw || raw === ed.seed) { cancel(ed); return; }
    const verdict = validateLabel(raw);
    if (!verdict.ok) { showError(ed, verdict.reason); return; }
    ed.settled = true;
    let result: unknown;
    try {
        result = await ed.save(verdict.value);
    } catch (err) {
        ed.settled = false;
        const e = err as { message?: string; detail?: string } | null;
        const detail = (e && (e.message || e.detail)) || t('sidebar.heading.rename.refused');
        showError(ed, t('sidebar.heading.rename.failed_inline', { detail }));
        announce(t('sidebar.heading.rename.failed', { name: ed.seed, detail }));
        return;
    }
    teardown(ed);
    announce(ed.successText ? ed.successText(verdict.value) : t('sidebar.rename.done', { name: ed.seed, value: verdict.value }));
    if (ed.afterSuccess) await ed.afterSuccess(result, verdict.value);
}

function saveRow(name: string, id: string, value: string): Promise<unknown> {
    if (isBrowserName(name)) return renameBrowser(id, value);
    if (Layouts.isLayoutName(name)) return Layouts.rename(id, value);
    return env().API!.renameSession(id, value);
}

export function beginEdit(rowEl: Element): boolean {
    const shell = env().CloudeWeb?.sidebarShell;
    if (shell && typeof shell.owns === 'function' && shell.owns(rowEl) && typeof shell.beginRowRename === 'function') {
        return shell.beginRowRename(rowEl);
    }
    if (isEditing() || !(rowEl instanceof HTMLElement)) return false;
    const name = rowEl.dataset.name;
    const id = rowEl.dataset.sessionId || (rowEl.dataset.asleep ? rowEl.dataset.sessionUuid : '')
        || rowEl.dataset.browserId || rowEl.dataset.layoutUuid || null;
    const nameEl = rowEl.querySelector<HTMLElement>('[data-row-name]');
    if (rowEl.getAttribute('data-rename-state') !== 'renameable' || !id || !name) {
        announce((nameEl && nameEl.getAttribute('data-name-note')) || t('sidebar.row.rename.refused'));
        rowEl.setAttribute('data-rename-refused', '1');
        return false;
    }
    if (!nameEl) return false;
    const seed = (nameEl.textContent || '').trim();
    return openEditor({
        hostEl: rowEl, nameEl, seed, ariaLabel: t('sidebar.rename.aria', { name: seed }),
        save: (value) => saveRow(name, id, value),
        afterSuccess: async () => { await env().SessionSidebar?.forceRefresh(); },
    });
}

export function onRowKeydown(e: KeyboardEvent, rowEl: Element): boolean {
    if (e.key !== 'F2') return false;
    e.preventDefault();
    beginEdit(rowEl);
    return true;
}

export function afterRender(): void {
    if (current === null) return;
    const list = env().SessionSidebar?.listEl;
    if (list && list.contains(current.wrap)) return;
    current = null;
}
