
const esc = (v) => String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

export function rowsHtml(rows) {
    return rows.map((row) => {
        const data = Object.entries(row.data || {}).map(([k, v]) => ` data-${k}="${esc(v)}"`).join('');
        const hintId = `${row.id}-hint`;
        return `<div role="option" id="${esc(row.id)}" data-choice-option="${esc(row.value)}"${data}`
            + (row.hint ? ` aria-describedby="${esc(hintId)}"` : '')
            + (row.disabled ? ' aria-disabled="true"' : '') + '>'
            + `<span class="lpd-label">${esc(row.label)}</span>`
            + row.tags.map((t) => `<span class="lpd-tag">${esc(t)}</span>`).join('')
            + (row.kindTag ? `<span class="lpd-tag lpd-tag--kind" data-kind="${esc(row.kind)}">${esc(row.kindTag)}</span>` : '')
            + (row.hint ? `<span class="cdd__sr" id="${esc(hintId)}">${esc(row.hint)}</span>` : '')
            + '</div>';
    }).join('');
}

export function fakeHandle(rows, value = '') {
    const state = { rows: rows.map((r) => ({ ...r })), value, answer: null, destroyed: false, focused: 0 };
    return {
        state,
        selected() {
            const r = state.rows.find((x) => x.value === state.value);
            return r ? { value: r.value, data: { ...r.data }, disabled: !!r.disabled } : null;
        },
        setEnabled(predicate) { state.rows.forEach((r) => { r.disabled = !predicate(r.data || {}); }); },
        selectFirst(predicate) {
            const r = state.rows.find((x) => !x.disabled && predicate(x));
            if (r) state.value = r.value;
        },
        account() { return state.answer; },
        focus() { state.focused += 1; },
        destroy() { state.destroyed = true; },
        pick(v) { const r = state.rows.find((x) => x.value === v); if (r && !r.disabled) state.value = v; },
    };
}
