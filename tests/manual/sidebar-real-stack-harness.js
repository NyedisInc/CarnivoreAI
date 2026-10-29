
(function () {
    const SKIP = new Set(['app.js', 'router.js']);

    const fixture = window.__fixture || { rows: [], groups: [] };

    const groupState = { groups: [], members: new Map() };
    (fixture.groups || []).forEach((g, i) => {
        groupState.groups.push({ group_uuid: g.uuid, name: g.name, position: i,
            member_session_uuids: g.member_session_uuids || null });
        for (const m of (g.members || [])) groupState.members.set(m, g.uuid);
    });

    function groupsBody() {
        return {
            status: 'ok',
            detail: null,
            groups: groupState.groups.slice()
                .sort((a, b) => a.position - b.position)
                .map((g) => ({
                    group_uuid: g.group_uuid,
                    name: g.name,
                    position: g.position,
                    members: Array.from(groupState.members.entries())
                        .filter(([, u]) => u === g.group_uuid).map(([n]) => n),
                    ...(g.member_session_uuids ? { member_session_uuids: g.member_session_uuids.slice() } : {}),
                })),
        };
    }

    window.__groupsUnavailable = false;

    const STUB = {
        async listSessionGroups() {
            if (window.__groupsUnavailable) {
                return { status: 'unavailable', groups: [], detail: 'harness: table unreadable' };
            }
            return groupsBody();
        },
        async assignSessionGroup(name, uuid) {
            if (uuid === null || uuid === undefined) groupState.members.delete(name);
            else groupState.members.set(name, uuid);
            return groupsBody();
        },
        async createSessionGroup(name) {
            const uuid = `h${groupState.groups.length + 1}`;
            groupState.groups.push({ group_uuid: uuid, name, position: groupState.groups.length });
            return groupsBody();
        },
        async renameSessionGroup(uuid, name) {
            const g = groupState.groups.find((x) => x.group_uuid === uuid);
            if (g) g.name = name;
            return groupsBody();
        },
        async deleteSessionGroup(uuid) {
            let freed = 0;
            for (const [n, u] of Array.from(groupState.members.entries())) {
                if (u === uuid) { groupState.members.delete(n); freed += 1; }
            }
            groupState.groups = groupState.groups.filter((g) => g.group_uuid !== uuid);
            return Object.assign(groupsBody(), { freed });
        },
        async reorderSessionGroups(uuids) {
            uuids.forEach((u, i) => {
                const g = groupState.groups.find((x) => x.group_uuid === u);
                if (g) g.position = i;
            });
            return groupsBody();
        },
        async listAttachableSessions() { return JSON.parse(JSON.stringify(fixture.rows || [])); },
        async listSessions() { return []; },
        async listSessionRecords() { return JSON.parse(JSON.stringify(fixture.records || [])); },
        async reorderSessionGroupMembers(uuid, sessionUuids) {
            const g = groupState.groups.find((x) => x.group_uuid === uuid);
            if (g) g.member_session_uuids = sessionUuids.slice();
            return groupsBody();
        },
        async getSession() { return null; },
        async adoptSession() { return {}; },
        async setSessionUnread() { return {}; },
        async destroySession() { return {}; },
        async destroyExternalSession() { return {}; },
    };
    function installStub() {
        if (!window.API || typeof window.API !== 'object') window.API = {};
        Object.assign(window.API, STUB);
    }
    installStub();
    window.App = { returnToExistingTerminal() {} };
    window.TerminalController = { async destroySession() {} };

    function loadScript(src, isModule) {
        return new Promise((resolve) => {
            const el = document.createElement('script');
            if (isModule) el.type = 'module';
            el.src = src;
            el.onload = () => resolve();
            el.onerror = () => {
                (window.__harnessLoadErrors = window.__harnessLoadErrors || []).push(src);
                resolve();
            };
            document.body.appendChild(el);
        });
    }

    async function boot() {
        const html = await (await fetch('/static/index.html')).text();
        const doc = new DOMParser().parseFromString(html, 'text/html');
        for (const link of doc.querySelectorAll('link[rel="stylesheet"]')) {
            const el = document.createElement('link');
            el.rel = 'stylesheet';
            el.href = link.getAttribute('href');
            document.head.appendChild(el);
        }
        const mount = document.getElementById('panel-mount');
        for (const sel of ['#session-sidebar-backdrop', '#session-sidebar-panel']) {
            const node = doc.querySelector(sel);
            if (node) mount.appendChild(document.importNode(node, true));
        }
        const header = doc.querySelector('.header');
        if (header) {
            document.getElementById('header-mount').appendChild(document.importNode(header, true));
        }
        for (const s of doc.querySelectorAll('script[src]')) {
            const src = s.getAttribute('src');
            const base = src.split('/').pop();
            if (SKIP.has(base)) continue;
            await loadScript(src, s.getAttribute('type') === 'module');
            if (base === 'api.js' || base === 'api-toasts.js') installStub();
        }
        for (let i = 0; i < 100 && !(globalThis.CloudeI18n && globalThis.CloudeLabels); i++) {
            await new Promise((r) => setTimeout(r, 50));
        }
        window.SessionSidebar.show();
        window.SessionSidebar.open();
        await window.SessionSidebar._fetchAndRender();
        window.__sidebarReady = true;
    }

    window.addEventListener('DOMContentLoaded', () => {
        boot().catch((err) => { window.__harnessBootError = String(err && err.stack || err); });
    });
})();
