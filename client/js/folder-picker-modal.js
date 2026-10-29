
console.log('[FolderPickerModal Module] Loading...');

(function () {
    function defaultEscapeHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function open(options) {
        var esc = (options && options.escapeHtml) || defaultEscapeHtml;
        var lister = options && typeof options.list === 'function' ? options.list : null;
        var browseDirectory = (p) => (lister ? lister(p) : window.API.browseDirectory(p));
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = 'modal-overlay text-prompt-modal';

            const SessionStatusUI = window.SessionStatusUI || {};
            const folderGlyph = typeof SessionStatusUI.folderIconSvg === 'function'
                ? SessionStatusUI.folderIconSvg() : '';
            const homeGlyph = typeof SessionStatusUI.homeIconSvg === 'function'
                ? SessionStatusUI.homeIconSvg() : '';
            const upGlyph = typeof SessionStatusUI.chevronUpIconSvg === 'function'
                ? SessionStatusUI.chevronUpIconSvg() : '';

            overlay.innerHTML = `
                <div class="modal-content folder-picker-modal">
                    <div class="text-prompt-modal__head">
                        <span class="text-prompt-modal__verb">&raquo; ${esc((options && typeof options.title === 'string') ? options.title : 'select a folder')}</span>
                    </div>
                    <div class="modal-body">
                        <div class="folder-picker-pathbar">
                            <button type="button" class="folder-picker-navbtn" id="folder-picker-up"
                                    title="go to parent directory" aria-label="go to parent directory" disabled>${upGlyph}</button>
                            <button type="button" class="folder-picker-navbtn" id="folder-picker-home"
                                    aria-label="go to home directory">${homeGlyph}</button>
                            <input type="text" class="folder-picker-path modal-input" id="folder-picker-path"
                                   spellcheck="false" autocomplete="off" autocapitalize="off" autocorrect="off"
                                   aria-label="directory path"
                                   placeholder="${lister ? 'type a path then Enter' : "type a path then Enter - created if it doesn't exist"}">
                        </div>
                        <div class="folder-picker-status" id="folder-picker-status" role="status" aria-live="polite"></div>
                        <div class="folder-picker-list" id="folder-picker-list" tabindex="-1">
                            <div class="folder-picker-empty">loading...</div>
                        </div>
                        <div class="modal-description">
                            click a folder to enter it, or type letters to jump · ↑/↓ to move · Enter opens the highlighted folder.
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="modal-btn modal-btn-secondary" id="folder-picker-cancel">cancel</button>
                        <button class="modal-btn modal-btn-confirm" id="folder-picker-confirm">open here</button>
                    </div>
                </div>
            `;

            document.body.appendChild(overlay);

            const pathInput = overlay.querySelector('#folder-picker-path');
            const statusEl = overlay.querySelector('#folder-picker-status');
            const listEl = overlay.querySelector('#folder-picker-list');
            const upBtn = overlay.querySelector('#folder-picker-up');
            const homeBtn = overlay.querySelector('#folder-picker-home');
            const confirmBtn = overlay.querySelector('#folder-picker-confirm');
            const cancelBtn = overlay.querySelector('#folder-picker-cancel');

            let currentPath = null;
            let currentParent = null;
            let entries = [];
            let activeIndex = -1;
            let typeBuffer = '';
            let typeTimer = null;

            const close = (value) => {
                document.removeEventListener('keydown', onKeyDown, true);
                if (typeTimer) clearTimeout(typeTimer);
                document.body.removeChild(overlay);
                resolve(value);
            };

            const clearStatus = () => {
                statusEl.textContent = '';
                statusEl.className = 'folder-picker-status';
            };
            const showStatus = (msg, kind) => {
                statusEl.textContent = msg;
                statusEl.className = `folder-picker-status folder-picker-status--${kind || 'info'}`;
            };

            const setActive = (idx, { scroll = true } = {}) => {
                const els = listEl.querySelectorAll('.folder-picker-item');
                if (!els.length) { activeIndex = -1; return; }
                idx = Math.max(0, Math.min(idx, els.length - 1));
                els.forEach((el, i) => el.classList.toggle('folder-picker-item-active', i === idx));
                activeIndex = idx;
                if (scroll) els[idx].scrollIntoView({ block: 'nearest' });
            };

            const navigate = (data) => {
                currentPath = data.path;
                currentParent = data.parent;
                entries = Array.isArray(data.entries) ? data.entries : [];
                pathInput.value = data.path || '';
                upBtn.disabled = !data.parent;
                activeIndex = -1;
                typeBuffer = '';
                if (typeTimer) { clearTimeout(typeTimer); typeTimer = null; }

                if (data.truncated && options && options.truncatedText) showStatus(options.truncatedText, 'info');

                if (!entries.length) {
                    listEl.innerHTML = '<div class="folder-picker-empty">no subfolders here</div>';
                    return;
                }

                listEl.innerHTML = entries.map((entry, i) => `
                    <div class="folder-picker-item config-editor-toggle" role="option" data-index="${i}" data-path="${esc(entry.path)}">
                        <span class="folder-picker-icon">${folderGlyph}</span>
                        <span class="folder-picker-name config-editor-node-name">${esc(entry.name)}</span>
                    </div>
                `).join('');

                listEl.querySelectorAll('.folder-picker-item').forEach(item => {
                    item.addEventListener('click', () => loadPath(item.dataset.path));
                    item.addEventListener('mousemove', () => {
                        const idx = parseInt(item.dataset.index, 10);
                        if (idx !== activeIndex) setActive(idx, { scroll: false });
                    });
                });
            };

            const loadPath = async (targetPath) => {
                listEl.innerHTML = '<div class="folder-picker-empty">loading...</div>';
                clearStatus();
                try {
                    navigate(await browseDirectory(targetPath));
                } catch (error) {
                    console.error('Launchpad: Folder browse failed:', error);
                    listEl.innerHTML = `<div class="folder-picker-empty">error: ${esc(error.message || String(error))}</div>`;
                }
            };

            const submitPath = async () => {
                const value = pathInput.value.trim();
                if (!value) return;
                clearStatus();
                try {
                    navigate(await browseDirectory(value));
                } catch (error) {
                    if (error && error.status === 404 && !lister) {
                        try {
                            const data = await window.API.makeDirectory(value);
                            navigate(data);
                            showStatus(`created ${data.path}`, 'success');
                        } catch (mkErr) {
                            showStatus(`could not create: ${mkErr.message || mkErr}`, 'error');
                        }
                    } else {
                        showStatus(error.message || String(error), 'error');
                    }
                }
            };

            pathInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    submitPath();
                }
            });

            const onKeyDown = (e) => {
                if (e.key === 'Escape') {
                    e.preventDefault();
                    close(null);
                    return;
                }

                if (document.activeElement === pathInput) return;

                const ae = document.activeElement;
                const onButton = !!ae && ae.tagName === 'BUTTON';
                if (onButton && (e.key === 'Enter' || e.key === ' ') && !typeBuffer) return;

                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    setActive(activeIndex < 0 ? 0 : activeIndex + 1);
                    return;
                }
                if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    setActive(activeIndex < 0 ? entries.length - 1 : activeIndex - 1);
                    return;
                }
                if (e.key === 'Enter') {
                    e.preventDefault();
                    if (activeIndex >= 0 && entries[activeIndex]) {
                        loadPath(entries[activeIndex].path);
                    } else if (currentPath) {
                        close(currentPath);
                    }
                    return;
                }

                if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
                    e.preventDefault();
                    if (onButton) listEl.focus();
                    typeBuffer += e.key.toLowerCase();
                    if (typeTimer) clearTimeout(typeTimer);
                    typeTimer = setTimeout(() => { typeBuffer = ''; }, 800);
                    const matchIdx = entries.findIndex(
                        en => en.name.toLowerCase().startsWith(typeBuffer)
                    );
                    if (matchIdx >= 0) setActive(matchIdx);
                }
            };
            document.addEventListener('keydown', onKeyDown, true);

            upBtn.addEventListener('click', () => {
                if (currentParent) loadPath(currentParent);
            });

            homeBtn.addEventListener('click', () => loadPath('~'));

            confirmBtn.addEventListener('click', () => {
                if (currentPath) close(currentPath);
            });

            cancelBtn.addEventListener('click', () => close(null));

            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) close(null);
            });

            loadPath(null);

            setTimeout(() => listEl.focus(), 100);
        });
    }

    window.FolderPickerModal = { open: open };
})();
