import { LETTERS } from '../menu-keys.js';
import { MENU_GROUPS } from './menu-tree.js';
import { menuActionId } from './menu-actions.js';

export const TOP_GROUPS = Object.freeze(['app', 'pages', 'sidebar', 'terminal', 'menus', 'mouse', 'desktop', 'standard']);

export const GROUP_RULES = Object.freeze([
    [/^history\./, ['app', 'history']],
    [/^layout\.tab\./, ['app', 'layout-tabs']],
    [/^palette\./, ['app', 'palette']],
    [/^terminal\.text\./, ['app', 'text-size']],
    [/^(settings\.open|file\.save|form\.submit|search\.focus)$/, ['app', 'general']],
    [/^nav\./, ['pages', 'rail']],
    [/^feed\./, ['pages', 'automations-feed']],
    [/^review\./, ['pages', 'automations-review']],
    [/^automations\./, ['pages', 'automation-detail']],
    [/^catalog\./, ['pages', 'skills-catalog']],
    [/^elite\./, ['pages', 'warez-board']],
    [/^sidebar\.row\./, ['sidebar', 'rows']],
    [/^terminal\.search\./, ['terminal', 'search']],
    [/^terminal\.zoom\./, ['terminal', 'zoom']],
    [/^terminal\.(copy|paste|newline)$/, ['terminal', 'text']],
    [/^keybar\./, ['terminal', 'phone-key-bar']],
    [/^desktop\.(new_|open_)/, ['desktop', 'file-menu']],
    [/^desktop\.(quit)$/, ['desktop', 'app-menu']],
    [/^desktop\.hotkey$/, ['desktop', 'whole-computer']],
    [/^desktop\.role\./, ['desktop', 'edit-and-window-menus']],
    [/^standard\./, ['standard']],
]);

export function groupPath(action) {
    if (action.category === 'mouse') return ['mouse', action.mouse[0].replace('+', '-')];
    const rule = GROUP_RULES.find(([pattern]) => pattern.test(action.id));
    return rule ? rule[1] : null;
}

export function entryForItem(itemId) {
    return LETTERS.find((e) => e.ids.includes(itemId)) ?? LETTERS.find((e) => (e.verbs ?? []).includes(itemId.split('-')[0]));
}

export const itemLabelKey = (itemId) => `keymap.item.${itemId.replace(/:/g, '.')}`;

export const groupLabelKey = (path) => `keymap.group.${path.join('.')}`;

function place(root, path, leaf) {
    let level = root;
    const walked = [];
    for (const id of path) {
        walked.push(id);
        let branch = level.find((n) => n.id === id && n.children);
        if (!branch) {
            branch = { id, path: [...walked], labelKey: groupLabelKey(walked), children: [] };
            level.push(branch);
        }
        level = branch.children;
    }
    level.push(leaf);
}

function placeItems(root, byId, path, items) {
    for (const item of items) {
        if (typeof item !== 'string') {
            placeItems(root, byId, [...path, item.branch], item.items);
            continue;
        }
        const entry = entryForItem(item);
        const action = entry ? byId.get(menuActionId(entry)) : undefined;
        if (action) place(root, path, { id: `${path.slice(1).join('/')}/${item}`, labelKey: itemLabelKey(item), action, itemId: item });
    }
}

export function buildTree(actions) {
    const root = [];
    const byId = new Map(actions.map((a) => [a.id, a]));
    for (const action of actions) {
        const path = action.id.startsWith('menu.') ? null : groupPath(action);
        if (path) place(root, path, { id: action.id, labelKey: action.labelKey, action });
    }
    for (const group of MENU_GROUPS) {
        for (const menu of group.menus) {
            placeItems(root, byId, ['menus', group.id, menu.id], menu.items);
        }
    }
    return TOP_GROUPS.map((id) => root.find((n) => n.id === id)).filter(Boolean);
}

export function countLeaves(node) {
    return node.children ? node.children.reduce((n, c) => n + countLeaves(c), 0) : 1;
}
