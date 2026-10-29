import {
    PROJECT_CREATE_KEYS,
    uniqueNameFailure,
} from '../../../../client/js/labels/project-create.js';
import { refusedWith } from './refusal-shape';
import type { Translate } from '../sessions/types';
import type { CreateHost } from './create-host';
import type { ModalOpeners } from './modals';

export const UNIQUE_NAME_ATTEMPTS = 20;

export interface KeyedError extends Error {
    cloudeKey?: string;
}

interface ApiError extends Error {
    status?: number;
    body?: { existing_project?: { name?: string | null } | null } | null;
}

export async function saveProjectWithUniqueName(
    host: CreateHost,
    row: { name: string; path: string; description?: string | null },
): Promise<string> {
    let attempt = row.name;
    for (let i = 0; i < UNIQUE_NAME_ATTEMPTS; i += 1) {
        try {
            await host.createProject({
                name: attempt,
                path: row.path,
                description: row.description ?? null,
            });
            return attempt;
        } catch (error) {
            const status = (error as ApiError | null)?.status;
            if (status === 409) {
                const existing = (error as ApiError).body?.existing_project?.name;
                if (existing) return String(existing);
                throw error;
            }
            if (!refusedWith(error, { code: 'project_name_taken', phrase: 'already exists' })) throw error;
            attempt = `${row.name} (${i + 2})`;
        }
    }
    const failure: KeyedError = new Error(PROJECT_CREATE_KEYS.uniqueNameFailed);
    failure.cloudeKey = PROJECT_CREATE_KEYS.uniqueNameFailed;
    throw failure;
}

export type OpenFolderOutcome =
    | 'opened'
    | 'cancelled_folder'
    | 'cancelled_name'
    | 'cancelled_provider'
    | 'no_picker'
    | 'failed';

export async function openProjectFromFolderFlow(
    host: CreateHost,
    modals: ModalOpeners,
    t: Translate,
): Promise<OpenFolderOutcome> {
    try {
        const picker = host.folderPicker();
        if (!picker) {
            host.showError(t(PROJECT_CREATE_KEYS.folderPickerUnavailable));
            return 'no_picker';
        }
        const selectedPath = await picker();
        if (!selectedPath) return 'cancelled_folder';

        const defaultName = selectedPath.split('/').filter(Boolean).pop() || selectedPath;
        const details = await modals.name({
            title: t(PROJECT_CREATE_KEYS.nameAddTitle),
            confirmLabel: t(PROJECT_CREATE_KEYS.wizardNext),
            defaultName,
            pathHint: selectedPath,
        });
        if (!details) return 'cancelled_name';

        const choice = await host.chooseProvider(null, t(PROJECT_CREATE_KEYS.wizardCreate));
        if (!choice) return 'cancelled_provider';

        host.updateStatus(t(PROJECT_CREATE_KEYS.editStatusUpdating, { name: details.name }));
        const savedName = await saveProjectWithUniqueName(host, {
            name: details.name,
            path: selectedPath,
            description: details.description || null,
        });
        await host.reloadProjects();
        await host.selectProject(
            {
                name: savedName,
                path: selectedPath,
                description: details.description || null,
            },
            choice,
        );
        return 'opened';
    } catch (error) {
        console.error('CloudeWeb: failed to open project from folder:', error);
        host.showError(
            t(PROJECT_CREATE_KEYS.createFolderFailed, {
                reason: uniqueNameFailure(error, t),
            }),
        );
        return 'failed';
    }
}
