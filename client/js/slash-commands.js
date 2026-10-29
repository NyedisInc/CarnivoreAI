
console.log('[SlashCommands Module] Loading...');

class SlashCommandsModal {
    constructor() {
        this.commonCommands = [];
        this.commonCommandDetails = [];
        this.commonDefaulted = false;
        this.groups = [];
        this.commandIndex = new Map();
        this.modal = null;
        this.loaded = false;
        this.isOpen = false;
        this.onCommandSelect = null;
        this.projectPath = null;
        this._initToken = 0;

        this.filter = new window.SlashCommandFilter();
    }

    async init(onCommandSelect, projectPath = null) {
        console.log('[SlashCommands] Initializing (NOT creating modal yet)');
        this.onCommandSelect = onCommandSelect;
        this.projectPath = projectPath || null;
        const token = ++this._initToken;

        const [, groups] = await Promise.all([
            this._loadCommonCommands(),
            this._fetchGroups(projectPath || null),
        ]);
        if (token !== this._initToken) return;
        this._setGroups(groups);
        if (this.modal) this._refreshList();

        this.loaded = true;
        console.log('[SlashCommands] Initialization complete (modal will be created on demand)');
    }

    async _loadCommonCommands() {
        try {
            const response = await window.API.getCommonCommands();
            this.commonCommands = response.commands || [];
            this.commonCommandDetails = Array.isArray(response.command_details)
                ? response.command_details
                : this.commonCommands.map(c => ({ command: c, description: '' }));
            this.commonDefaulted = response.defaulted === true;
            console.log('[SlashCommands] Fetched', this.commonCommands.length, 'common commands');
        } catch (error) {
            console.error('[SlashCommands] Failed to fetch common commands:', error);
            this.commonCommands = [
                '/agents', '/clear', '/compact', '/context',
                '/hooks', '/mcp', '/resume', '/rewind', '/usage'
            ];
            this.commonCommandDetails = this.commonCommands.map(
                c => ({ command: c, description: '' })
            );
            this.commonDefaulted = true;
        }
    }

    _applyFavorites(payload) {
        this.commonCommands = payload.commands || [];
        this.commonCommandDetails = Array.isArray(payload.command_details)
            ? payload.command_details
            : [];
        this.commonDefaulted = payload.defaulted === true;
        if (window.CloudeWeb && window.CloudeWeb.setSlashFavorites) {
            window.CloudeWeb.setSlashFavorites(payload);
        }
        window.SlashFavorites.repaint(this.modal, {
            details: this.commonCommandDetails,
            onChange: (p) => this._applyFavorites(p),
        });
    }

    _mountFavorites() {
        const web = window.CloudeWeb;
        if (!web || !web.mountSlashFavorites) {
            console.error('[SlashCommands] compiled bundle missing; favorites row not mounted');
            return;
        }
        web.setSlashFavorites({
            command_details: this.commonCommandDetails,
            defaulted: this.commonDefaulted,
        });
        web.mountSlashFavorites({
            onSelect: (command) => this.selectCommand(command),
            onChange: (payload) => this._applyFavorites(payload),
            describe: (cmd) => {
                const info = this.commandIndex.get(cmd);
                return (info && info.description) || '';
            },
        });
    }

    async _fetchGroups(projectPath) {
        try {
            const response = await window.API.getSlashCommands(projectPath);
            const groups = Array.isArray(response.groups) ? response.groups : [];
            console.log('[SlashCommands] Fetched', groups.length, 'command groups');
            return groups;
        } catch (error) {
            console.error('[SlashCommands] Failed to fetch slash command groups:', error);
            return [];
        }
    }

    _setGroups(groups) {
        this.groups = groups;
        this.commandIndex = new Map();
        for (const group of this.groups) {
            for (const cmd of (group.commands || [])) {
                this.commandIndex.set(cmd.command, cmd);
            }
        }
    }

    _refreshList() {
        const list = this.modal.querySelector('#all-commands-list');
        if (!list) return;
        list.innerHTML = this.renderAllCommands();
        this._wireListRows();
        this.filter.index(this.modal);
        const filterInput = this.modal.querySelector('#slash-command-filter');
        this.filter.apply(filterInput ? filterInput.value : '');
    }


    createModal() {
        console.log('[SlashCommands] createModal() called');

        const modalHTML = `
            <div id="slash-commands-modal" class="modal" style="display: none;">
                <div class="modal-overlay">
                    <div class="modal-content slash-commands-modal-content popup-focus">
                        <div class="modal-header">
                            <h2>/ Slash Commands</h2>
                            <button class="modal-close" aria-label="Close modal">&times;</button>
                        </div>
                        <div class="modal-body">
                            <div class="common-commands-section">
                                <!-- Owned by the compiled favorites panel;
                                     no markup goes inside it. -->
                                <div class="common-commands-grid" id="common-commands-grid"></div>
                            </div>
                            <div class="all-commands-section">
                                <h3>all commands</h3>
                                <input
                                    type="text"
                                    id="slash-command-filter"
                                    class="command-filter-input"
                                    placeholder="type to filter..."
                                    autocomplete="off"
                                    aria-label="Filter commands"
                                />
                                <div class="all-commands-list" id="all-commands-list">
                                    ${this.renderAllCommands()}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        const existingModal = document.getElementById('slash-commands-modal');
        if (existingModal) {
            console.log('[SlashCommands] Removing existing modal');
            existingModal.remove();
        }

        document.body.insertAdjacentHTML('beforeend', modalHTML);
        this.modal = document.getElementById('slash-commands-modal');
        console.log('[SlashCommands] Modal added to DOM:', this.modal ? 'success' : 'FAILED');
        this.filter.index(this.modal);
        if (this.modal) this._mountFavorites();
    }

    renderAllCommands() {
        if (!this.groups || this.groups.length === 0) {
            return '<div style="color: var(--oc-text-muted); padding: 12px; text-align: center;">no commands available</div>';
        }

        const starred = window.SlashFavorites.favoriteSet(this.commonCommandDetails);
        return this.groups.map(group => {
            const commands = group.commands || [];
            if (commands.length === 0) return '';
            return `
                <div class="command-category" data-group-id="${this._escapeHtml(group.id)}">
                    <h4 class="category-title">${this._escapeHtml(group.label)}</h4>
                    ${commands.map(cmd => this._renderCommandItem(cmd, starred.has(cmd.command))).join('')}
                </div>
            `;
        }).join('');
    }

    _renderCommandItem(cmd, starred) {
        const display = cmd.args ? `${cmd.command} ${cmd.args}` : cmd.command;
        const full = cmd.description || '';
        const short = window.CommandDescription.shorten(full);
        const more = window.CommandDescription.isShortened(full)
            ? '<button type="button" class="command-more" aria-expanded="false">more</button>'
            : '';
        return `
            <div class="command-item" data-command="${this._escapeHtml(cmd.command)}" data-description="${this._escapeHtml(full)}">
                ${window.SlashFavorites.starButton(cmd.command, !!starred)}
                <span class="command-name">${this._escapeHtml(display)}</span>
                <span class="command-description">${this._escapeHtml(short)}</span>
                ${more}
            </div>
        `;
    }

    _toggleFullDescription(btn) {
        const item = btn.closest('.command-item');
        if (!item) return;
        const descEl = item.querySelector('.command-description');
        if (!descEl) return;
        const full = item.dataset.description || '';
        const expanded = btn.getAttribute('aria-expanded') === 'true';
        descEl.textContent = expanded ? window.CommandDescription.shorten(full) : full;
        btn.setAttribute('aria-expanded', String(!expanded));
        btn.textContent = expanded ? 'more' : 'less';
    }

    _escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    _wireListRows() {
        const list = this.modal.querySelector('#all-commands-list') || this.modal;
        const commandItems = list.querySelectorAll('.command-item');
        commandItems.forEach(item => {
            item.addEventListener('click', () => {
                const command = item.dataset.command;
                this.selectCommand(command);
            });
        });

        window.SlashFavorites.wire(list, (payload) => this._applyFavorites(payload));

        list.querySelectorAll('.command-more').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this._toggleFullDescription(btn);
            });
        });
    }

    attachEventListeners() {
        if (!this.modal) return;

        const closeBtn = this.modal.querySelector('.modal-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => this.close());
        }

        const overlay = this.modal.querySelector('.modal-overlay');
        if (overlay) {
            window.DismissGuard.onOverlayDismiss(overlay, () => this.close());
        }


        this._wireListRows();

        const filterInput = this.modal.querySelector('#slash-command-filter');
        if (filterInput) {
            filterInput.addEventListener('input', () => {
                this.filter.apply(filterInput.value);
            });
            filterInput.addEventListener('keydown', (e) => {
                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    this.filter.moveActive(1);
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    this.filter.moveActive(-1);
                } else if (e.key === 'Enter') {
                    e.preventDefault();
                    const target = this.filter.getEnterTarget();
                    if (target) this.selectCommand(target.command);
                }
            });
        }

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isOpen) {
                this.close();
            }
        });
    }

    open() {
        console.log('[SlashCommands] open() called');
        this._ownership = window.TerminalInputOwnership
            ? window.TerminalInputOwnership.claim('command') : null;

        if (!this.modal) {
            console.log('[SlashCommands] Modal does not exist yet, creating now...');
            this.createModal();
            this.attachEventListeners();
            console.log('[SlashCommands] Modal created and event listeners attached');
        }

        if (!this.modal) {
            console.error('[SlashCommands] Failed to create modal!');
            return;
        }

        const filterInput = this.modal.querySelector('#slash-command-filter');
        if (filterInput) filterInput.value = '';
        this.filter.apply('');

        console.log('[SlashCommands] Adding .active class to show modal');
        this.modal.classList.add('active');
        this.isOpen = true;
    }

    close() {
        console.log('[SlashCommands] close() called');
        if (!this.modal) {
            console.log('[SlashCommands] No modal to close');
            return;
        }
        console.log('[SlashCommands] Removing .active class to hide modal');
        this.modal.classList.remove('active');
        this.isOpen = false;
    }

    selectCommand(command) {
        if (this.onCommandSelect) {
            this.onCommandSelect(command, this._ownership);
        }
        this.close();

        setTimeout(() => {
            const terminal = document.querySelector('.xterm-helper-textarea');
            if (terminal) {
                terminal.focus();
            }
        }, 100);
    }
}

window.SlashCommandsModal = new SlashCommandsModal();
console.log('[SlashCommands Module] Exported as window.SlashCommandsModal');
