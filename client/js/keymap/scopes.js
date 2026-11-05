
export const FIXED_SCOPES = Object.freeze([
    'global', 'terminal-screen', 'terminal-pane', 'field', 'menu', 'electron-menu', 'os-global',
]);

const EVERYWHERE = new Set(['electron-menu', 'os-global']);

const PAIRS = Object.freeze([['terminal-screen', 'terminal-pane']]);

export function isScope(scope) {
    return FIXED_SCOPES.includes(scope) || /^(overlay|list|menu):[a-z0-9-]+$/.test(String(scope));
}

export function scopesOverlap(a, b, hasCmd = false) {
    if (a === b || EVERYWHERE.has(a) || EVERYWHERE.has(b)) return true;
    const other = a === 'global' ? b : b === 'global' ? a : null;
    if (other !== null) return isMenu(other) ? hasCmd : true;
    if ((a === 'field' && b.startsWith('overlay:')) || (b === 'field' && a.startsWith('overlay:'))) return true;
    return PAIRS.some(([x, y]) => (a === x && b === y) || (a === y && b === x));
}

function isMenu(scope) {
    return scope === 'menu' || scope.startsWith('menu:');
}
