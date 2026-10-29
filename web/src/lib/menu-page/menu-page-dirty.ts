import { t } from '../i18n/index.svelte';

export type DirtyCheck = () => boolean;

interface Entry {
    pageId: string;
    isDirty: DirtyCheck;
    discard?: () => void;
}

const entries = new Set<Entry>();

export type ConfirmFn = (
    title: string,
    message: string,
    detail: string,
    confirmLabel: string,
    cancelLabel: string,
    variant: string,
) => Promise<boolean>;

export function registerPageDirty(pageId: string, isDirty: DirtyCheck, discard?: () => void): () => void {
    const entry: Entry = { pageId, isDirty, discard };
    entries.add(entry);
    return () => {
        entries.delete(entry);
    };
}

export function isPageDirty(pageId: string): boolean {
    for (const entry of entries) {
        if (entry.pageId !== pageId) continue;
        try {
            if (entry.isDirty()) return true;
        } catch (error) {
            console.error('menu page dirty check failed; treating the page as saved', pageId, error);
        }
    }
    return false;
}

function liveConfirm(): ConfirmFn | null {
    const app = (globalThis as { App?: { showConfirmModal?: ConfirmFn } }).App;
    return typeof app?.showConfirmModal === 'function' ? app.showConfirmModal.bind(app) : null;
}

export async function mayClosePage(pageId: string | null, confirm: ConfirmFn | null = liveConfirm()): Promise<boolean> {
    if (!pageId || !isPageDirty(pageId)) return true;
    if (!confirm) {
        console.error('menu page has unsaved changes and the confirm dialog is not on the page; the page stays open', pageId);
        return false;
    }
    const discarded = await confirm(
        t('menu_page.unsaved.title'),
        t('menu_page.unsaved.message'),
        '',
        t('menu_page.unsaved.discard'),
        t('menu_page.unsaved.keep'),
        'danger',
    );
    if (discarded) for (const entry of entries) if (entry.pageId === pageId) entry.discard?.();
    return discarded;
}

export function resetPageDirty(): void {
    entries.clear();
}
