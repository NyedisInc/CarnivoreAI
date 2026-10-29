/* the page terminal */

console.log('[ConfigEditorModal Module] Loading...');

(function () {
    let activeFile = null;
    let overlayEl = null;
    let inPlace = false;
    let stopWatching = null;
    let openGeneration = 0;
    let viewCleanup = null;

    function isMarkdown(path) {
        return /\.md$/i.test(path || '');
    }

    function esc(value) {
        const div = document.createElement('div');
        div.textContent = String(value == null ? '' : value);
        return div.innerHTML;
    }

    function isDirty() {
        return !!(activeFile && activeFile.dirty);
    }

    /* there is nothing */
    async function confirmDiscardIfDirty() {
        if (!isDirty()) return true;
        return window.App.showConfirmModal(
            'discard unsaved changes?',
            `"${activeFile.path}" has unsaved edits.`,
            'closing now will lose them. this cannot be undone.',
            'discard',
            'keep editing',
            'danger'
        );
    }

    function close() {
        openGeneration += 1;
        if (activeFile && activeFile.cmEditor) {
            try { activeFile.cmEditor.destroy(); } catch (_) {  }
        }
        if (overlayEl) {
            if (!inPlace) window.ModalStack.pop(overlayEl);
            if (overlayEl.parentNode) overlayEl.parentNode.removeChild(overlayEl);
        }
        if (viewCleanup) {
            try { viewCleanup(); } catch (_) {  }
        }
        viewCleanup = null;
        if (stopWatching) stopWatching();
        stopWatching = null;
        overlayEl = null;
        activeFile = null;
        inPlace = false;
    }

    function isInPlace() {
        return !!(overlayEl && inPlace);
    }

    async function closeGuarded() {
        if (!(await confirmDiscardIfDirty())) return;
        close();
    }

    async function open(rootId, relPath, readOnly, projectPath, placement = null) {
        const request = ++openGeneration;
        if (!(await confirmDiscardIfDirty()) || request !== openGeneration) return;
        close();
        const generation = openGeneration;
        const host = placement && placement.host && placement.host.isConnected ? placement.host : null;
        if (host) {
            buildInPlaceShell(host, rootId, relPath, projectPath, placement.onFiles);
            watchTerminal(placement.stillCurrent);
        }
        else buildShell(rootId, relPath, projectPath);
        try {
            const result = await window.API.readConfigFile(rootId, relPath, projectPath);
            if (generation !== openGeneration) return;
            activeFile = {
                root: rootId,
                path: relPath,
                projectPath,
                isExecutable: result.is_executable,
                isSensitive: result.is_sensitive,
                readOnly: readOnly || result.read_only,
                revealed: !result.is_sensitive,
                originalContent: result.content,
                dirty: false,
                mode: 'edit',
                cmEditor: null,
            };
            renderBody();
        } catch (err) {
            if (generation !== openGeneration) return;
            const body = document.getElementById('config-editor-modal-body');
            if (body) body.innerHTML = `<div class="config-editor-error">failed to open: ${esc(err.message || err)}</div>`;
        }
    }

    async function openView(title, subtitle, mount, placement = null) {
        const request = ++openGeneration;
        if (!(await confirmDiscardIfDirty()) || request !== openGeneration) return;
        close();
        const host = placement && placement.host && placement.host.isConnected ? placement.host : null;
        if (host) {
            buildInPlaceShell(host, '', title, null, placement.onFiles, subtitle);
            watchTerminal(placement.stillCurrent);
        } else buildShell('', title, null, subtitle);
        const body = document.getElementById('config-editor-modal-body');
        if (!body) return;
        body.replaceChildren();
        const cleanup = mount(body);
        viewCleanup = typeof cleanup === 'function' ? cleanup : null;
    }

    function buildShell(rootId, relPath, projectPath, subtitle) {
        const stacked = window.ModalStack.depth() > 0;
        const backBtn = stacked
            ? '<button type="button" class="config-editor-modal-back" id="config-editor-modal-back" ' +
              'aria-label="Back to files">' +
              '<span aria-hidden="true">&larr;</span> files</button>'
            : '';

        overlayEl = document.createElement('div');
        overlayEl.className = 'modal-overlay config-editor-modal-overlay';
        overlayEl.setAttribute('data-modal', 'config-editor');
        overlayEl.innerHTML = contentHtml(backBtn, rootId, relPath, projectPath, 'role="dialog" aria-modal="true"', subtitle);
        document.body.appendChild(overlayEl);
        window.ModalStack.push(overlayEl, { onEscape: () => closeGuarded() });

        overlayEl.querySelector('#config-editor-modal-close').addEventListener('click', () => closeGuarded());
        if (stacked) {
            overlayEl.querySelector('#config-editor-modal-back')
                .addEventListener('click', () => closeGuarded());
        }
        overlayEl.addEventListener('click', (e) => { if (e.target === overlayEl) closeGuarded(); });

        setTimeout(() => {
            const closeBtn = overlayEl && overlayEl.querySelector('#config-editor-modal-close');
            try { if (closeBtn) closeBtn.focus(); } catch (_) {  }
        }, 50);
    }

    function contentHtml(leadHtml, rootId, relPath, projectPath, dialogAttrs, subtitle) {
        return (
            `<div class="config-editor-modal-content" ${dialogAttrs} aria-labelledby="config-editor-modal-title">` +
            '  <div class="modal-header config-editor-modal-header">' +
            `    <div>${leadHtml}<span id="config-editor-modal-title" class="config-editor-modal-title">${esc(relPath)}</span>` +
            `    <div class="config-editor-modal-subtitle">${typeof subtitle === 'string' ? esc(subtitle) : `${esc(rootId)} root${projectPath ? ` · ${esc(projectPath)}` : ''}`}</div></div>` +
            '    <button type="button" class="modal-close" id="config-editor-modal-close" aria-label="Close editor">&times;</button>' +
            '  </div>' +
            '  <div class="modal-body config-editor-modal-body" id="config-editor-modal-body"><div class="config-editor-loading">loading...</div></div>' +
            '  <div class="modal-footer config-editor-modal-footer" id="config-editor-modal-footer" hidden></div>' +
            '</div>'
        );
    }

    function buildInPlaceShell(host, rootId, relPath, projectPath, onFiles, subtitle) {
        const t = (key) => (window.CloudeI18n && typeof window.CloudeI18n.t === 'function'
            ? window.CloudeI18n.t(key) : key);
        const filesBtn = typeof onFiles === 'function'
            ? '<button type="button" class="config-editor-modal-back" id="config-editor-modal-back" ' +
              `aria-label="${esc(t('files.editor.files_label'))}" title="${esc(t('files.editor.files_label'))}">` +
              `<span aria-hidden="true">&larr;</span> ${esc(t('files.editor.files'))}</button>`
            : '';
        inPlace = true;
        overlayEl = document.createElement('div');
        overlayEl.className = 'config-editor-inplace';
        overlayEl.setAttribute('data-modal', 'config-editor');
        overlayEl.innerHTML = contentHtml(filesBtn, rootId, relPath, projectPath, 'role="dialog"', subtitle);
        host.appendChild(overlayEl);
        overlayEl.addEventListener('keydown', (e) => {
            if (e.key !== 'Escape') return;
            e.preventDefault();
            e.stopPropagation();
            closeGuarded();
        });
        overlayEl.querySelector('#config-editor-modal-close').addEventListener('click', () => closeGuarded());
        if (filesBtn) {
            overlayEl.querySelector('#config-editor-modal-back').addEventListener('click', () => onFiles());
        }
        setTimeout(() => {
            const closeBtn = overlayEl && overlayEl.querySelector('#config-editor-modal-close');
            try { if (closeBtn) closeBtn.focus(); } catch (_) {  }
        }, 50);
    }

    function watchTerminal(stillCurrent) {
        if (typeof stillCurrent !== 'function') return;
        const check = () => { if (overlayEl && inPlace && !stillCurrent()) closeGuarded(); };
        window.addEventListener('cloude:terminal-connection', check);
        stopWatching = () => window.removeEventListener('cloude:terminal-connection', check);
    }

    function renderBody() {
        const f = activeFile;
        const body = document.getElementById('config-editor-modal-body');
        const footer = document.getElementById('config-editor-modal-footer');
        if (!body || !footer) return;

        const execNote = f.isExecutable
            ? '<div class="config-editor-exec-warning">this file is code claude code runs automatically. saving requires confirmation and is always backed up first.</div>'
            : '';
        const sensitiveNote = f.isSensitive
            ? '<div class="config-editor-exec-warning">this file looks like credentials, a secret, or a private key. its contents are masked until you reveal them, and saving requires confirmation.</div>'
            : '';
        const roNote = f.readOnly ? '<div class="config-editor-ro-warning">read-only - this file is under a read-only root.</div>' : '';
        const isMd = isMarkdown(f.path);
        const toggleHtml = isMd
            ? `<div class="config-editor-mode-toggle" role="tablist" aria-label="editor mode">
                 <button type="button" role="tab" id="config-editor-mode-edit" aria-selected="${f.mode === 'edit'}">edit</button>
                 <button type="button" role="tab" id="config-editor-mode-preview" aria-selected="${f.mode === 'preview'}">preview</button>
               </div>`
            : '';

        body.innerHTML = (
            `${execNote}${sensitiveNote}${roNote}${toggleHtml}` +
            '<div id="config-editor-save-error" class="config-editor-error" hidden></div>' +
            (f.isSensitive && !f.revealed ? maskHtml() : '') +
            `<div id="config-editor-cm-host" class="config-editor-cm-host oc-focus-host" data-readonly="${f.readOnly ? '1' : '0'}" ${f.isSensitive && !f.revealed ? 'hidden' : ''}></div>` +
            `<div id="config-editor-preview" class="config-editor-preview" hidden></div>`
        );

        const saveDisabled = f.readOnly || (f.isSensitive && !f.revealed);
        footer.hidden = false;
        footer.innerHTML = (
            '<span id="config-editor-dirty-flag" class="config-editor-dirty-flag"></span>' +
            '<button type="button" class="modal-btn modal-btn-secondary" id="config-editor-cancel">cancel</button>' +
            `<button type="button" class="modal-btn modal-btn-primary" id="config-editor-save" ${saveDisabled ? 'disabled' : ''}>save</button>`
        );

        wireBody(f, isMd);
    }

    function maskHtml() {
        return (
            '<div id="config-editor-sensitive-mask" class="config-editor-sensitive-mask">' +
            window.SessionStatusUI.lockIconSvg() +
            '<div class="config-editor-sensitive-mask-text">this file looks like credentials, a secret, or a private key. ' +
            'its contents are hidden by default so they do not end up on screen in a screenshot or screen-share.</div>' +
            '<button type="button" class="modal-btn modal-btn-secondary" id="config-editor-reveal">reveal contents</button>' +
            '</div>'
        );
    }

    async function revealSensitive() {
        const f = activeFile;
        if (!f) return;
        const confirmed = await window.App.showConfirmModal(
            'show credentials on screen?',
            `"${f.path}" contains credentials, a secret, or a private key.`,
            'its contents will be displayed on screen and stay visible until you close this editor. anyone who can see or record your screen will be able to read them.',
            'reveal',
            'keep hidden'
        );
        if (!confirmed || !activeFile) return;
        activeFile.revealed = true;
        const mask = document.getElementById('config-editor-sensitive-mask');
        if (mask) mask.remove();
        const host = document.getElementById('config-editor-cm-host');
        if (host) host.hidden = false;
        mountEditor(activeFile);
        const saveBtn = document.getElementById('config-editor-save');
        if (saveBtn && !activeFile.readOnly) saveBtn.disabled = false;
    }

    function mountEditor(f) {
        const host = document.getElementById('config-editor-cm-host');
        if (!host || (f.isSensitive && !f.revealed)) return;
        if (f.cmEditor) {
            try { f.cmEditor.destroy(); } catch (_) {  }
        }
        f.cmEditor = window.CodeMirrorBundle.createEditor(
            host,
            f.originalContent,
            f.path,
            f.readOnly,
            (newValue) => {
                f.dirty = newValue !== f.originalContent;
                updateDirtyFlag();
            }
        );
    }

    function wireBody(f, isMd) {
        if (!f.isSensitive || f.revealed) {
            mountEditor(f);
        } else {
            const revealBtn = document.getElementById('config-editor-reveal');
            if (revealBtn) revealBtn.addEventListener('click', () => revealSensitive());
        }

        document.getElementById('config-editor-cancel').addEventListener('click', () => closeGuarded());
        if (!f.readOnly) {
            document.getElementById('config-editor-save').addEventListener('click', () => save());
        }
        if (isMd) {
            document.getElementById('config-editor-mode-edit').addEventListener('click', () => setMode('edit'));
            document.getElementById('config-editor-mode-preview').addEventListener('click', () => setMode('preview'));
        }
        updateDirtyFlag();
    }

    function setMode(mode) {
        if (!activeFile) return;
        if (activeFile.isSensitive && !activeFile.revealed) return;
        const host = document.getElementById('config-editor-cm-host');
        activeFile.mode = mode;
        const editTab = document.getElementById('config-editor-mode-edit');
        const previewTab = document.getElementById('config-editor-mode-preview');
        const preview = document.getElementById('config-editor-preview');
        if (mode === 'preview') {
            const content = activeFile.cmEditor ? activeFile.cmEditor.getValue() : activeFile.originalContent;
            preview.innerHTML = window.MarkdownLite.render(content);
            host.hidden = true;
            preview.hidden = false;
        } else {
            host.hidden = false;
            preview.hidden = true;
        }
        editTab.setAttribute('aria-selected', String(mode === 'edit'));
        previewTab.setAttribute('aria-selected', String(mode === 'preview'));
    }

    function updateDirtyFlag() {
        const el = document.getElementById('config-editor-dirty-flag');
        if (!el || !activeFile) return;
        el.textContent = activeFile.dirty ? 'unsaved changes' : '';
    }

    async function save() {
        const f = activeFile;
        if (!f || !f.cmEditor) return;
        const errorEl = document.getElementById('config-editor-save-error');
        errorEl.hidden = true;
        const content = f.cmEditor.getValue();

        if (f.path.endsWith('.json')) {
            try {
                JSON.parse(content);
            } catch (err) {
                errorEl.hidden = false;
                errorEl.classList.remove('config-editor-success');
                errorEl.textContent = `invalid json - not saved: ${err.message}`;
                return;
            }
        }

        let acknowledgeExecutable = false;
        if (f.isExecutable) {
            const confirmed = await window.App.showConfirmModal(
                'save executable file?',
                `"${f.path}" is code claude code runs automatically.`,
                'a backup of the current version is made before saving. this cannot be undone.',
                'save',
                'cancel'
            );
            if (!confirmed) return;
            acknowledgeExecutable = true;
        }

        let acknowledgeSensitive = false;
        if (f.isSensitive) {
            const confirmed = await window.App.showConfirmModal(
                'save credentials file?',
                `"${f.path}" contains credentials, a secret, or a private key.`,
                'a backup of the current version is made before saving. this cannot be undone.',
                'save',
                'cancel'
            );
            if (!confirmed) return;
            acknowledgeSensitive = true;
        }

        try {
            const result = await window.API.writeConfigFile({
                root: f.root,
                path: f.path,
                content,
                project_path: f.projectPath,
                acknowledge_executable: acknowledgeExecutable,
                acknowledge_sensitive: acknowledgeSensitive,
            });
            f.originalContent = content;
            f.dirty = false;
            updateDirtyFlag();
            errorEl.hidden = false;
            errorEl.classList.add('config-editor-success');
            errorEl.textContent = result.backed_up ? 'saved (previous version backed up to .bak)' : 'saved';
        } catch (err) {
            errorEl.hidden = false;
            errorEl.classList.remove('config-editor-success');
            errorEl.textContent = `save failed: ${err.message || err}`;
        }
    }

    window.ConfigEditorModal = { open, openView, close, isDirty, isInPlace, confirmDiscardIfDirty };
    console.log('[ConfigEditorModal Module] Exported as window.ConfigEditorModal');
})();
