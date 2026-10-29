/* Escape cancels */
import { t } from '../i18n/index.svelte';
import { announce, hg } from './interaction-globals';

export interface HeadingRenameSpec {
    key: string;
    seed: string;
    ariaLabel: string;
    save(value: string): Promise<unknown>;
    successText?(value: string): string;
    afterSuccess?(result: unknown, value: string): void | Promise<void>;
}

const FALLBACK_LABEL_MAX = 200;

class HeadingRenameState {
    spec = $state.raw<HeadingRenameSpec | null>(null);
    value = $state('');
    error = $state('');
    selectAll = $state(0);
    caret: [number, number] | null = null;
    settled = false;
}

export const headingRename = new HeadingRenameState();

export function isHeadingEditing(): boolean {
    return headingRename.spec !== null;
}

export function labelMax(): number {
    return hg().SessionLabel?.LABEL_MAX_CHARS || FALLBACK_LABEL_MAX;
}

export function openHeadingRename(spec: HeadingRenameSpec): boolean {
    if (headingRename.spec || hg().SessionSidebarRename?.isEditing?.()) return false;
    headingRename.settled = false;
    headingRename.value = spec.seed;
    headingRename.error = '';
    headingRename.caret = [0, spec.seed.length];
    headingRename.spec = spec;
    announce(t('sidebar.heading.rename.editing', { name: spec.seed }));
    return true;
}

export function dropHeadingRename(): void {
    headingRename.settled = true;
    headingRename.spec = null;
    headingRename.error = '';
    headingRename.caret = null;
}

export function cancelHeadingRename(): void {
    const spec = headingRename.spec;
    if (!spec || headingRename.settled) return;
    dropHeadingRename();
    announce(t('sidebar.heading.rename.canceled', { name: spec.seed }));
}

function validate(raw: string): { ok: boolean; value?: string; reason?: string } {
    const rule = hg().SessionLabel?.validate;
    return rule ? rule(raw) : { ok: false, reason: t('sidebar.heading.rename.no_rule') };
}

function showError(text: string): void {
    headingRename.error = text;
    headingRename.selectAll += 1;
}

export async function commitHeadingRename(): Promise<void> {
    const spec = headingRename.spec;
    if (!spec || headingRename.settled) return;
    const raw = (headingRename.value || '').trim();
    if (!raw || raw === spec.seed) {
        cancelHeadingRename();
        return;
    }
    const verdict = validate(raw);
    if (!verdict.ok) {
        showError(verdict.reason || '');
        return;
    }
    const value = verdict.value as string;
    headingRename.settled = true;
    let result: unknown;
    try {
        result = await spec.save(value);
    } catch (err) {
        const e = err as { message?: string; detail?: string } | null;
        const detail = (e && (e.message || e.detail)) || t('sidebar.heading.rename.refused');
        if (headingRename.spec === spec) {
            headingRename.settled = false;
            showError(t('sidebar.heading.rename.failed_inline', { detail }));
        }
        announce(t('sidebar.heading.rename.failed', { name: spec.seed, detail }));
        return;
    }
    if (headingRename.spec === spec) dropHeadingRename();
    announce(spec.successText ? spec.successText(value) : `renamed ${spec.seed} to ${value}`);
    if (spec.afterSuccess) await spec.afterSuccess(result, value);
}

export function headingDrawn(key: string): boolean {
    const list = document.getElementById('session-sidebar-list');
    if (!list) return false;
    return Array.from(list.querySelectorAll('[data-group-toggle]'))
        .some((el) => el.getAttribute('data-group-toggle') === key);
}

export function reconcileHeadingRename(listEl: Element): void {
    if (headingRename.spec && !listEl.querySelector('.session-sidebar-rename-edit')) dropHeadingRename();
}
