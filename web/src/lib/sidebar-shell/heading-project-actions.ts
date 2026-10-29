import { t } from '../i18n/index.svelte';
import { releaseThisTab } from '../drawer/row-menu-sleep';
import { companySource } from './company-source.svelte';
import { closeItemMenu } from '../item-menu/open.svelte';
import { headingDrawn, openHeadingRename } from './heading-rename.svelte';
import {
    announce, announceFailure, hg, reasonOf, refetchDrawer, usableGroups,
} from './interaction-globals';
import type { SidebarRow } from './legacy';
import { BAND_PROJECT_PREFIX, groupByUuid, projectBandKeyFor } from '../drawer/group-store';
import { isAgentKind, isBrowser } from '../drawer/bucketing';
import { showPath } from './show-path';
import { setProjectColorPreview } from '../project-colors/preview.svelte';

type Row = SidebarRow & {
    asleep?: boolean;
    label?: string;
    session_id?: string | null;
    session_uuid?: string | null;
};

function allRows(): Row[] {
    const rows = hg().SessionSidebar?._rows;
    return Array.isArray(rows) ? (rows as Row[]) : [];
}

export function projectRows(key: string): Row[] {
    return allRows().filter((r) => {
        if (!isAgentKind(r)) return false;
        if (r.project_id === null || r.project_id === undefined) return false;
        return projectBandKeyFor(r.project_id) === key;
    });
}

export function groupRows(groupUuid: string): Row[] {
    const G = usableGroups();
    return G ? allRows().filter((r) => G.groupOf(r.name) === groupUuid) : [];
}

export function projectNameFor(key: string): string | null {
    const row = projectRows(key).find((r) => r.project_name);
    return row ? (row.project_name as string) : (companySource().projectNameOf?.(key.slice(BAND_PROJECT_PREFIX.length)) ?? null);
}

/* no working directory */
export async function newAgentInProject(key: string): Promise<void> {
    const lp = hg().CloudeWeb?.launchpad;
    if (!lp || typeof lp.selectProject !== 'function') {
        announceFailure(t('sidebar.project.launcher_missing'));
        return;
    }
    const found = await projectFolderFor(key, 'sidebar.project.outcome.no_agent');
    if (!found) return;
    await lp.selectProject(found);
}

async function projectFolderFor(key: string, outcome: string): Promise<{ name: string; path: string } | null> {
    const name = projectNameFor(key);
    if (!name) { announceFailure(t('sidebar.project.no_name')); return null; }
    const anyRow = projectRows(key)[0];
    const projectId = anyRow ? anyRow.project_id : key.slice(BAND_PROJECT_PREFIX.length);
    let path: string | null = null;
    const api = hg().API;
    if (projectId != null && api) {
        try {
            const projects = await api.getProjects();
            const match = projects.find((p) => p && String(p.id) === String(projectId));
            path = (match && match.path) || null;
        } catch (err) {
            announceFailure(t('sidebar.project.list_read_failed', { reason: reasonOf(err) }));
            return null;
        }
    }
    if (!path) {
        announceFailure(t('sidebar.project.folder_unknown', { name, outcome: t(outcome) }));
        return null;
    }
    return { name, path };
}

export async function showProjectPath(key: string): Promise<void> {
    const found = await projectFolderFor(key, 'sidebar.project.outcome.nothing_shown');
    if (found) await showPath(found.path, found.name);
}

function releaseIfThisTab(row: Row): void {
    releaseThisTab({ name: row.name });
}

export async function sleepRows(rows: Row[], label: string): Promise<{ slept: number; failed: number }> {
    const api = hg().API;
    const targets = rows.filter((r) => !r.asleep && r.closed !== true && !isBrowser(r));
    if (!targets.length || !api) {
        announce(t('sidebar.heading.sleep_none', { name: label }));
        return { slept: 0, failed: 0 };
    }
    let slept = 0;
    const failures: string[] = [];
    for (const row of targets) {
        const who = row.label || row.name;
        if (!row.session_uuid) {
            failures.push(`${who}: ${t('session.sleep.no_uuid')}`);
            continue;
        }
        try {
            const res = await api.sleepSession(row.session_uuid);
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
    await refetchDrawer();
    if (failures.length) {
        announceFailure(t('sidebar.heading.sleep_partial', {
            name: label, slept, total: targets.length, reasons: failures.join('; '),
        }));
    } else {
        announce(t('sidebar.heading.slept', { name: label, count: slept }));
    }
    return { slept, failed: failures.length };
}

export function sleepProject(key: string): Promise<{ slept: number; failed: number }> {
    return sleepRows(projectRows(key), projectNameFor(key) || t('sidebar.project.unnamed'));
}

export function sleepGroup(groupUuid: string): Promise<{ slept: number; failed: number }> {
    const group = groupByUuid(groupUuid);
    return sleepRows(groupRows(groupUuid), group ? group.name : groupUuid);
}

async function closeRow(row: Row): Promise<void> {
    const api = hg().API!;
    if (row.asleep || row.closed === true) {
        if (!row.session_uuid) throw new Error('no session id recorded');
        await api.deleteSessionRecord(row.session_uuid);
        return;
    }
    releaseIfThisTab(row);
    if (row.session_id) await api.destroySession(row.session_id);
    else await api.destroyExternalSession(row.name);
}

export async function removeProject(key: string): Promise<boolean> {
    const name = projectNameFor(key);
    const { API: api, App: app } = hg();
    if (!name) { announceFailure(t('sidebar.project.no_name')); return false; }
    if (!api || !app) return false;
    const rows = projectRows(key);
    const ok = await app.showConfirmModal(
        t('sidebar.project.remove.title'),
        t('sidebar.project.remove.message', { name }),
        rows.length
            ? t('sidebar.project.remove.detail', { count: rows.length })
            : t('sidebar.project.remove.detail_empty'),
        t('sidebar.project.remove.confirm'),
        t('sidebar.group.remove.cancel'),
        'danger',
    );
    if (!ok) return false;
    const failures: string[] = [];
    for (const row of rows) {
        try {
            await closeRow(row);
        } catch (err) {
            failures.push(`${row.label || row.name}: ${reasonOf(err)}`);
        }
    }
    if (failures.length) {
        await refetchDrawer();
        announceFailure(t('sidebar.project.remove_partial', {
            name, failed: failures.length, total: rows.length, reasons: failures.join('; '),
        }));
        return false;
    }
    try {
        await api.archiveProject(name);
    } catch (err) {
        await refetchDrawer();
        announceFailure(t('sidebar.project.remove_failed', { name, reason: reasonOf(err) }));
        return false;
    }
    await refetchDrawer();
    announce(t('sidebar.project.removed', { name, count: rows.length }));
    return true;
}

export function renameProject(key: string): boolean {
    const name = projectNameFor(key);
    const api = hg().API;
    if (!name) { announceFailure(t('sidebar.project.no_name')); return false; }
    if (!api || !headingDrawn(key)) {
        announceFailure(t('sidebar.heading.rename.no_editor'));
        return false;
    }
    return openHeadingRename({
        key,
        seed: name,
        ariaLabel: t('sidebar.project.rename.aria', { name }),
        save: (value) => api.updateProject(name, { newName: value }),
        successText: (value) => t('sidebar.project.renamed', { name: value }),
        afterSuccess: () => refetchDrawer(),
    });
}

export async function setProjectColor(name: string, color: string, projectId: number): Promise<void> {
    closeItemMenu();
    const api = hg().API;
    try {
        if (!api) { announceFailure(t('sidebar.project.color_unavailable', { name })); return; }
        await api.updateProject(name, { color });
    } catch (err) {
        announceFailure(t('sidebar.project.color_failed', { name, reason: reasonOf(err) }));
    } finally {
        setProjectColorPreview(projectId, null);
    }
}
