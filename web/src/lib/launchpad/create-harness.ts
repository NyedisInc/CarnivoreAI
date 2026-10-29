import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { CreateHost, CreatePayload, CreatedSession, HostChoice, ProviderChoice } from './create-host';
import type { ModalOpeners } from './modals';
import type { ChoiceOptions, ClonedProject, EditResult, FolderChoice } from './modal-types';

/** A real translator over the shipped en catalog. */
export function enT(): (key: string, params?: Record<string, unknown> | null) => string {
    const i18n = createI18n({ locale: 'en' }) as {
        t(key: string, params?: Record<string, unknown> | null): string;
    };
    return (key, params) => i18n.t(key, params);
}

export interface Recorder {
    host: CreateHost;
    calls: Array<[string, unknown]>;
    payloads: CreatePayload[];
    errors: string[];
}

export function recorder(overrides: Partial<CreateHost> = {}): Recorder {
    const calls: Array<[string, unknown]> = [];
    const payloads: CreatePayload[] = [];
    const errors: string[] = [];
    const base: CreateHost = {
        chooseProvider: async () => {
            calls.push(['chooseProvider', null]);
            return {} as ProviderChoice;
        },
        listHosts: async () => {
            calls.push(['listHosts', null]);
            return [];
        },
        createSession: async (payload) => {
            calls.push(['createSession', payload]);
            payloads.push(payload);
            return { working_dir: '/Users/me/Development/My App' } as CreatedSession;
        },
        createProject: async (row) => {
            calls.push(['createProject', row]);
            return row;
        },
        checkProjectRoot: async (path) => {
            calls.push(['checkProjectRoot', path]);
            return { ok: true };
        },
        updateProject: async (name, fields) => {
            calls.push(['updateProject', { name, fields }]);
            return null;
        },
        archiveProject: async (name) => {
            calls.push(['archiveProject', name]);
            return null;
        },
        unarchiveProject: async (name) => {
            calls.push(['unarchiveProject', name]);
            return null;
        },
        cloneProject: async (payload) => {
            calls.push(['cloneProject', payload]);
            return { name: 'repo', path: '/p/repo' } as ClonedProject;
        },
        defaultParentDir: async () => '/Users/me/Development',
        folderPicker: () => null,
        remoteFolders: async () => ({ status: 'unavailable', reason: 'peer_too_old' }),
        reloadProjects: async () => {
            calls.push(['reloadProjects', null]);
            return null;
        },
        projects: () => [],
        projectsListingOk: () => true,
        presenceFor: () => null,
        selectProject: async (project, choice) => {
            calls.push(['selectProject', { project, choice }]);
            return null;
        },
        detachAndCreateNew: (agentType) => {
            calls.push(['detachAndCreateNew', agentType]);
            return null;
        },
        terminalDims: () => ({ cols: 132, rows: 40 }),
        updateStatus: (message) => calls.push(['updateStatus', message]),
        showError: (message) => {
            calls.push(['showError', message]);
            errors.push(message);
        },
        confirm: async () => {
            calls.push(['confirm', null]);
            return true;
        },
        announceSessionCreated: (session) => calls.push(['announceSessionCreated', session]),
    };
    return { host: { ...base, ...overrides }, calls, payloads, errors };
}

export function modals(script: {
    name?: Array<{ name: string; description: string } | null>;
    folder?: FolderChoice | null;
    choice?: string | null;
    edit?: EditResult | null;
    clone?: ClonedProject | null;
}): { openers: ModalOpeners; asked: Array<[string, unknown]> } {
    const asked: Array<[string, unknown]> = [];
    const names = [...(script.name ?? [])];
    return {
        asked,
        openers: {
            async name(request) {
                asked.push(['name', request]);
                return names.length ? (names.shift() ?? null) : null;
            },
            async folder(request) {
                asked.push(['folder', request]);
                return script.folder ?? null;
            },
            async choice(options: ChoiceOptions) {
                asked.push(['choice', options]);
                return script.choice ?? null;
            },
            async edit(request) {
                asked.push(['edit', request]);
                return script.edit ?? null;
            },
            async clone(request) {
                asked.push(['clone', request]);
                return script.clone ?? null;
            },
        },
    };
}


export const GOOD_NAME = { name: 'My App', description: 'a thing' };

export const GOOD_FOLDER: FolderChoice = {
    parent: '/Users/me/Development',
    path: '/Users/me/Development',
};
