import { t } from '../i18n/index.svelte';
import * as host from '../../opscenter/api/host';
import { contextFromRow, type RowMenuCtx } from '../item-menu/row-context';
import { ROW_ITEMS } from '../item-menu/menus/row-items';
import { runTable } from '../item-menu/run/index';
import { readAnimations, saveAnimations } from '../motion/animations-pref';
import type { DrawerRowLike, PaletteItem } from './palette-sources';

export const PALETTE_CONTAINER = 'command-palette';

export const PALETTE_ROW_ITEMS: readonly string[] = [
    'restart', 'rename', 'fork', 'new-terminal-here', 'move-to-folder', 'move-to-group', 'pin', 'mute', 'keep-awake',
    'mark-read', 'sleep', 'wake',
];

export function paletteAnchor(): Element | null {
    return typeof document === 'undefined' ? null : document.getElementById(PALETTE_CONTAINER);
}

export function paletteContext(row: DrawerRowLike): RowMenuCtx {
    return { ...contextFromRow(row, { surface: 'sidebar' }), anchor: paletteAnchor() };
}

export function sessionActions(row: DrawerRowLike): PaletteItem[] {
    const ctx = paletteContext(row);
    const label = String(row.label || row.name);
    const out: PaletteItem[] = [];
    for (const id of PALETTE_ROW_ITEMS) {
        const item = ROW_ITEMS.find((i) => i.id === id);
        if (!item || !item.available(ctx) || !item.enabled(ctx)) continue;
        out.push({
            id: `action:${id}:${row.session_id || row.name}`, kind: 'action', title: item.label(ctx), subtitle: label,
            run: () => runTable.run(id, paletteContext(row)),
        });
    }
    return out;
}

function app(id: string, key: string, run: () => unknown): PaletteItem {
    return { id: `action:${id}`, kind: 'action', title: t(key), subtitle: t('palette.kind.action'), run };
}

export function appActions(rows: readonly DrawerRowLike[]): PaletteItem[] {
    const terminalSearch = (globalThis as { CloudeWeb?: { openTerminalSearch?: () => unknown } }).CloudeWeb?.openTerminalSearch;
    const list = [
        app('new-session', 'palette.action.new_session', () => host.newSession(null)),
        app('new-terminal', 'palette.action.new_terminal', () => host.newTerminal()),
        app('open-project', 'palette.action.open_project', () => host.startNewProject()),
        app('switch-theme', 'palette.action.switch_theme', () => host.openThemes()),
        app('animations', readAnimations() ? 'palette.action.animations_off' : 'palette.action.animations_on', () => saveAnimations(!readAnimations())),
        app('settings', 'palette.action.settings', () => host.openSettings()),
        app('pair-computer', 'palette.action.pair_computer', () => host.openHosts()),
    ];
    if (typeof terminalSearch === 'function') list.push(app('terminal-search', 'palette.action.terminal_search', () => terminalSearch()));
    const inView = host.primarySessionId();
    const row = inView ? rows.find((r) => r.session_id === inView) : undefined;
    return row ? [...list, ...sessionActions(row)] : list;
}
