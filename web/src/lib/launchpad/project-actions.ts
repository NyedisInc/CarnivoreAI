import { PROJECT_CREATE_KEYS } from '../../../../client/js/labels/project-create.js';
import { setListInbox, setListNudge } from '../../cplugs/huddle/task-list-prefs';
import type { ProjectRow, Translate } from '../sessions/types';
import type { CreateHost } from './create-host';
import { reasonOf } from './failure-reason';
import type { ModalOpeners } from './modals';

export async function archiveProjectFlow(
    host: CreateHost,
    t: Translate,
    projectName: string,
): Promise<boolean> {
    try {
        const confirmed = await host.confirm(
            t(PROJECT_CREATE_KEYS.archiveTitle),
            t(PROJECT_CREATE_KEYS.archiveMessage, { name: projectName }),
            t(PROJECT_CREATE_KEYS.archiveDetails),
            t(PROJECT_CREATE_KEYS.archiveConfirm),
            t(PROJECT_CREATE_KEYS.cancel),
        );
        if (!confirmed) return false;
        await host.archiveProject(projectName);
        await host.reloadProjects();
        return true;
    } catch (error) {
        console.error('CloudeWeb: failed to archive project:', error);
        host.showError(t(PROJECT_CREATE_KEYS.archiveFailed, { reason: reasonOf(error, t) }));
        return false;
    }
}

export async function unarchiveProjectFlow(
    host: CreateHost,
    t: Translate,
    projectName: string,
): Promise<boolean> {
    try {
        await host.unarchiveProject(projectName);
        await host.reloadProjects();
        return true;
    } catch (error) {
        console.error('CloudeWeb: failed to restore project:', error);
        host.showError(t(PROJECT_CREATE_KEYS.restoreFailed, { reason: reasonOf(error, t) }));
        return false;
    }
}

export type EditOutcome = 'updated' | 'cancelled' | 'unchanged' | 'failed';

export async function editProjectFlow(
    host: CreateHost,
    modals: ModalOpeners,
    t: Translate,
    project: ProjectRow,
): Promise<EditOutcome> {
    const currentName = String(project.name ?? '');
    const currentDescription = String(project.description ?? '');
    const currentDefault = String(project.default_launch_profile ?? '');
    const currentColor = String(project.color ?? '');
    const projectId = typeof project.id === 'number' ? project.id : null;
    try {
        const result = await modals.edit({
            projectName: currentName,
            projectPath: String(project.path ?? ''),
            projectDescription: currentDescription,
            projectDefaultLaunchProfile: currentDefault,
            projectColor: currentColor,
            projectId,
        });
        if (!result) return 'cancelled';

        const nameChanged = result.name !== currentName;
        const descChanged = result.description !== currentDescription;
        const defaultChanged = result.defaultLaunchProfile !== undefined && result.defaultLaunchProfile !== currentDefault;
        const colorChanged = result.color !== undefined && result.color !== currentColor;
        const nudgeChanged = result.nudge !== undefined && projectId !== null;
        const inboxChanged = result.inbox !== undefined && projectId !== null;
        if (!nameChanged && !descChanged && !defaultChanged && !colorChanged && !nudgeChanged && !inboxChanged) return 'unchanged';

        host.updateStatus(t(PROJECT_CREATE_KEYS.editStatusUpdating, { name: currentName }));
        const fields: Record<string, unknown> = {};
        if (nameChanged) fields.newName = result.name;
        if (descChanged) fields.description = result.description;
        if (defaultChanged) fields.defaultLaunchProfile = result.defaultLaunchProfile;
        if (colorChanged) fields.color = result.color;
        if (Object.keys(fields).length > 0) await host.updateProject(currentName, fields);
        if (nudgeChanged && projectId !== null) {
            try {
                await setListNudge(projectId, result.nudge === true);
            } catch (error) {
                console.error('CloudeWeb: failed to set the huddle nudge:', error);
                host.showError(t('project.edit.task_manager.failed', { reason: reasonOf(error, t) }));
            }
        }
        if (inboxChanged && projectId !== null) {
            try {
                await setListInbox(projectId, result.inbox === true);
            } catch (error) {
                console.error('CloudeWeb: failed to set the huddle add box switch:', error);
                host.showError(t('project.edit.task_manager.failed_inbox', { reason: reasonOf(error, t) }));
            }
        }
        await host.reloadProjects();
        host.updateStatus(t(PROJECT_CREATE_KEYS.editStatusDone));
        return 'updated';
    } catch (error) {
        console.error('CloudeWeb: failed to update project:', error);
        host.showError(t(PROJECT_CREATE_KEYS.editFailed, { reason: reasonOf(error, t) }));
        return 'failed';
    }
}
