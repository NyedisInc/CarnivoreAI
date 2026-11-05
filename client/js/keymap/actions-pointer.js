import { def } from './define.js';

const STD = 'web/src/lib/zone-shell/key-nav.ts';

const STANDARD = [
    def('standard.escape', 'standard', 'global', ['escape'], { owner: 'client/js/modal-stack.js', fixedKey: 'keymap.fixed.standard' }),
    def('standard.menu_key', 'standard', 'global', ['shift+f10', 'menu'], { owner: 'web/src/lib/zone-shell/key-nav.ts', fixedKey: 'keymap.fixed.standard' }),
    def('standard.move', 'standard', 'global', ['arrowup', 'arrowdown', 'arrowleft', 'arrowright'], { owner: STD, fixedKey: 'keymap.fixed.standard' }),
    def('standard.edges', 'standard', 'global', ['home', 'end'], { owner: STD, fixedKey: 'keymap.fixed.standard' }),
    def('standard.activate', 'standard', 'global', ['enter', 'space'], { owner: STD, fixedKey: 'keymap.fixed.standard' }),
    def('standard.tab', 'standard', 'global', ['tab', 'shift+tab'], { owner: STD, fixedKey: 'keymap.fixed.standard' }),
];

const GESTURE_ROWS = [
    ['tab.close', 'middle', 'list:tabs', 'web/src/opscenter/shell/TabStrip.svelte'],
    ['sidebar.row.middle', 'middle', 'list:sidebar', 'web/src/lib/sidebar-shell/row-middle-click.ts'],
    ['toast.dismiss', 'middle', 'overlay:toast', 'web/src/lib/toast-stack/ToastCard.svelte'],
    ['crosstalk.card.dismiss', 'middle', 'overlay:crosstalk-card', 'web/src/lib/crosstalk/terminal-cards/CardStack.svelte'],
    ['pack.toast.dismiss', 'middle', 'overlay:pack-toast', 'web/src/lib/pack-op-toast/PackOpToast.svelte'],
    ['huddle.post.dismiss', 'middle', 'list:task-manager', 'web/src/cplugs/huddle/task-manager-middle-dismiss.ts'],
    ['confirm.ok', 'middle', 'overlay:confirm', 'web/src/lib/confirm-ok/confirm-ok.ts'],
    ['item.menu.open', 'right', 'global', 'web/src/lib/item-menu/page-row.ts'],
    ['split.reset', 'double', 'list:layout', 'web/src/lib/split-divider/SplitDivider.svelte'],
    ['gutter.reset', 'double', 'list:layout', 'web/src/opscenter/engine/Gutter.svelte'],
    ['drawer.reset', 'double', 'list:drawer', 'web/src/lib/drawer/resize.ts'],
    ['crosstalk.split.reset', 'double', 'list:crosstalk', 'web/src/opscenter/cells/crosstalk/Cell.svelte'],
    ['huddle.group.rename', 'double', 'list:task-manager', 'web/src/cplugs/huddle/TaskManagerSections.svelte'],
    ['theme.apply', 'double', 'list:themes', 'web/src/lib/themes-page/ThemeCard.svelte'],
    ['terminal.zoom.click', 'shift+click', 'list:layout', 'web/src/opscenter/cells/terminal-live/TerminalActions.svelte'],
    ['huddle.fold_all', 'shift+click', 'list:task-manager', 'web/src/cplugs/huddle/TaskManagerSections.svelte'],
    ['huddle.status_fold_all', 'shift+click', 'list:task-manager', 'web/src/cplugs/huddle/TaskManagerStatusSections.svelte'],
    ['huddle.question.dismiss', 'shift+click', 'list:task-manager', 'web/src/cplugs/huddle/ask/ask-model.ts'],
    ['swarm.lineage', 'shift+click', 'list:swarm', 'web/src/cplugs/huddle/swarm/SwarmOrg.svelte'],
    ['swarm.open_terminal', 'shift+click', 'list:swarm', 'web/src/cplugs/huddle/swarm/SwarmLedger.svelte'],
    ['files.row.range', 'shift+click', 'list:files', 'web/src/opscenter/cells/files/FileRow.svelte'],
    ['log.field.filter', 'alt+click', 'list:log', 'web/src/opscenter/log/LogRow.svelte'],
    ['palette.row.new', 'cmd+click', 'overlay:palette', 'web/src/lib/palette/Palette.svelte'],
    ['terminal.scroll', 'wheel', 'terminal-pane', 'client/js/terminal-scroll.js'],
    ['swarm.org.zoom', 'wheel', 'list:swarm', 'web/src/cplugs/huddle/swarm/SwarmOrg.svelte'],
];

const MOUSE = GESTURE_ROWS.map(([id, gesture, scope, owner]) => def(`mouse.${id}`, 'mouse', scope, [], { owner, mouse: [gesture] }));

const KEY_BAR = [
    ['slash', 'slash_hint'], ['esc', 'esc_hint'], ['tab', 'tab_hint'], ['shifttab', 'shifttab_hint'], ['up', 'up_hint'],
    ['down', 'down_hint'], ['left', 'left_hint'], ['right', 'right_hint'], ['enter', 'enter_hint'], ['undo', 'undo_hint'],
    ['stash', 'stash_hint'], ['tools', 'paste_hint'],
].map(([id, hint]) => def(`keybar.${id}`, 'terminal', 'list:key-bar', [], {
    owner: 'client/js/terminal-key-bar.js', labelKey: `terminal.keybar.${hint}`, mouse: ['tap'],
}));

export const POINTER_ACTIONS = Object.freeze([...STANDARD, ...KEY_BAR, ...MOUSE]);
