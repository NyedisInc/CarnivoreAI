/* the home screen */
import { PROJECT_CREATE_KEYS } from '../../../../client/js/labels/project-create.js';
import { presenceBadgeText } from '../../../../client/js/labels/project-tree.js';
import type { ProjectRow, Translate } from '../sessions/types';
import type { CreateHost } from './create-host';
import type { ChoiceItem } from './modal-types';
import type { ModalOpeners } from './modals';
import { createProjectFlow } from './create-flow';
import { openProjectFromFolderFlow } from './open-folder-flow';

export type NewProjectChoice = 'empty' | 'clone' | 'folder' | null;

export function newProjectItems(t: Translate): ChoiceItem[] {
    return [
        {
            key: 'empty',
            label: t(PROJECT_CREATE_KEYS.newProjectEmpty),
            sub: t(PROJECT_CREATE_KEYS.newProjectEmptySub),
        },
        {
            key: 'clone',
            label: t(PROJECT_CREATE_KEYS.newProjectClone),
            sub: t(PROJECT_CREATE_KEYS.newProjectCloneSub),
        },
        {
            key: 'folder',
            label: t(PROJECT_CREATE_KEYS.newProjectFolder),
            sub: t(PROJECT_CREATE_KEYS.newProjectFolderSub),
        },
    ];
}

export async function startNewClaudeProject(
    host: CreateHost,
    modals: ModalOpeners,
    t: Translate,
): Promise<NewProjectChoice> {
    const how = await modals.choice({
        title: t(PROJECT_CREATE_KEYS.newProjectTitle),
        items: newProjectItems(t),
    });
    if (how === 'empty') {
        await createProjectFlow(host, modals, t, null);
        return 'empty';
    }
    if (how === 'clone') {
        await cloneFromGithubFlow(host, modals, t);
        return 'clone';
    }
    if (how === 'folder') {
        await openProjectFromFolderFlow(host, modals, t);
        return 'folder';
    }
    return null;
}

export function existingProjectItems(
    projects: ProjectRow[],
    presenceFor: (project: ProjectRow) => Record<string, unknown> | null,
    t: Translate,
): ChoiceItem[] {
    return projects.map((project) => {
        const row = presenceFor(project);
        const presence = row ? String(row.presence ?? 'unchecked') : 'unchecked';
        const detail = row && row.presence_detail ? String(row.presence_detail) : null;
        const reason = presenceBadgeText(presence, detail, t);
        return {
            key: String(project.name ?? ''),
            label: String(project.name ?? ''),
            sub: String(project.path ?? ''),
            disabled: presence === 'missing' || presence === 'unreachable',
            reason,
        };
    });
}

export type NewSessionOutcome = 'opened' | 'cancelled' | 'cannot_determine' | 'none';

export async function startSessionInExistingProject(
    host: CreateHost,
    modals: ModalOpeners,
    t: Translate,
): Promise<NewSessionOutcome> {
    if (host.projectsListingOk() === false) {
        await modals.choice({
            title: t(PROJECT_CREATE_KEYS.newSessionTitle),
            items: [],
            emptyMessage: t(PROJECT_CREATE_KEYS.newSessionCannotDetermine),
            emptyKind: 'unknown',
        });
        return 'cannot_determine';
    }
    const projects = host.projects() || [];
    if (projects.length === 0) {
        await modals.choice({
            title: t(PROJECT_CREATE_KEYS.newSessionTitle),
            items: [],
            emptyMessage: t(PROJECT_CREATE_KEYS.newSessionNone),
            emptyKind: 'info',
        });
        return 'none';
    }
    const chosen = await modals.choice({
        title: t(PROJECT_CREATE_KEYS.newSessionPickTitle),
        items: existingProjectItems(projects, (p) => host.presenceFor(p), t),
    });
    if (!chosen) return 'cancelled';
    const project = projects.find((p) => String(p.name ?? '') === chosen);
    if (!project) return 'cancelled';
    await host.selectProject(project, null);
    return 'opened';
}

export type CloneOutcome = 'opened' | 'cancelled_provider' | 'cancelled' | 'failed';

export async function cloneFromGithubFlow(
    host: CreateHost,
    modals: ModalOpeners,
    t: Translate,
): Promise<CloneOutcome> {
    const choice = await host.chooseProvider(null, t(PROJECT_CREATE_KEYS.wizardNext));
    if (!choice) return 'cancelled_provider';

    const defaultParentDir = await host.defaultParentDir();
    const project = await modals.clone({
        confirmLabel: t(PROJECT_CREATE_KEYS.wizardCreate),
        clone: (payload) => host.cloneProject(payload),
        ...(defaultParentDir ? { defaultParentDir } : {}),
    });
    if (!project) return 'cancelled';

    try {
        await host.reloadProjects();
        await host.selectProject(
            {
                name: project.name,
                path: project.path,
                description: project.description || null,
            },
            choice,
        );
        return 'opened';
    } catch (error) {
        console.error('CloudeWeb: failed to open the cloned project:', error);
        host.showError(
            t(PROJECT_CREATE_KEYS.createFailed, {
                reason: error instanceof Error && error.message
                    ? error.message
                    : t('error.server_unreachable'),
            }),
        );
        return 'failed';
    }
}
