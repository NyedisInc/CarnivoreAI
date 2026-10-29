/*  hidden  <button> */

console.log('[ConfigEditorNewFile Module] Loading...');

(function () {
    let overlayEl = null;

    function esc(value) {
        const div = document.createElement('div');
        div.textContent = String(value == null ? '' : value);
        return div.innerHTML;
    }

    function close() {
        if (!overlayEl) return;
        window.ModalStack.pop(overlayEl);
        if (overlayEl.parentNode) overlayEl.parentNode.removeChild(overlayEl);
        overlayEl = null;
    }

    function showError(message) {
        const el = overlayEl && overlayEl.querySelector('#config-editor-new-error');
        if (!el) return;
        el.textContent = message;
        el.hidden = false;
    }

    function promptHtml(roots) {
        const options = roots.map(
            r => `<option value="${esc(r.id)}">${esc(r.label)}</option>`,
        ).join('');
        return (
            '<div class="modal-content" role="dialog" aria-modal="true" aria-labelledby="config-editor-new-title">' +
            '  <div class="modal-header" id="config-editor-new-title">» new file</div>' +
            '  <div class="modal-body">' +
            '    <div class="config-editor-new-form">' +
            '      <label for="config-editor-new-root">where</label>' +
            `      <select id="config-editor-new-root">${options}</select>` +
            '      <label for="config-editor-new-path">path, relative to that root</label>' +
            '      <input type="text" id="config-editor-new-path" placeholder="notes.md" ' +
            '             autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" />' +
            '      <div class="config-editor-new-hint">the directory must already exist. this does not create folders.</div>' +
            '      <div id="config-editor-new-error" class="config-editor-error" hidden></div>' +
            '    </div>' +
            '  </div>' +
            '  <div class="modal-footer">' +
            '    <button type="button" class="modal-btn modal-btn-secondary" id="config-editor-new-cancel">cancel</button>' +
            '    <button type="button" class="modal-btn modal-btn-primary" id="config-editor-new-create">create</button>' +
            '  </div>' +
            '</div>'
        );
    }

    function open(roots, projectPath) {
        return new Promise((resolve) => {
            close();
            overlayEl = document.createElement('div');
            overlayEl.className = 'modal-overlay';
            overlayEl.setAttribute('data-modal', 'config-new-file');
            overlayEl.innerHTML = promptHtml(roots);
            document.body.appendChild(overlayEl);

            const finish = (value) => { close(); resolve(value); };
            window.ModalStack.push(overlayEl, { onEscape: () => finish(null) });

            const pathInput = overlayEl.querySelector('#config-editor-new-path');
            const rootSelect = overlayEl.querySelector('#config-editor-new-root');
            const createBtn = overlayEl.querySelector('#config-editor-new-create');

            const submit = async () => {
                const root = rootSelect.value;
                const path = (pathInput.value || '').trim();
                if (!path) {
                    showError('a file name is required');
                    return;
                }
                createBtn.disabled = true;
                try {
                    await window.API.createConfigFile({
                        root,
                        path,
                        content: '',
                        project_path: root === 'user' ? null : projectPath,
                    });
                    finish({ root, path });
                } catch (err) {
                    showError(err.message || String(err));
                    createBtn.disabled = false;
                }
            };

            createBtn.addEventListener('click', submit);
            overlayEl.querySelector('#config-editor-new-cancel')
                .addEventListener('click', () => finish(null));
            overlayEl.addEventListener('click', (e) => { if (e.target === overlayEl) finish(null); });
            pathInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') { e.preventDefault(); submit(); }
            });

            setTimeout(() => { try { pathInput.focus(); } catch (_) {  } }, 50);
        });
    }

    window.ConfigEditorNewFile = { open, close };
    console.log('[ConfigEditorNewFile Module] Exported as window.ConfigEditorNewFile');
})();
