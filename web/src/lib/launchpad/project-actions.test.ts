/* THE THROWN SENTENCE */
import { describe, expect, test } from 'vitest';

import { enT, modals, recorder } from './create-harness';
import { archiveProjectFlow, editProjectFlow, unarchiveProjectFlow } from './project-actions';
import {
    UNIQUE_NAME_ATTEMPTS,
    openProjectFromFolderFlow,
    saveProjectWithUniqueName,
} from './open-folder-flow';
import { uniqueNameFailure } from '../../../../client/js/labels/project-create.js';

describe('archiving asks, restoring does not', () => {
    test('archiving confirms, then archives, then refreshes', async () => {
        const rec = recorder();
        expect(await archiveProjectFlow(rec.host, enT(), 'api')).toBe(true);
        expect(rec.calls.map(([kind]) => kind)).toEqual([
            'confirm',
            'archiveProject',
            'reloadProjects',
        ]);
    });

    test('the confirm names the real consequences', async () => {
        const seen: string[] = [];
        const rec = recorder({
            confirm: async (title, message, details, primary) => {
                seen.push(title, message, String(details), primary);
                return false;
            },
        });
        await archiveProjectFlow(rec.host, enT(), 'api');
        expect(seen[0]).toBe('archive project');
        expect(seen[1]).toBe('archive "api"?');
        expect(seen[2]).toMatch(/non-running sessions are archived with it/);
        expect(seen[2]).toMatch(/folder on disk is not touched/);
        expect(seen[3]).toBe('archive');
    });

    test('refusing the confirm archives nothing', async () => {
        const rec = recorder({ confirm: async () => false });
        expect(await archiveProjectFlow(rec.host, enT(), 'api')).toBe(false);
        expect(rec.calls.map(([kind]) => kind)).not.toContain('archiveProject');
    });

    test('a failed archive is a sentence, not a thrown error', async () => {
        const rec = recorder({
            archiveProject: async () => {
                throw new Error('server said no');
            },
        });
        expect(await archiveProjectFlow(rec.host, enT(), 'api')).toBe(false);
        expect(rec.errors).toEqual(['failed to archive project: server said no']);
    });

    test('restoring never confirms, because it only adds a row back', async () => {
        const rec = recorder();
        expect(await unarchiveProjectFlow(rec.host, enT(), 'api')).toBe(true);
        expect(rec.calls.map(([kind]) => kind)).toEqual(['unarchiveProject', 'reloadProjects']);
        expect(rec.calls.map(([kind]) => kind)).not.toContain('confirm');
    });

    test('a failed restore is a sentence too', async () => {
        const rec = recorder({
            unarchiveProject: async () => {
                throw new Error('');
            },
        });
        expect(await unarchiveProjectFlow(rec.host, enT(), 'api')).toBe(false);
        expect(rec.errors).toEqual([
            'failed to restore project: the server could not be reached',
        ]);
    });
});

describe('renaming a project changes the LABEL and nothing on disk', () => {
    const project = { name: 'api', path: '/p/api', description: 'the api' };

    test('a changed name is sent as newName', async () => {
        const rec = recorder();
        const m = modals({ edit: { name: 'api2', description: 'the api' } });
        expect(await editProjectFlow(rec.host, m.openers, enT(), project)).toBe('updated');
        const call = rec.calls.find(([kind]) => kind === 'updateProject')?.[1] as {
            name: string;
            fields: Record<string, unknown>;
        };
        expect(call.name).toBe('api');
        expect(call.fields).toEqual({ newName: 'api2' });
    });

    test('a changed description alone is sent alone', async () => {
        const rec = recorder();
        const m = modals({ edit: { name: 'api', description: 'new words' } });
        expect(await editProjectFlow(rec.host, m.openers, enT(), project)).toBe('updated');
        const call = rec.calls.find(([kind]) => kind === 'updateProject')?.[1] as {
            fields: Record<string, unknown>;
        };
        expect(call.fields).toEqual({ description: 'new words' });
    });

    test('a changed color alone is sent alone, as a hex color', async () => {
        const rec = recorder();
        const m = modals({ edit: { name: 'api', description: 'the api', color: '#7457c2' } });
        expect(await editProjectFlow(rec.host, m.openers, enT(), project)).toBe('updated');
        const call = rec.calls.find(([kind]) => kind === 'updateProject')?.[1] as { fields: Record<string, unknown> };
        expect(call.fields).toEqual({ color: '#7457c2' });
    });

    test('the same color, or no color before and after, writes nothing; a pick of no color on a colored project removes it', async () => {
        const rec = recorder();
        const m2 = modals({ edit: { name: 'api', description: 'the api', color: '#4e69ba' } });
        expect(await editProjectFlow(rec.host, m2.openers, enT(), { ...project, color: '#4e69ba' })).toBe('unchanged');
        const m3 = modals({ edit: { name: 'api', description: 'the api', color: '' } });
        expect(await editProjectFlow(rec.host, m3.openers, enT(), { ...project, color: '' })).toBe('unchanged');
        expect(rec.calls.map(([kind]) => kind)).not.toContain('updateProject');
        const m = modals({ edit: { name: 'api', description: 'the api', color: '' } });
        expect(await editProjectFlow(rec.host, m.openers, enT(), { ...project, color: '#4e69ba' })).toBe('updated');
        const call = rec.calls.find(([kind]) => kind === 'updateProject')?.[1] as { fields: Record<string, unknown> };
        expect(call.fields).toEqual({ color: '' });
    });

    test('saving the same values writes NOTHING', async () => {
        const rec = recorder();
        const m = modals({ edit: { name: 'api', description: 'the api' } });
        expect(await editProjectFlow(rec.host, m.openers, enT(), project)).toBe('unchanged');
        expect(rec.calls.map(([kind]) => kind)).not.toContain('updateProject');
    });

    test('cancelling writes nothing', async () => {
        const rec = recorder();
        const m = modals({ edit: null });
        expect(await editProjectFlow(rec.host, m.openers, enT(), project)).toBe('cancelled');
        expect(rec.calls.map(([kind]) => kind)).not.toContain('updateProject');
    });

    test('a name collision is reported as the server said it', async () => {
        const rec = recorder({
            updateProject: async () => {
                throw new Error('a project named api2 already exists');
            },
        });
        const m = modals({ edit: { name: 'api2', description: 'the api' } });
        expect(await editProjectFlow(rec.host, m.openers, enT(), project)).toBe('failed');
        expect(rec.errors[0]).toBe(
            'failed to update project: a project named api2 already exists',
        );
    });

    test('the modal is shown the FOLDER, which it may not edit', async () => {
        const rec = recorder();
        const m = modals({ edit: null });
        await editProjectFlow(rec.host, m.openers, enT(), project);
        const request = m.asked[0]![1] as { projectPath: string };
        expect(request.projectPath).toBe('/p/api');
    });
});

describe('a unique project name is FOUND, never forced', () => {
    test('a free name is used as typed', async () => {
        const rec = recorder();
        const saved = await saveProjectWithUniqueName(rec.host, { name: 'api', path: '/p/api' });
        expect(saved).toBe('api');
    });

    test('a 409 root conflict reuses the existing project and never retries', async () => {
        let attempts = 0;
        const rec = recorder({
            createProject: async () => {
                attempts += 1;
                throw Object.assign(new Error("a project at /p/api already exists, named 'api (original)'"), {
                    status: 409,
                    body: { existing_project: { id: 7, name: 'api (original)' } },
                });
            },
            projects: () => [],
        });
        const saved = await saveProjectWithUniqueName(rec.host, { name: 'api', path: '/p/api' });
        expect(saved).toBe('api (original)');
        expect(attempts).toBe(1);
    });

    test('a collision on a DIFFERENT folder is suffixed', async () => {
        let attempts = 0;
        const rec = recorder({
            createProject: async (row) => {
                attempts += 1;
                if (attempts < 3) throw Object.assign(new Error('project already exists'), { status: 400 });
                return row;
            },
            projects: () => [],
        });
        const saved = await saveProjectWithUniqueName(rec.host, { name: 'api', path: '/p/new' });
        expect(saved).toBe('api (3)');
    });

    test('an error that is not a collision is re-raised unchanged', async () => {
        const rec = recorder({
            createProject: async () => {
                throw new Error('disk is full');
            },
        });
        await expect(
            saveProjectWithUniqueName(rec.host, { name: 'api', path: '/p/api' }),
        ).rejects.toThrow('disk is full');
    });

    test('giving up throws a catalog KEY, and the key renders a sentence', async () => {
        const rec = recorder({
            createProject: async () => {
                throw new Error('project already exists');
            },
            projects: () => [],
        });
        let thrown: unknown = null;
        try {
            await saveProjectWithUniqueName(rec.host, { name: 'api', path: '/p/new' });
        } catch (error) {
            thrown = error;
        }
        expect((thrown as { cloudeKey?: string }).cloudeKey).toBe(
            'project.create.unique_name_failed',
        );
        expect(uniqueNameFailure(thrown, enT())).toBe(
            'could not find a unique name for this project',
        );
        expect(UNIQUE_NAME_ATTEMPTS).toBe(20);
    });
});

describe('opening a folder that already exists', () => {
    test('folder, then name, then provider, and only then a write', async () => {
        const rec = recorder({ folderPicker: () => async () => '/Users/me/code/api' });
        const m = modals({ name: [{ name: 'api', description: '' }] });
        expect(await openProjectFromFolderFlow(rec.host, m.openers, enT())).toBe('opened');

        const kinds = rec.calls.map(([kind]) => kind);
        expect(kinds.indexOf('chooseProvider')).toBeLessThan(kinds.indexOf('createProject'));
        expect(kinds).toContain('selectProject');
    });

    test('the default name is the folder basename, and the path is shown', async () => {
        const rec = recorder({ folderPicker: () => async () => '/Users/me/code/api' });
        const m = modals({ name: [null] });
        expect(await openProjectFromFolderFlow(rec.host, m.openers, enT())).toBe('cancelled_name');
        const request = m.asked[0]![1] as { defaultName: string; pathHint: string };
        expect(request.defaultName).toBe('api');
        expect(request.pathHint).toBe('/Users/me/code/api');
    });

    test('cancelling the picker writes nothing', async () => {
        const rec = recorder({ folderPicker: () => async () => null });
        const m = modals({ name: [{ name: 'api', description: '' }] });
        expect(await openProjectFromFolderFlow(rec.host, m.openers, enT())).toBe(
            'cancelled_folder',
        );
        expect(rec.calls).toEqual([]);
    });

    test('cancelling the provider writes nothing, so no orphan row is left', async () => {
        const rec = recorder({
            folderPicker: () => async () => '/Users/me/code/api',
            chooseProvider: async () => null,
        });
        const m = modals({ name: [{ name: 'api', description: '' }] });
        expect(await openProjectFromFolderFlow(rec.host, m.openers, enT())).toBe(
            'cancelled_provider',
        );
        expect(rec.calls.map(([kind]) => kind)).not.toContain('createProject');
    });

    test('a missing picker says so instead of doing nothing', async () => {
        const rec = recorder({ folderPicker: () => null });
        const m = modals({});
        expect(await openProjectFromFolderFlow(rec.host, m.openers, enT())).toBe('no_picker');
        expect(rec.errors[0]).toMatch(/folder picker is unavailable/);
    });

    test('it posts working_dir, which is the UNRESTRICTED field', async () => {
        const rec = recorder({ folderPicker: () => async () => '/anywhere/at/all' });
        const m = modals({ name: [{ name: 'api', description: '' }] });
        await openProjectFromFolderFlow(rec.host, m.openers, enT());
        const row = rec.calls.find(([kind]) => kind === 'createProject')?.[1] as { path: string };
        expect(row.path).toBe('/anywhere/at/all');
    });
});
