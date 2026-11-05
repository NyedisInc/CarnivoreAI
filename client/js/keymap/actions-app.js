import { def } from './define.js';

const CHORDS = 'web/src/lib/app-keys/chords.ts';
const SEARCH = 'web/src/lib/terminal-search/search-keys.ts';
const RAIL = 'web/src/opscenter/shell/rail-hints.ts';
const MENU_JS = 'macOS/app-menu/';

const APP = [
    def('history.back', 'app', 'global', { mac: ['cmd+['] }, { owner: CHORDS, labelKey: 'keys.page.app.back', menus: ['go'], rebindable: true }),
    def('history.forward', 'app', 'global', { mac: ['cmd+]'] }, { owner: CHORDS, labelKey: 'keys.page.app.forward', menus: ['go'], rebindable: true }),
    ...[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => def(`layout.tab.${n}`, 'app', 'global', { mac: [`cmd+${n}`] }, {
        owner: CHORDS,
        rebindable: true,
        labelKey: n === 9 ? 'keys.page.app.layout_last' : `keymap.action.layout.tab.${n}`,
        altLabelKeys: n === 9 ? [] : ['keys.page.app.layout_tab'],
    })),
    def('palette.open', 'app', 'global', { mac: ['cmd+k'], other: ['ctrl+shift+k'] }, {
        owner: CHORDS, labelKey: 'keys.page.app.palette', altLabelKeys: ['keys.page.app.palette_other'], rebindable: true,
    }),
    def('palette.actions', 'app', 'global', { mac: ['shift+cmd+p'] }, { owner: CHORDS, labelKey: 'keys.page.app.palette_actions', rebindable: true }),
    def('terminal.text.bigger', 'app', 'global', { mac: ['ctrl+cmd+='] }, { owner: CHORDS, labelKey: 'keys.page.app.text_bigger', rebindable: true }),
    def('terminal.text.smaller', 'app', 'global', { mac: ['ctrl+cmd+-'] }, { owner: CHORDS, labelKey: 'keys.page.app.text_smaller', rebindable: true }),
    def('terminal.text.reset', 'app', 'global', { mac: ['ctrl+cmd+0'] }, { owner: CHORDS, labelKey: 'keys.page.app.text_reset', rebindable: true }),
    def('settings.open', 'app', 'global', { mac: ['cmd+,'], other: ['ctrl+,'] }, {
        owner: 'web/src/lib/settings-page/settings-shortcut.ts', labelKey: 'keys.page.settings.open', menus: ['carnivore'],
    }),
    def('file.save', 'app', 'list:files', { mac: ['cmd+s'], other: ['ctrl+s'] }, { owner: 'web/src/lib/open-files/FileScreen.svelte' }),
    def('form.submit', 'app', 'field', { mac: ['cmd+enter'], other: ['ctrl+enter'] }, {
        owner: 'web/src/cplugs/huddle/HuddleBody.svelte',
    }),
    def('search.focus', 'app', 'list:pages', ['/'], { owner: 'web/src/lib/drawer-tabs/DrawerSearch.svelte' }),
];

const NAV = [
    ['home', '..', 'opscenter.nav.home'], ['hosts', 'h', 'opscenter.nav.hosts'], ['sessions', 's', 'opscenter.nav.sessions'],
    ['warroom', 'c', 'opscenter.nav.warroom'], ['widgets', 'w', 'opscenter.nav.widgets'], ['warez', 'r', 'opscenter.nav.warez'],
    ['blueprints', 'b', 'blueprint.title'], ['automations', 'u', 'opscenter.nav.automations'], ['providers', 'a', 'opscenter.nav.providers'],
    ['settings', '`', 'opscenter.nav.settings'], ['wrappers', 'l', 'opscenter.nav.wrappers'],
].map(([id, key, labelKey]) => def(`nav.${id}`, 'navigation', 'menu:rail', [key], {
    owner: RAIL,
    labelKey: id === 'settings' ? 'keymap.action.nav.settings' : labelKey,
    altLabelKeys: id === 'settings' ? [labelKey] : [],
}));

const TERMINAL = [
    def('terminal.search.open', 'terminal', 'terminal-screen', { mac: ['cmd+f'], other: ['ctrl+f'] }, { owner: SEARCH, labelKey: 'keys.page.search.open' }),
    def('terminal.search.next', 'terminal', 'overlay:terminal-search', { mac: ['cmd+g', 'enter'], other: ['ctrl+g', 'enter'] }, { owner: SEARCH, labelKey: 'keys.page.search.next' }),
    def('terminal.search.prev', 'terminal', 'overlay:terminal-search', { mac: ['shift+cmd+g', 'shift+enter'], other: ['shift+ctrl+g', 'shift+enter'] }, { owner: SEARCH, labelKey: 'keys.page.search.prev' }),
    def('terminal.search.jump', 'terminal', 'overlay:terminal-search', ['arrowup', 'arrowdown'], { owner: SEARCH, labelKey: 'keys.page.search.jump' }),
    def('terminal.search.close', 'terminal', 'overlay:terminal-search', ['escape'], { owner: SEARCH, labelKey: 'keys.page.search.close' }),
    def('terminal.zoom.toggle', 'terminal', 'terminal-screen', { mac: ['shift+cmd+enter'] }, {
        owner: 'web/src/opscenter/engine/layout-zoom.svelte.ts', labelKey: 'keys.page.zoom.toggle',
    }),
    def('terminal.zoom.restore', 'terminal', 'terminal-screen', ['shift+escape'], {
        owner: 'web/src/opscenter/engine/layout-zoom.svelte.ts', labelKey: 'keys.page.zoom.restore',
    }),
    def('terminal.copy', 'terminal', 'terminal-pane', { mac: ['cmd+c'], other: ['ctrl+shift+c'] }, { owner: 'client/js/clipboard.js', mayShare: true }),
    def('terminal.paste', 'terminal', 'terminal-pane', { mac: ['cmd+v'], other: ['ctrl+shift+v'] }, { owner: 'client/js/terminal.js', mayShare: true }),
    def('terminal.newline', 'terminal', 'terminal-pane', ['shift+enter'], { owner: 'client/js/terminal.js' }),
];

const DESKTOP = [
    def('desktop.new_session', 'desktop', 'electron-menu', { mac: ['cmd+n'] }, { owner: `${MENU_JS}file.js`, menus: ['file'] }),
    def('desktop.new_window', 'desktop', 'electron-menu', { mac: ['shift+cmd+n'] }, { owner: `${MENU_JS}file.js`, menus: ['file'] }),
    def('desktop.open_project', 'desktop', 'electron-menu', { mac: ['cmd+o'] }, { owner: `${MENU_JS}file.js`, menus: ['file'] }),
    def('desktop.quit', 'desktop', 'electron-menu', { mac: ['cmd+q'], other: ['ctrl+q'] }, { owner: `${MENU_JS}carnivore.js`, menus: ['carnivore', 'tray'] }),
    def('desktop.hotkey', 'desktop', 'os-global', { mac: ['ctrl+alt+cmd+c'] }, { owner: 'macOS/hotkey.js' }),
    ...[
        ['undo', 'cmd+z'], ['redo', 'shift+cmd+z'], ['cut', 'cmd+x'], ['copy', 'cmd+c'], ['paste', 'cmd+v'], ['select_all', 'cmd+a'], ['reload', 'cmd+r'],
        ['force_reload', 'shift+cmd+r'], ['dev_tools', 'alt+cmd+i'], ['zoom_reset', 'cmd+0'], ['zoom_in', 'cmd++'],
        ['zoom_out', 'cmd+-'], ['fullscreen', 'ctrl+cmd+f'], ['minimize', 'cmd+m'], ['close', 'cmd+w'], ['hide', 'cmd+h'],
        ['hide_others', 'alt+cmd+h'],
].map(([id, chord]) => def(`desktop.role.${id}`, 'desktop', 'electron-menu', { mac: [chord] }, { owner: `${MENU_JS}chords.js`, mayShare: id === 'copy' || id === 'paste' })),
];

export const APP_ACTIONS = Object.freeze([...APP, ...NAV, ...TERMINAL, ...DESKTOP]);
