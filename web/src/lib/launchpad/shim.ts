/* <script */
import { derivedDisplayName } from '../sessions/session-label';
import type { ProjectRow } from '../sessions/types';
import { sessionStore } from '../sessions/store.svelte';
import { hostWindow } from '../sessions/env';
import type { SessionRecord } from '../sessions/types';

export interface LaunchpadShim {
    readonly launchpadScreen: HTMLElement | null;
    init(): void;
    loadProjects(): Promise<void>;
    loadRunningSessions(): Promise<void>;
    openProjectByName(name: string): Promise<void>;
    _deriveRunningSessionDisplayName(tmuxName: string | null): string;
    readonly sessionRecords: SessionRecord[];
    showError(message: string): void;
    /* nothing at all */
    selectProject(project: ProjectRow, choice?: Record<string, unknown> | null): Promise<void>;
    showProviderModal?: (opts?: { projectDefault?: string | null; accounts?: boolean; goLabel?: string | null }) => Promise<Record<string, unknown> | null>;
}

export interface ShimBackends {
    launchpadScreen(): HTMLElement | null;
    init(): void;
    loadProjects(): Promise<void>;
    loadRunningSessions(): Promise<void>;
    openProjectByName(name: string): Promise<void>;
    showError(message: string): void;
    selectProject(project: ProjectRow, choice?: Record<string, unknown> | null): Promise<void>;
}

export function publishLaunchpadShim(backends: ShimBackends): LaunchpadShim {
    const win = hostWindow() as unknown as Record<string, unknown> | undefined;
    const existing = (win?.Launchpad as Partial<LaunchpadShim> | undefined) || {};
    const shim = existing as LaunchpadShim;

    Object.defineProperty(shim, 'launchpadScreen', {
        configurable: true,
        enumerable: true,
        get: () => backends.launchpadScreen(),
    });
    Object.defineProperty(shim, 'sessionRecords', {
        configurable: true,
        enumerable: true,
        get: () => sessionStore.sessionRecords,
    });
    Object.assign(shim, {
        init: () => backends.init(),
        loadProjects: () => backends.loadProjects(),
        loadRunningSessions: () => backends.loadRunningSessions(),
        openProjectByName: (name: string) => backends.openProjectByName(name),
        showError: (message: string) => backends.showError(message),
        selectProject: (project: ProjectRow, choice?: Record<string, unknown> | null) =>
            backends.selectProject(project, choice),
        _deriveRunningSessionDisplayName: (tmuxName: string | null) =>
            derivedDisplayName(tmuxName),
    });

    if (win) win.Launchpad = shim;
    return shim;
}

export const SHIM_MEMBERS: readonly string[] = [
    'launchpadScreen',
    'init',
    'loadProjects',
    'loadRunningSessions',
    'openProjectByName',
    'showError',
    'selectProject',
    '_deriveRunningSessionDisplayName',
    'sessionRecords',
    'showProviderModal',
];
