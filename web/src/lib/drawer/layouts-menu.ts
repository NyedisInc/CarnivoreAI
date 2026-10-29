import { t } from '../i18n/index.svelte';
import { drawerEnv } from './env';
import { rowElementFor } from '../item-menu/run/run-env';
import { togglePinRow } from '../sidebar-shell/row-reorder';
import * as GroupColor from './group-color';
import { bridge, idOf } from './layouts-model';
import { announce } from '../sidebar-shell/interaction-globals';

export interface MenuItemContext { name: string; label?: string; layoutUuid?: string }

interface AppShell {
    showConfirmModal?(title: string, message: string, detail: string, confirm: string, cancel: undefined, tone: string): Promise<boolean>;
}

async function remove(ctx: MenuItemContext): Promise<void> {
    const b = bridge();
    if (!b) return;
    const app = drawerEnv().App as AppShell | undefined;
    const name = ctx.label || ctx.name;
    const ok = app && typeof app.showConfirmModal === 'function'
        ? await app.showConfirmModal(t('layout.remove.title'), t('layout.remove.message', { name }), t('layout.remove.detail'),
            t('layout.remove.confirm'), undefined, 'danger')
        : window.confirm(t('layout.remove.message', { name }));
    if (!ok) return;
    try {
        await b.delete(idOf(ctx.name));
    } catch (err) {
        console.error('SessionSidebarLayouts: remove failed:', err);
        window.alert(t('layout.remove.failed', { reason: err instanceof Error && err.message ? err.message : String(err) }));
    }
}

function kebabFor(ctx: MenuItemContext): Element | null {
    const rowEl = rowElementFor(ctx);
    return rowEl ? rowEl.querySelector('[data-row-menu]') : null;
}

async function saveAsBlueprint(ctx: MenuItemContext): Promise<void> {
    const env = drawerEnv();
    const blueprints = env.CloudeWeb?.blueprints as
        { fromLayout?(uuid: string, name?: string): Promise<{ ok: boolean; name?: string; reason?: string }> } | undefined;
    if (!blueprints || typeof blueprints.fromLayout !== 'function') return;
    const prompter = env.TextPromptModal as { open?(o: Record<string, string>): Promise<string | null | undefined> } | undefined;
    const defaultName = ctx.label || ctx.name || '';
    const name = prompter && typeof prompter.open === 'function'
        ? await prompter.open({
            title: t('blueprint.from_layout.title'), label: t('blueprint.name.label'), defaultValue: defaultName,
            confirmLabel: t('blueprint.save'), cancelLabel: t('blueprint.cancel'),
        })
        : defaultName;
    if (name === null || name === undefined) return;
    const result = await blueprints.fromLayout(idOf(ctx.name), String(name).trim() || undefined);
    if (result.ok) {
        announce(t('blueprint.saved', { name: result.name }));
    } else {
        window.alert(t('blueprint.save_failed', { reason: result.reason }));
    }
}

function loadBlueprint(ctx: MenuItemContext): void {
    const web = drawerEnv().CloudeWeb as { openBlueprintPicker?(a: Element): void; openBlueprintsScreen?(): void } | undefined;
    if (!web) return;
    const anchor = kebabFor(ctx);
    if (anchor && typeof web.openBlueprintPicker === 'function') web.openBlueprintPicker(anchor);
    else if (typeof web.openBlueprintsScreen === 'function') web.openBlueprintsScreen();
}

export function runMenuItem(itemId: string, ctx: MenuItemContext): Promise<void> | null {
    if (itemId === 'close') return remove(ctx);
    if (itemId === 'pin') {
        togglePinRow(ctx.name);
        return Promise.resolve();
    }
    if (itemId === 'colour') {
        const anchor = kebabFor(ctx);
        if (anchor) GroupColor.openFor(anchor, 'layout', idOf(ctx.name));
        return Promise.resolve();
    }
    if (itemId === 'save-blueprint') return saveAsBlueprint(ctx);
    if (itemId === 'load-blueprint') { loadBlueprint(ctx); return Promise.resolve(); }
    return null;
}
