import { layouts } from '../layouts-bridge/api.svelte';
import { layoutTabs, visibleTabs } from '../../opscenter/layouts/layout-tabs.svelte';
import { layoutMode } from '../../opscenter/layouts/mode.svelte';
import { sessions } from '../../opscenter/api/sessions.svelte';
import { focusHistory, type FocusEntry } from '../focus-history/focus-history';
import { goTo } from '../nav-items/nav-items';
import type { AppChord } from './router';
import { stepTerminalFont } from '../terminal-font/terminal-font';
import { onMac, togglePalette } from '../palette/palette-host';

export function isLive(entry: FocusEntry): boolean {
    if (entry.kind === 'layout') return !layouts.data || layouts.data.some((l) => l.layout_uuid === entry.uuid);
    return !sessions.data || sessions.data.some((row) => row.session?.id === entry.id);
}

export function walk(dir: -1 | 1): boolean {
    const entry = focusHistory.step(dir, isLive);
    if (entry) void goTo(entry.kind === 'layout' ? entry : { kind: 'session', id: entry.id, tmuxName: entry.tmuxName });
    return true;
}

export function openLayoutTab(n: number): boolean {
    const known = layouts.data ? layouts.data.map((l) => l.layout_uuid) : null;
    const tabs = visibleTabs(layoutTabs.uuids, known, layoutMode.uuid);
    if (tabs.length === 0) return false;
    const uuid = n === 9 ? tabs[tabs.length - 1] : tabs[n - 1];
    if (uuid && uuid !== layoutMode.uuid) void goTo({ kind: 'layout', uuid });
    return true;
}

const DIGITS = [1, 2, 3, 4, 5, 6, 7, 8, 9];

const TEXT_SIZE: readonly [string, string, number][] = [['=', 'bigger', 1], ['-', 'smaller', -1], ['0', 'reset', 0]];

const ctrlCmd = (key: string): string => ['ctrl', 'cmd', key].join(' ');

const PALETTE_OTHER_KEYS = ['ctrl', 'shift', 'k'].join(' ');
const PALETTE_ACTIONS_KEYS = ['shift', 'cmd', 'p'].join(' ');

export const APP_CHORDS: readonly AppChord[] = [
    { id: 'history.back', key: '[', meta: true, accelerator: 'Cmd+[', keys: 'cmd [', labelKey: 'keys.page.app.back', run: () => walk(-1) },
    { id: 'history.forward', key: ']', meta: true, accelerator: 'Cmd+]', keys: 'cmd ]', labelKey: 'keys.page.app.forward', run: () => walk(1) },
    ...DIGITS.map((n): AppChord => ({
        id: `layout.tab.${n}`, key: String(n), meta: true, accelerator: `Cmd+${n}`, keys: `cmd ${n}`,
        labelKey: n === 9 ? 'keys.page.app.layout_last' : 'keys.page.app.layout_tab', run: () => openLayoutTab(n),
    })),
    { id: 'palette.open', key: 'k', meta: true, accelerator: 'Cmd+K', keys: 'cmd k', labelKey: 'keys.page.app.palette', inFields: true, run: () => onMac() && togglePalette('go') },
    { id: 'palette.open.other', key: 'k', ctrl: true, shift: true, accelerator: 'Ctrl+Shift+K', keys: PALETTE_OTHER_KEYS, labelKey: 'keys.page.app.palette_other', inFields: true, run: () => !onMac() && togglePalette('go') },
    { id: 'palette.actions', key: 'p', meta: true, shift: true, accelerator: 'Shift+Cmd+P', keys: PALETTE_ACTIONS_KEYS, labelKey: 'keys.page.app.palette_actions', inFields: true, run: () => togglePalette('actions') },
    ...TEXT_SIZE.map(([key, name, delta]): AppChord => ({
        id: `terminal.text.${name}`, key, meta: true, ctrl: true, accelerator: `Ctrl+Cmd+${key}`, keys: ctrlCmd(key),
        labelKey: `keys.page.app.text_${name}`, run: () => stepTerminalFont(delta),
    })),
];

export const APP_KEY_ROWS: readonly { keys: string; labelKey: string }[] = [
    { keys: 'cmd [', labelKey: 'keys.page.app.back' },
    { keys: 'cmd ]', labelKey: 'keys.page.app.forward' },
    { keys: 'cmd 1 to 8', labelKey: 'keys.page.app.layout_tab' },
    { keys: 'cmd 9', labelKey: 'keys.page.app.layout_last' },
    { keys: 'cmd k', labelKey: 'keys.page.app.palette' },
    { keys: PALETTE_OTHER_KEYS, labelKey: 'keys.page.app.palette_other' },
    { keys: PALETTE_ACTIONS_KEYS, labelKey: 'keys.page.app.palette_actions' },
    ...TEXT_SIZE.map(([key, name]) => ({ keys: ctrlCmd(key), labelKey: `keys.page.app.text_${name}` })),
];
