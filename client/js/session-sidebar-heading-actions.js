
console.log('[SessionSidebarHeadingActions Module] Loading...');

(function () {
    let wired = false;

    function tr(key, params) {
        const i18n = globalThis.CloudeI18n;
        return (i18n && typeof i18n.t === 'function') ? i18n.t(key, params) : key;
    }

    function GA() { return window.SessionSidebarGroupActions; }

    function openBlueprintsScreen() {
        const web = window.CloudeWeb;
        if (web && typeof web.openBlueprintsScreen === 'function') web.openBlueprintsScreen();
    }

    function announce(text) {
        const ga = GA();
        if (ga && ga.announce) ga.announce(text);
    }

    function announceFailure(text) {
        announce(text);
        const notice = window.WriteFailureNotice;
        if (notice && typeof notice.report === 'function') notice.report(text);
    }

    function reasonOf(err) {
        return (err && err.message) || String(err || 'the server could not be reached');
    }

    async function refresh() {
        const bar = window.SessionSidebar;
        if (bar && typeof bar._fetchAndRender === 'function') {
            bar._lastSig = null;
            await bar._fetchAndRender();
        }
    }

    function allRows() {
        const bar = window.SessionSidebar;
        return (bar && Array.isArray(bar._rows)) ? bar._rows : [];
    }

    function projectRows(key) {
        const G = window.SessionSidebarGroupStore;
        const KG = window.SessionSidebarKindGroups;
        return allRows().filter((r) => {
            if (KG && !KG.isAgentKind(r)) return false;
            if (r.project_id === null || r.project_id === undefined) return false;
            return (G ? G.projectBandKeyFor(r.project_id) : `p:${r.project_id}`) === key;
        });
    }

    function groupRows(groupUuid) {
        const G = window.SessionSidebarGroupStore;
        if (!G || !G.isUsable()) return [];
        return allRows().filter((r) => G.groupOf(r.name) === groupUuid);
    }

    function projectNameFor(key) {
        const row = projectRows(key).find((r) => r.project_name);
        return row ? row.project_name : null;
    }

    async function newAgentInProject(key) {
        const lp = window.CloudeWeb && window.CloudeWeb.launchpad;
        if (!lp || typeof lp.selectProject !== 'function') {
            announceFailure('cannot start a new agent: the launcher did not load');
            return;
        }
        const found = await projectFolderFor(key, 'no agent was started');
        if (!found) return;
        await lp.selectProject(found);
    }

    async function projectFolderFor(key, outcome) {
        const name = projectNameFor(key);
        if (!name) { announceFailure(tr('sidebar.project.no_name')); return null; }
        const anyRow = projectRows(key)[0];
        const projectId = anyRow ? anyRow.project_id : null;
        let path = null;
        if (projectId != null && window.API && typeof window.API.getProjects === 'function') {
            try {
                const projects = await window.API.getProjects();
                const match = Array.isArray(projects) ? projects.find((p) => p && p.id === projectId) : null;
                path = match ? match.path : null;
            } catch (err) {
                announceFailure('could not read the project list: ' + reasonOf(err));
                return null;
            }
        }
        if (!path) {
            announceFailure('CANNOT DETERMINE the folder for "' + name
                + '": no project record names one, so ' + outcome);
            return null;
        }
        return { name, path };
    }

    async function showProjectPath(key) {
        const web = window.CloudeWeb;
        if (!web || typeof web.showPath !== 'function') {
            announceFailure('cannot show the path: the popup did not load');
            return;
        }
        const found = await projectFolderFor(key, 'nothing was shown');
        if (found) await web.showPath(found.path, found.name);
    }

    function releaseIfThisTab(row) {
        const S = window.SessionRowMenuSleep;
        if (S && typeof S.releaseThisTab === 'function') S.releaseThisTab({ name: row.name });
    }

    function spaced(groups) {
        const out = [];
        groups.filter((group) => group.length).forEach((group) => {
            group.forEach((entry, i) => out.push(i === 0 && out.length ? { ...entry, separatorBefore: true } : entry));
        });
        return out;
    }

    function openProjectMenu(anchor, key) {
        const ga = GA();
        if (!ga) return;
        const name = projectNameFor(key) || tr('sidebar.project.unnamed');
        const groups = [
            [
                { label: tr('opscenter.tabs.new_agent'), icon: 'agent', id: 'new-agent', onPick: () => newAgentInProject(key) },
                { label: tr('layout.row.load_blueprint'), icon: 'cube', id: 'load-blueprint', onPick: () => openBlueprintsScreen() },
            ],
            [
                { label: tr('sidebar.heading.rename'), icon: 'rename', id: 'rename-project', onPick: () => renameProject(key, anchor) },
            ],
            [
                { label: tr('sidebar.show_path.label'), icon: 'show-path', id: 'show-path', onPick: () => showProjectPath(key) },
            ],
            [
                { label: tr('sidebar.heading.sleep'), icon: 'sleep', id: 'sleep', onPick: () => sleepProject(key) },
            ],
            [
                { label: tr('sidebar.heading.remove'), icon: 'close', id: 'delete-project', onPick: () => removeProject(key) },
            ],
        ];
        ga.showMenu(anchor, spaced(groups), tr('sidebar.project.menu.title', { name }));
    }

    function renameProject(key, anchor) {
        const name = projectNameFor(key);
        if (!name) { announceFailure(tr('sidebar.project.no_name')); return; }
        const R = window.SessionSidebarRename;
        if (!R || R.openHeadingEditor(anchor, {
            seed: name,
            ariaLabel: `Rename project ${name}`,
            save: (value) => window.API.updateProject(name, { newName: value }),
            successText: (value) => tr('sidebar.project.renamed', { name: value }),
            afterSuccess: () => refresh(),
        }) === null) announceFailure('could not open the rename editor');
    }

    async function sleepRows(rows, label) {
        const KG = window.SessionSidebarKindGroups;
        const targets = rows.filter((r) => !r.asleep && !(KG && KG.isBrowser(r)));
        if (!targets.length) {
            announce(tr('sidebar.heading.sleep_none', { name: label }));
            return { slept: 0, failed: 0 };
        }
        let slept = 0;
        const failures = [];
        for (const row of targets) {
            const who = row.label || row.name;
            if (!row.session_uuid) { failures.push(`${who}: ${tr('session.sleep.no_uuid')}`); continue; }
            try {
                const res = await window.API.sleepSession(row.session_uuid);
                if (res && res.status === 'asleep') {
                    slept += 1;
                    releaseIfThisTab(row);
                } else {
                    failures.push(`${who}: ${(res && res.detail) || 'refused'}`);
                }
            } catch (err) {
                failures.push(`${who}: ${reasonOf(err)}`);
            }
        }
        await refresh();
        if (failures.length) {
            announceFailure(tr('sidebar.heading.sleep_partial', {
                name: label, slept, total: targets.length, reasons: failures.join('; '),
            }));
        } else {
            announce(tr('sidebar.heading.slept', { name: label, count: slept }));
        }
        return { slept, failed: failures.length };
    }

    function sleepProject(key) {
        return sleepRows(projectRows(key), projectNameFor(key) || tr('sidebar.project.unnamed'));
    }

    function sleepGroup(groupUuid) {
        const G = window.SessionSidebarGroupStore;
        const group = G && G.groupByUuid(groupUuid);
        return sleepRows(groupRows(groupUuid), group ? group.name : groupUuid);
    }

    async function closeRow(row) {
        if (row.asleep) {
            if (!row.session_uuid) throw new Error('no session id recorded');
            await window.API.deleteSessionRecord(row.session_uuid);
            return;
        }
        releaseIfThisTab(row);
        if (row.session_id) await window.API.destroySession(row.session_id);
        else await window.API.destroyExternalSession(row.name);
    }

    async function removeProject(key) {
        const name = projectNameFor(key);
        if (!name) { announceFailure(tr('sidebar.project.no_name')); return false; }
        const rows = projectRows(key);
        const ok = await window.App.showConfirmModal(
            tr('sidebar.project.remove.title'),
            tr('sidebar.project.remove.message', { name }),
            rows.length
                ? tr('sidebar.project.remove.detail', { count: rows.length })
                : tr('sidebar.project.remove.detail_empty'),
            tr('sidebar.project.remove.confirm'),
            tr('sidebar.group.remove.cancel'),
            'danger',
        );
        if (!ok) return false;
        const failures = [];
        for (const row of rows) {
            try {
                await closeRow(row);
            } catch (err) {
                failures.push(`${row.label || row.name}: ${reasonOf(err)}`);
            }
        }
        if (failures.length) {
            await refresh();
            announceFailure(tr('sidebar.project.remove_partial', {
                name, failed: failures.length, total: rows.length, reasons: failures.join('; '),
            }));
            return false;
        }
        try {
            await window.API.archiveProject(name);
        } catch (err) {
            await refresh();
            announceFailure(tr('sidebar.project.remove_failed', { name, reason: reasonOf(err) }));
            return false;
        }
        await refresh();
        announce(tr('sidebar.project.removed', { name, count: rows.length }));
        return true;
    }

    function init() {
        if (wired) return;
        document.addEventListener('click', (e) => {
            const btn = e.target.closest && e.target.closest('[data-project-menu]');
            if (!btn) return;
            const CC = window.SessionSidebarChromeClicks;
            if (CC && CC.shellOwns && CC.shellOwns(e.target)) return;
            e.preventDefault();
            e.stopPropagation();
            const key = btn.getAttribute('data-project-menu');
            setTimeout(() => openProjectMenu(btn, key), 0);
        });
        wired = true;
    }

    window.SessionSidebarHeadingActions = {
        init, openProjectMenu, renameProject,
        sleepProject, sleepGroup, removeProject, projectRows, groupRows,
        newAgentInProject,
    };
    init();
    console.log('[SessionSidebarHeadingActions Module] Exported as window.SessionSidebarHeadingActions');
})();
