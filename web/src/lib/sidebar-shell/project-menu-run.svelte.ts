import { companyList } from '../companies';
import { historyApi, type HistoryProject } from '../projects-shared/history-api';
import { ProjectsController } from '../projects-shared/page-controller.svelte';
import { SET_COMPANY } from '../projects-shared/ledger-model';
import { toolOf } from '../sessions-page/project-tools';
import { projects } from '../../opscenter/api/projects.svelte';
import { archivedProjects } from '../drawer/archived-visibility';
import { t } from '../i18n/index.svelte';
import { fileProject, newCompanyPrompt, removeFromCompany } from './company-actions';
import { createGroupThenAssign } from './group-assign';
import { announce, announceFailure, hg, refetchDrawer } from './interaction-globals';
import {
    archiveProject, newAgentInProject, projectNameFor, renameProject, showProjectPath, sleepProject,
} from './heading-project-actions';
import { openDrawerProjectTool, wantDrawerMigrate } from './project-menu-windows.svelte';

export function drawerProjectOf(key: string): HistoryProject | null {
    const id = Number(key.slice(2));
    const live = (projects.data ?? []).find((p) => p.id === id);
    const found = live ?? archivedProjects().find((p) => p.id === id);
    if (!found) return null;
    const archivedAt = live ? (live.archived_at ?? null) : 'archived';
    return {
        id, name: found.name, root: live ? (live.root ?? live.path) : (found.root ?? null), description: null, archived_at: archivedAt,
        last_opened_at: null, created_at: null, default_theme: null, company_id: found.company_id ?? null,
        new_sessions_join_swarm: Boolean((live as { new_sessions_join_swarm?: boolean } | undefined)?.new_sessions_join_swarm),
        storage: found.storage ?? null, pack_state: found.pack_state ?? null, moved_to_label: found.moved_to_label ?? null,
    };
}

let controller: ProjectsController | null = null;

function pageController(): ProjectsController {
    if (controller) return controller;
    const made = new ProjectsController({
        api: historyApi,
        t,
        embedded: true,
        close: () => undefined,
        onChanged: () => {
            void refetchDrawer();
            if (projects.status === 'ok') void projects.refresh?.();
        },
    });
    $effect.root(() => {
        $effect(() => {
            if (!made.notice) return;
            if (made.noticeKind === 'error') announceFailure(made.notice);
            else announce(made.notice);
        });
    });
    controller = made;
    return made;
}

export function runDrawerProjectVerb(key: string, id: string): void {
    const name = projectNameFor(key);
    if (id === 'new-session') void newAgentInProject(key);
    else if (id === 'rename-project') renameProject(key);
    else if (id === 'show-path') void showProjectPath(key);
    else if (id === 'sleep') void sleepProject(key);
    else if (id === 'archive-project') void archiveProject(key);
    else if (id === 'group') void createGroupThenAssign(null, undefined, key);
    else if (id === 'load-blueprint') hg().CloudeWeb?.openBlueprintsScreen?.();
    else if (id === 'remove-from-company') { if (name) void removeFromCompany(name); }
    else if (id === 'new-company-for-project') void newCompanyPrompt(name);
    else if (id.startsWith(SET_COMPANY)) {
        const company = companyList().find((c) => c.id === Number(id.slice(SET_COMPANY.length)));
        if (name && company) void fileProject(name, company);
    } else runOnController(key, id);
}

function runOnController(key: string, id: string): void {
    const fallbackName = projectNameFor(key);
    const project = drawerProjectOf(key) ?? (fallbackName ? {
        id: Number(key.slice(2)), name: fallbackName, root: null, description: null, archived_at: null,
        last_opened_at: null, created_at: null, default_theme: null, company_id: null,
    } : null);
    if (!project) return;
    const tool = toolOf(id);
    if (tool) {
        if (project.id != null) openDrawerProjectTool(tool, { id: project.id, name: project.name });
        return;
    }
    if (id === 'migrate-project' || id === 'migrate-back') wantDrawerMigrate();
    pageController().projectAction(id, { key, project, session_total: 0, counts: {}, last_activity_at: null, sessions: [] });
}
