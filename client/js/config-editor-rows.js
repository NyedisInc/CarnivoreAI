/* padding */

console.log('[ConfigEditorRows Module] Loading...');

(function () {
'use strict';

const CHEVRON_SVG = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">'
    + '<path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
    + '</svg>';

function esc(value) {
    const div = document.createElement('div');
    div.textContent = String(value == null ? '' : value);
    return div.innerHTML;
}

function indentHtml(depth) {
    let html = '';
    for (let i = 0; i < depth; i++) {
        html += '<span class="config-editor-guide" aria-hidden="true"></span>';
    }
    return html;
}

function dirRowHtml(node, depth, isRoot) {
    return (
        indentHtml(depth)
        + `<span class="config-editor-toggle-glyph" aria-hidden="true">${CHEVRON_SVG}</span>`
        + window.SessionStatusUI.folderIconSvg()
        + `<span class="config-editor-node-name${isRoot ? ' config-editor-root-label' : ''}">${esc(node.name)}</span>`
        + (node.read_only ? ' <span class="config-editor-badge">read-only</span>' : '')
    );
}

function fileRowHtml(node, depth) {
    return (
        indentHtml(depth)
        + '<span class="config-editor-toggle-spacer" aria-hidden="true"></span>'
        + window.SessionStatusUI.fileIconSvg()
        + `<span class="config-editor-node-name">${esc(node.name)}</span>`
        + (node.is_executable ? ' <span class="config-editor-badge config-editor-badge--exec">runs automatically</span>' : '')
        + (node.is_sensitive ? ` <span class="config-editor-badge config-editor-badge--sensitive">${window.SessionStatusUI.lockIconSvg()}sensitive</span>` : '')
    );
}

function noticeLi(message) {
    const li = document.createElement('li');
    li.className = 'config-editor-node config-editor-node--notice';
    const el = document.createElement('div');
    el.className = 'config-editor-notice';
    el.textContent = message;
    li.appendChild(el);
    return li;
}

function errorEl(message) {
    const el = document.createElement('div');
    el.className = 'config-editor-error';
    el.textContent = message;
    return el;
}

window.ConfigEditorRows = { esc, indentHtml, dirRowHtml, fileRowHtml, noticeLi, errorEl };
console.log('[ConfigEditorRows Module] Exported as window.ConfigEditorRows');

}());
