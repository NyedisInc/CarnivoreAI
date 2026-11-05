import { APP_ACTIONS } from './actions-app.js';
import { LIST_ACTIONS } from './actions-lists.js';
import { MENU_ACTIONS } from './menu-actions.js';
import { POINTER_ACTIONS } from './actions-pointer.js';

export const CATEGORIES = Object.freeze(['app', 'navigation', 'terminal', 'menus', 'lists', 'mouse', 'desktop', 'standard']);

export const ACTIONS = Object.freeze([...APP_ACTIONS, ...LIST_ACTIONS, ...MENU_ACTIONS, ...POINTER_ACTIONS]);

export const categoryLabelKey = (category) => `keymap.category.${category}`;
