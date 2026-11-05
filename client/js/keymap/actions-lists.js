import { def } from './define.js';

const CATALOG = 'web/src/lib/catalog/keys.ts';
const FEED = 'web/src/lib/automations/feed/feed-keys.ts';
const REVIEW = 'web/src/lib/automations/review/review-keys.ts';
const ROWS = 'web/src/lib/sidebar-shell/row-reorder.ts';
const PALETTE = 'web/src/lib/palette/Palette.svelte';
const ELITE = 'web/src/lib/elite/EliteScreen.svelte';

const CATALOG_ACTIONS = [
    ['search', ['/'], 'skill.browse.keys.search'], ['next', ['j'], 'keymap.action.catalog.next'], ['prev', ['k'], 'keymap.action.catalog.prev'],
    ['open', ['enter'], 'skill.browse.keys.open'], ['install', ['i'], 'skill.browse.keys.install'], ['try', ['t'], 'skill.browse.keys.try'],
    ['update', ['u'], 'skill.browse.keys.update'], ['help', ['?'], 'skill.browse.keys.help'],
].map(([id, keys, labelKey]) => def(`catalog.${id}`, 'lists', 'list:catalog', keys, {
    owner: CATALOG, labelKey, altLabelKeys: id === 'next' || id === 'prev' ? ['skill.browse.keys.move'] : [],
}));

const AUTOMATION_ACTIONS = [
    def('feed.next', 'lists', 'list:feed', ['j', 'arrowdown'], { owner: FEED }),
    def('feed.prev', 'lists', 'list:feed', ['k', 'arrowup'], { owner: FEED }),
    def('feed.next_changed', 'lists', 'list:feed', ['u'], { owner: FEED }),
    def('feed.prev_changed', 'lists', 'list:feed', ['shift+u'], { owner: FEED }),
    def('feed.next_unread', 'lists', 'list:feed', ['n'], { owner: FEED }),
    def('feed.toggle_fold', 'lists', 'list:feed', ['o'], { owner: FEED }),
    def('feed.search', 'lists', 'list:feed', ['/'], { owner: FEED }),
    def('feed.close_sheet', 'lists', 'list:feed', ['escape'], { owner: FEED }),
    def('review.next', 'lists', 'list:review', ['j'], { owner: REVIEW }),
    def('review.prev', 'lists', 'list:review', ['k'], { owner: REVIEW }),
    def('review.open', 'lists', 'list:review', ['enter'], { owner: REVIEW }),
    def('review.good', 'lists', 'list:review', ['r'], { owner: REVIEW }),
    def('automations.detail.older', 'lists', 'list:automations', ['['], { owner: 'web/src/lib/automations/pane/DetailPane.svelte' }),
    def('automations.detail.newer', 'lists', 'list:automations', [']'], { owner: 'web/src/lib/automations/pane/DetailPane.svelte' }),
];

const SURFACE_ACTIONS = [
    def('sidebar.row.rename', 'lists', 'list:sidebar', ['f2'], { owner: ROWS }),
    def('sidebar.row.move_up', 'lists', 'list:sidebar', ['alt+arrowup'], { owner: ROWS }),
    def('sidebar.row.move_down', 'lists', 'list:sidebar', ['alt+arrowdown'], { owner: ROWS }),
    def('sidebar.row.pin', 'lists', 'list:sidebar', ['p'], { owner: ROWS }),
    def('palette.next', 'lists', 'overlay:palette', ['ctrl+n'], { owner: PALETTE }),
    def('palette.prev', 'lists', 'overlay:palette', ['ctrl+p'], { owner: PALETTE }),
    def('palette.pick', 'lists', 'overlay:palette', ['enter'], { owner: PALETTE }),
    def('palette.pick_new', 'lists', 'overlay:palette', ['cmd+enter'], { owner: PALETTE, mayShare: true }),
    def('palette.chip', 'lists', 'overlay:palette', ['tab'], { owner: PALETTE }),
    def('palette.chip_remove', 'lists', 'overlay:palette', ['backspace'], { owner: PALETTE }),
    ...[1, 2, 3, 4, 5].map((n) => def(`palette.pick_${n}`, 'lists', 'overlay:palette', { mac: [`cmd+${n}`] }, { owner: PALETTE, mayShare: true })),
];

const ELITE_ACTIONS = [
    ['next', ['arrowdown', 'j'], 'next'], ['prev', ['arrowup', 'k'], 'prev'], ['page_down', ['pagedown'], 'page_down'],
    ['page_up', ['pageup'], 'page_up'], ['first', ['home'], 'first'], ['last', ['end'], 'last'], ['tag', ['space'], 'tag'],
    ['open', ['enter'], 'enter'], ['add', ['+'], 'add'], ['try', ['='], 'try'], ['scroll_down', ['alt+arrowdown'], 'scroll_down'],
    ['scroll_up', ['alt+arrowup'], 'scroll_up'], ['batch_d', ['shift+d'], 'batch_d'], ['batch_u', ['shift+u'], 'batch_u'],
    ['batch_c', ['shift+c'], 'batch_c'], ['comment', ['shift+m'], 'comment'], ['escape', ['escape'], 'escape'],
].map(([id, keys, label]) => def(`elite.${id}`, 'lists', 'list:elite', keys, { owner: ELITE, labelKey: `warez.elite.key.${label}` }));

const ELITE_GLOBAL = [
    ['replay_logo', 'alt+l', 'replay_logo'], ['dial', 'alt+d', 'dial'], ['hangup', 'alt+h', 'hangup'],
].map(([id, key, label]) => def(`elite.${id}`, 'lists', 'list:elite', [key], { owner: ELITE, labelKey: `warez.elite.key.${label}` }));

export const LIST_ACTIONS = Object.freeze([
    ...CATALOG_ACTIONS, ...AUTOMATION_ACTIONS, ...SURFACE_ACTIONS, ...ELITE_ACTIONS, ...ELITE_GLOBAL,
]);
