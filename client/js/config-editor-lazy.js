
console.log('[ConfigEditorLazy Module] Loading...');

(function () {
'use strict';

const FETCH_DEPTH = 1;

function needsFetch(node) {
    return !!(node && node.is_dir && node.children_loaded === false);
}

/* could not */
async function childrenFor(rootId, node, projectPath) {
    if (node && node.list_error) {
        return {
            status: 'list_error',
            message: window.ConfigEditorRoots.listErrorNotice(node.list_error),
        };
    }
    if (!needsFetch(node)) {
        return { status: 'have', nodes: (node && node.children) || [] };
    }
    try {
        const resp = await window.API.getConfigFileTree(rootId, projectPath, {
            path: node.rel_path,
            depth: FETCH_DEPTH,
            ignored: true,
        });
        return { status: 'loaded', nodes: (resp && resp.tree) || [] };
    } catch (err) {
        // could not be read
        // could not
        const detail = (err && err.message) || String(err);
        console.warn(`ConfigEditorLazy: expand failed for ${rootId}:${node.rel_path}:`, err);
        return {
            status: 'failed',
            message: window.ConfigEditorRoots.expandFailedNotice(detail),
        };
    }
}

window.ConfigEditorLazy = { FETCH_DEPTH, needsFetch, childrenFor };
console.log('[ConfigEditorLazy Module] Exported as window.ConfigEditorLazy');

}());
