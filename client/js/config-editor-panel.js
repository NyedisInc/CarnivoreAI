/* at the gesture the page terminal */

console.log('[ConfigEditorPanel Module] Loading...');

function configEditorT(key, params) {
    const i18n = window.CloudeI18n;
    return i18n && typeof i18n.t === 'function' ? i18n.t(key, params) : key;
}

class ConfigEditorPanelController {
    constructor() {
        this.overlay = null;
        this._releaseTheme = null;
        this.panel = null;
        this.closeBtn = null;
        this.treeEl = null;
        this._header = null;
        this._git = null;

        this.isOpen = false;
        this._wired = false;
        this._context = null;
        this._target = null;
        this._treeGeneration = 0;
        this._treeLoading = null;
        this._best = null;
        this._scope = null;
        this._openGeneration = 0;
        this._directory = null;
        this._mode = 'drawer';
        this._cellClose = null;
    }

    get mode() {
        return this._mode;
    }

    get directory() {
        return this._directory;
    }

    _dock() {
        const web = window.CloudeWeb;
        return web && web.rightDrawer && typeof web.rightDrawer.open === 'function' ? web.rightDrawer : null;
    }

    _announce() {
        if (this._git) {
            const session = this._target && this._target._currentSession;
            const sessionId = this.isOpen && !this._directory && session ? session.session_id : null;
            this._git.setTarget(sessionId ? { sessionId, workdir: this._currentProjectPath() || '' } : null);
        }
        if (typeof window.dispatchEvent !== 'function' || typeof CustomEvent !== 'function') return;
        window.dispatchEvent(new CustomEvent('cloude:file-drawer', {
            detail: { open: this.isOpen, mode: this._mode, directory: this._directory },
        }));
    }

    _gridUp() {
        const host = window.TerminalGridHost;
        return !!(host && typeof host.isMounted === 'function' && host.isMounted());
    }

    _paintHeaderMode() {
        if (this._header && typeof this._header.setComponentShown === 'function') {
            this._header.setComponentShown(this._mode === 'drawer' && this._gridUp());
        }
    }

    _projectContext() {
        return this._context || window.ConfigEditorRoots.resolveProjectContext(window.TerminalController);
    }

    _currentProjectPath() {
        return this._projectContext().path;
    }

    _prefs() {
        return this._header ? this._header.prefs() : { hideDot: false, hideIgnored: false };
    }

    _query() {
        return this._header ? String(this._header.query() || '').trim() : '';
    }

    _wire() {
        if (this._wired) return;
        this.overlay = document.getElementById('config-editor-overlay');
        this.panel = this.overlay ? this.overlay.querySelector('.config-editor-picker-content') : null;
        this.treeEl = document.getElementById('config-editor-tree');
        if (!this.overlay || !this.panel) return;

        const web = window.CloudeWeb;
        if (web && web.fileDrawer && typeof web.fileDrawer.mountHeader === 'function') {
            this._header = web.fileDrawer.mountHeader({
                onQuery: () => { this._treeLoading = this._loadTree(); return this._treeLoading; },
                onSubmit: () => this._enterBestMatch(),
                onScopeUp: () => this._scopeUp(),
                onScopeClear: () => this._setScope(null),
                onPrefs: () => this._loadTree(),
                onRefresh: () => this.refresh(),
                onCollapseAll: () => this.collapseAll(),
                onNewFile: () => this.createFile(),
                onClose: () => this.close(),
                onComponent: () => this.openAsComponent(),
            });
        } else {
            console.error('ConfigEditorPanel: window.CloudeWeb.fileDrawer is missing; '
                + 'the drawer opens with no header controls.');
        }
        if (web && web.fileDrawer && typeof web.fileDrawer.mountGit === 'function') {
            this._git = web.fileDrawer.mountGit({
                tree: this.treeEl,
                onTab: (tab) => { this.panel.dataset.fileTab = tab; },
                onOpenDiff: (path, mountView) => this._openDiff(path, mountView),
                onOpenFile: (path, repoRoot, workdirPath) => this._openFile('workdir', path, false, repoRoot, workdirPath),
            });
        }
        this.closeBtn = document.getElementById('config-editor-close');

        this.overlay.addEventListener('click', (e) => {
            if (e.target === this.overlay) this.close();
        });
        this.overlay.addEventListener('keydown', (e) => {
            if (e.key !== 'Escape' || this._mode !== 'drawer' || !this._docked()) return;
            e.stopPropagation();
            e.preventDefault();
            this._escape();
        });
        this._wired = true;
    }

    async open(triggerEl = null, controller = window.TerminalController, directory = null) {
        this._wire();
        if (!this.overlay) return;
        const request = ++this._openGeneration;
        const context = window.ConfigEditorRoots.resolveProjectContext(controller);
        const modal = window.ConfigEditorModal;
        const stacked = modal && !modal.isInPlace();
        if (stacked && modal.isDirty() && !(await modal.confirmDiscardIfDirty())) return;
        if (request !== this._openGeneration) return;
        if (stacked) modal.close();
        this._context = context;
        this._target = controller || null;
        this._directory = ['skills', 'plugins'].includes(directory) ? directory : null;
        this._triggerEl = triggerEl || null;
        if (this._mode === 'cell') {
            this._scopeThemeTo(controller);
            this._announce();
            await this._loadTree();
            return;
        }
        const wasOpen = this.isOpen;
        this.isOpen = true;
        this.overlay.hidden = false;
        this._scopeThemeTo(controller);
        const dock = this._dock();
        if (dock) {
            dock.register('files', {
                root: this.overlay, box: this.panel,
                close: () => { this.close(); },
                onDockChange: (docked) => this._syncModal(docked),
            });
            dock.open('files');
        }
        if (!wasOpen && !this._docked()) window.ModalStack.push(this.overlay, { onEscape: () => this._escape() });
        if (this._triggerEl) this._triggerEl.setAttribute('aria-expanded', 'true');
        this._paintHeaderMode();
        this._announce();
        if (this.closeBtn) {
            try { this.closeBtn.focus(); } catch (_) {  }
        }
        await this._loadTree();
    }

    _docked() {
        const dock = this._dock();
        return !!(dock && typeof dock.docked === 'function' && dock.docked());
    }

    _syncModal(docked) {
        if (!this.isOpen || this._mode !== 'drawer') return;
        if (!docked) {
            window.ModalStack.push(this.overlay, { onEscape: () => this._escape() });
            return;
        }
        window.ModalStack.pop(this.overlay);
        //  hidden 
        this.overlay.style.zIndex = '';
        this.overlay.removeAttribute('inert');
        this.overlay.removeAttribute('aria-hidden');
        this.overlay.classList.remove('modal-stack--covered');
    }

    async retarget(target) {
        if (!this.isOpen || !target) return;
        const before = this._currentProjectPath();
        const themeBefore = this._target && this._target._currentSession
            ? this._target._currentSession.pinned_theme : null;
        this._context = window.ConfigEditorRoots.resolveProjectContext(target);
        this._target = target;
        const themeNow = target._currentSession ? target._currentSession.pinned_theme : null;
        if (themeNow !== themeBefore) this._scopeThemeTo(target);
        this._announce();
        if (this._context.path !== before) await this._loadTree();
    }

    async attach(cellEl, target, onClose) {
        this._wire();
        if (!this.panel || !cellEl) return;
        if (this.isOpen && this._mode === 'drawer') await this.close();
        this._mode = 'cell';
        this._cellClose = typeof onClose === 'function' ? onClose : null;
        this.overlay.hidden = true;
        cellEl.appendChild(this.panel);
        this.isOpen = true;
        this._context = window.ConfigEditorRoots.resolveProjectContext(target);
        this._target = target || null;
        this._directory = null;
        this._scopeThemeTo(target);
        this._paintHeaderMode();
        this._announce();
        await this._loadTree();
    }

    detach(cellEl) {
        if (this._mode !== 'cell' || !this.panel || this.panel.parentElement !== cellEl) return;
        this.overlay.appendChild(this.panel);
        this._mode = 'drawer';
        this._cellClose = null;
        this.isOpen = false;
        this._treeGeneration += 1;
        this._scopeThemeTo(null);
        this._paintHeaderMode();
        this._announce();
    }

    async openAsComponent() {
        const web = window.CloudeWeb;
        const files = web && web.fileDrawer;
        if (!files || typeof files.showCell !== 'function') return;
        if (this.isOpen && this._mode === 'drawer') await this.close();
        files.showCell();
    }

    _scopeThemeTo(controller) {
        if (this._releaseTheme) {
            this._releaseTheme();
            this._releaseTheme = null;
        }
        if (!controller || !this.panel) return;
        const themes = window.Themes;
        const nav = window.ThemeNavigation;
        if (!themes || typeof themes.applyScopeTo !== 'function') return;
        const pin = (nav && typeof nav.resolvePinnedTheme === 'function')
            ? nav.resolvePinnedTheme(controller._currentSession)
            : null;
        this._releaseTheme = themes.applyScopeTo(this.panel, { pinnedTheme: pin });
    }

    async _escape() {
        if (this._header && this._header.escape()) return;
        await this.close();
    }

    async close() {
        if (!this.overlay || !this.isOpen) return;
        if (this._mode === 'cell') {
            if (this._cellClose) this._cellClose();
            return;
        }
        const modal = window.ConfigEditorModal;
        if (modal && !modal.isInPlace()) {
            if (modal.isDirty() && !(await modal.confirmDiscardIfDirty())) return;
            modal.close();
        }
        this.isOpen = false;
        this._treeGeneration += 1;
        this._openGeneration += 1;
        window.ModalStack.pop(this.overlay);
        this.overlay.hidden = true;
        this._scopeThemeTo(null);
        const dock = this._dock();
        if (dock) dock.close('files');
        this._announce();
        if (this._triggerEl) {
            this._triggerEl.setAttribute('aria-expanded', 'false');
            if (this._triggerEl.isConnected) this._triggerEl.focus();
        }
    }

    async refresh() {
        await this._loadTree();
    }

    collapseAll() {
        if (!this.treeEl) return;
        const keys = [];
        this.treeEl.querySelectorAll('.config-editor-toggle:not(.config-editor-toggle--root)').forEach((toggle) => {
            if (toggle.dataset.key) keys.push(toggle.dataset.key);
            this._setExpanded(toggle, false);
        });
        window.ConfigEditorTreeState.collapseAllDirs(keys);
    }

    _setExpanded(toggle, expanded) {
        toggle.setAttribute('aria-expanded', String(expanded));
        const list = toggle.nextElementSibling;
        if (list) list.hidden = !expanded;
    }

    _editorHost() {
        const host = this._target && this._target.host;
        return host && host.isConnected ? host : null;
    }

    _sessionRef() {
        const current = this._target && this._target._currentSession;
        if (!current) return null;
        const nested = current.session || current;
        return {
            sessionId: current.session_id || nested.id || null,
            sessionRowId: typeof current.session_row_id === 'number' ? current.session_row_id : null,
            tmuxName: current.tmux_session || nested.tmux_session || null,
        };
    }

    async _openAsRow(request) {
        const web = window.CloudeWeb;
        const opener = web && web.fileDrawer && web.fileDrawer.openFile;
        const ref = this._sessionRef();
        if (typeof opener !== 'function' || !ref) return false;
        const result = await opener(Object.assign({}, request, ref));
        if (result === 'unavailable') return false;
        if (result === 'opened' && this._mode !== 'cell') await this.close();
        return true;
    }

    async _openFile(rootId, relPath, readOnly, projectPath, workdirPath) {
        const rowPath = workdirPath === undefined ? relPath : workdirPath;
        if (rowPath && await this._openAsRow({ root: rootId, path: rowPath, kind: 'file' })) return;
        const placement = await this._placeInTerminal();
        window.ConfigEditorModal.open(rootId, relPath, readOnly, projectPath, placement);
    }

    async _openDiff(path, mountView) {
        if (await this._openAsRow({ root: 'workdir', path, kind: 'diff' })) return;
        const placement = await this._placeInTerminal();
        window.ConfigEditorModal.openView(path, configEditorT('git.diff.subtitle'), mountView, placement);
    }

    async _placeInTerminal() {
        const host = this._editorHost();
        if (!host) return null;
        const target = this._target;
        const directory = this._directory;
        const folder = this._currentProjectPath();
        if (this._mode !== 'cell') await this.close();
        return {
            host,
            onFiles: () => this.open(null, target, directory),
            stillCurrent: () => this._hostShows(host, folder),
        };
    }

    _hostShows(host, folder) {
        if (!host.isConnected) return false;
        if (host.id !== 'terminal-container') return true;
        const now = window.ConfigEditorRoots.resolveProjectContext(window.TerminalController);
        return now.path === folder;
    }

    async createFile() {
        const projectPath = this._currentProjectPath();
        const roots = window.ConfigEditorRoots.visibleRoots(!!projectPath)
            .map(r => ({ id: r.id, label: r.label }));
        if (!roots.length) return;
        const created = await window.ConfigEditorNewFile.open(roots, projectPath);
        if (!created) return;
        await this._loadTree();
        await this._openFile(created.root, created.path, false, created.root === 'user' ? null : projectPath);
    }


    async _loadTree() {
        if (!this.treeEl) return;
        const generation = ++this._treeGeneration;
        const query = this._query();
        this._best = null;
        this.treeEl.innerHTML = '';
        this.treeEl.appendChild(window.ConfigEditorRows.noticeLi(
            query ? configEditorT('files.drawer.searching') : 'loading...'));
        const context = this._projectContext();
        const prefs = this._prefs();
        const list = document.createElement('ul');
        list.className = 'config-editor-list config-editor-list--roots';
        const statuses = [];
        let matches = 0;
        let truncated = false;

        const steps = window.ConfigEditorRoots.planRoots(context).map((step) => {
            if (step.kind === 'notice') return { step };
            const def = this._scopedDef(step.def);
            const scope = query ? this._scope : null;
            if (scope && scope.rootId !== def.id) return { step, skip: true };
            return { step, def, pending: this._fetchRoot(def, context.path, query, scope ? scope.relPath : null) };
        });
        for (const { step, def, pending, skip } of steps) {
            if (skip) continue;
            if (step.kind === 'notice') {
                list.appendChild(window.ConfigEditorRows.noticeLi(step.message));
                continue;
            }
            const loaded = await pending;
            if (generation !== this._treeGeneration) return;
            if (loaded.errorLi) {
                list.appendChild(loaded.errorLi);
                continue;
            }
            statuses.push(loaded.ignoreStatus);
            let nodes = loaded.nodes;
            let searching = false;
            if (query) {
                const found = window.ConfigEditorFilter.filterTree(
                    nodes, query, prefs, window.ConfigEditorFilter.MATCH_LIMIT - matches);
                matches += found.matches;
                truncated = truncated || found.truncated || loaded.truncated;
                if (!found.nodes.length) continue;
                nodes = this._scope ? this._directFirst(found.nodes, query) : found.nodes;
                if (!this._best) {
                    const hit = this._firstNameMatch(nodes, query);
                    if (hit) this._best = { rootId: def.id, node: hit, projectPath: def.id === 'user' ? null : context.path };
                }
                searching = true;
            }
            const rootNode = { name: def.label, rel_path: def.path || '', is_dir: true, children: nodes };
            list.appendChild(this._buildNodeEl(def.id, rootNode, 0, {
                isRoot: true,
                defaultExpanded: searching || def.defaultExpanded,
                projectPath: context.path,
                searching,
            }));
        }

        if (query && !matches) {
            list.appendChild(window.ConfigEditorRows.noticeLi(configEditorT('files.drawer.no_matches', { query })));
        } else if (truncated) {
            list.appendChild(window.ConfigEditorRows.noticeLi(
                configEditorT('files.drawer.truncated', { count: window.ConfigEditorFilter.MATCH_LIMIT })));
        }
        this.treeEl.innerHTML = '';
        this.treeEl.appendChild(list);
        if (this._header) {
            this._header.setIgnoreStatus(
                statuses.includes('ok') ? 'ok' : (statuses.length ? 'unavailable' : 'unknown'));
        }
    }

    _firstNameMatch(nodes, query) {
        const needle = String(query || '').trim().toLowerCase();
        for (const node of nodes) {
            if (node.kind === 'more') continue;
            if (String(node.name || '').toLowerCase().includes(needle)) return node;
            if (node.is_dir && node.children) {
                const inner = this._firstNameMatch(node.children, query);
                if (inner) return inner;
            }
        }
        return null;
    }

    _directFirst(nodes, query) {
        const needle = String(query || '').trim().toLowerCase();
        const direct = (n) => String(n.name || '').toLowerCase().includes(needle);
        return [...nodes.filter(direct), ...nodes.filter((n) => !direct(n))];
    }

    _setScope(scope) {
        this._scope = scope && scope.relPath ? scope : null;
        if (this._header) this._header.setScope(this._scope ? `${this._scope.relPath}/` : '');
        this._treeLoading = this._loadTree();
    }

    _scopeUp() {
        if (!this._scope) return;
        const parts = this._scope.relPath.split('/').filter(Boolean);
        parts.pop();
        this._setScope({ rootId: this._scope.rootId, relPath: parts.join('/') });
    }

    _isBest(rootId, node) {
        const best = this._best;
        return !!best && best.rootId === rootId && best.node.rel_path === node.rel_path;
    }

    async _enterBestMatch() {
        const typed = this._query();
        await this._treeLoading;
        const best = this._best;
        if (!best || !typed || typed !== this._query()) return;
        const { rootId, node, projectPath } = best;
        if (!node.is_dir) {
            this._openFile(rootId, node.rel_path, node.read_only, projectPath);
            return;
        }
        const parts = String(node.rel_path || '').split('/').filter(Boolean);
        parts.forEach((_, i) => window.ConfigEditorTreeState.setNodeCollapsed(
            `${rootId}:${parts.slice(0, i + 1).join('/')}`, false));
        this._scope = { rootId, relPath: parts.join('/') };
        this._header.setScope(`${this._scope.relPath}/`);
        this._header.clearQuery();
        await this._treeLoading;
        const key = `${rootId}:${node.rel_path}`;
        const row = [...this.treeEl.querySelectorAll('.config-editor-toggle')].find((t) => t.dataset.key === key);
        if (row && row.scrollIntoView) row.scrollIntoView({ block: 'nearest' });
    }

    _scopedDef(def) {
        const directory = this._directory;
        if (!directory) return def;
        return { ...def,
            label: `${def.label}/${def.id === 'user' ? '' : '.claude/'}${directory}`,
            path: `${def.id === 'user' ? '' : '.claude/'}${directory}`,
            defaultExpanded: true,
        };
    }

    /* could not */
    async _fetchRoot(def, projectPath, query, scopePath = null) {
        try {
            const resp = query
                ? await window.API.findConfigFiles(def.id, projectPath, { q: query, path: scopePath || def.path || '', ignored: true })
                : await window.API.getConfigFileTree(def.id, projectPath, {
                    path: def.path || '', depth: window.ConfigEditorLazy.FETCH_DEPTH, ignored: true,
                });
            return {
                nodes: resp.tree || [],
                truncated: !!resp.truncated,
                ignoreStatus: resp.ignore_status || 'unavailable',
            };
        } catch (err) {
            const li = document.createElement('li');
            const message = (err.status === 400 && def.id === 'workdir')
                ? window.ConfigEditorRoots.workdirUnavailableNotice(def.label, projectPath)
                : `failed to load ${def.label}: ${err.message || err}`;
            li.appendChild(window.ConfigEditorRows.errorEl(message));
            return { errorLi: li };
        }
    }

    _buildNodeEl(rootId, node, depth, rootOpts) {
        const projectPath = rootOpts?.projectPath ?? this._currentProjectPath();
        const searching = !!rootOpts?.searching;
        if (node.kind === 'more') {
            return window.ConfigEditorRows.noticeLi(
                configEditorT('files.drawer.more_not_shown', { count: node.more_not_shown }));
        }
        const li = document.createElement('li');
        const isRoot = !!(rootOpts && rootOpts.isRoot);
        li.className = `config-editor-node config-editor-node--${node.is_dir ? 'dir' : 'file'}${isRoot ? ' config-editor-node--root' : ''}`;

        if (!node.is_dir) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'config-editor-file';
            btn.dataset.root = rootId;
            btn.dataset.path = node.rel_path;
            btn.dataset.readonly = node.read_only ? '1' : '0';
            btn.dataset.sensitive = node.is_sensitive ? '1' : '0';
            if (searching && this._isBest(rootId, node)) btn.classList.add('config-editor-match');
            btn.innerHTML = window.ConfigEditorRows.fileRowHtml(node, depth);
            btn.addEventListener('click', () => {
                this._openFile(rootId, node.rel_path, node.read_only, rootId === 'user' ? null : projectPath);
            });
            li.appendChild(btn);
            return li;
        }

        const key = `${rootId}:${node.rel_path || '__root__'}`;
        const collapsed = searching
            ? !(isRoot || node.filter_expanded)
            : window.ConfigEditorTreeState.startsCollapsed(
                rootId, node, isRoot ? rootOpts.defaultExpanded : undefined);

        const toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = `config-editor-toggle${isRoot ? ' config-editor-toggle--root' : ''}`;
        toggle.dataset.key = key;
        toggle.dataset.root = rootId;
        toggle.dataset.path = node.rel_path || '';
        if (searching && !isRoot && this._isBest(rootId, node)) toggle.classList.add('config-editor-match');
        toggle.setAttribute('aria-expanded', String(!collapsed));
        toggle.innerHTML = window.ConfigEditorRows.dirRowHtml(node, depth, isRoot);

        const childList = document.createElement('ul');
        childList.className = 'config-editor-list';
        childList.hidden = collapsed;
        let built = false;

        const buildChildren = async () => {
            if (built) return;
            built = true;
            const scopedPath = rootId === 'user' ? null : projectPath;
            let loadingLi = null;
            if (window.ConfigEditorLazy.needsFetch(node)) {
                loadingLi = window.ConfigEditorRows.noticeLi('loading...');
                childList.appendChild(loadingLi);
            }
            const verdict = await window.ConfigEditorLazy.childrenFor(rootId, node, scopedPath);
            if (loadingLi) loadingLi.remove();
            if (verdict.status === 'list_error' || verdict.status === 'failed') {
                childList.appendChild(window.ConfigEditorRows.noticeLi(verdict.message));
                return;
            }
            if (verdict.status === 'loaded') {
                node.children = verdict.nodes;
                node.children_loaded = true;
            }
            window.ConfigEditorFilter.visibleNodes(verdict.nodes, this._prefs()).forEach(
                (child) => childList.appendChild(this._buildNodeEl(rootId, child, depth + 1, { projectPath, searching })),
            );
        };
        if (!collapsed) buildChildren();

        toggle.addEventListener('click', () => {
            const nowExpanded = toggle.getAttribute('aria-expanded') !== 'true';
            if (nowExpanded) buildChildren();
            this._setExpanded(toggle, nowExpanded);
            if (!searching && !window.ConfigEditorTreeState.isForcedCollapsed(node.name)) {
                window.ConfigEditorTreeState.setNodeCollapsed(key, !nowExpanded);
            }
        });

        li.appendChild(toggle);
        li.appendChild(childList);
        return li;
    }
}

window.ConfigEditorPanel = new ConfigEditorPanelController();
console.log('[ConfigEditorPanel Module] Exported as window.ConfigEditorPanel');
