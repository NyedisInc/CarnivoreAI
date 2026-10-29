/* could not */

console.log('[ConfigEditorFilter Module] Loading...');

(function () {
'use strict';

const MATCH_LIMIT = 500;

/*  hidden  */
function isHidden(node, prefs) {
    if (!node || !prefs) return false;
    if (prefs.hideDot && String(node.name || '').startsWith('.')) return true;
    if (prefs.hideIgnored && node.is_ignored === true) return true;
    return false;
}

/*  hidden  */
function visibleNodes(nodes, prefs) {
    return (nodes || []).filter((n) => !isHidden(n, prefs));
}

function filterTree(nodes, query, prefs, limit = MATCH_LIMIT) {
    const needle = String(query || '').trim().toLowerCase();
    const state = { matches: 0, truncated: false };
    if (!needle) return { nodes: visibleNodes(nodes, prefs), matches: 0, truncated: false };

    const walk = (list) => {
        const kept = [];
        for (const node of visibleNodes(list, prefs)) {
            if (state.matches >= limit) {
                state.truncated = true;
                break;
            }
            const selfMatch = String(node.name || '').toLowerCase().includes(needle);
            if (!node.is_dir) {
                if (selfMatch) {
                    state.matches += 1;
                    kept.push(node);
                }
                continue;
            }
            if (selfMatch) {
                state.matches += 1;
                kept.push({ ...node, filter_expanded: false });
                continue;
            }
            const below = walk(node.children || []);
            if (below.length) {
                kept.push({ ...node, children: below, children_loaded: true, filter_expanded: true });
            }
        }
        return kept;
    };

    const kept = walk(nodes);
    return { nodes: kept, matches: state.matches, truncated: state.truncated };
}

window.ConfigEditorFilter = { MATCH_LIMIT, isHidden, visibleNodes, filterTree };
console.log('[ConfigEditorFilter Module] Exported as window.ConfigEditorFilter');

}());
