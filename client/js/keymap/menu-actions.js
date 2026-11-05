import { LETTERS } from '../menu-keys.js';
import { def } from './define.js';

export function menuActionId(entry) {
    return `menu.${entry.name}`;
}

export const MENU_ACTIONS = Object.freeze(LETTERS.map((entry) => def(menuActionId(entry), 'menus', 'menu', [entry.letter], {
    owner: 'client/js/menu-keys.js',
    labelKey: `keymap.menu.${entry.name}`,
    menus: ['item-menu'],
    mayShare: typeof entry.shares === 'string',
})));
