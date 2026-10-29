import { hostWindow, hostDocument } from '../sessions/env';
import type { ProjectRow, RunningSessionRow } from '../sessions/types';

export interface SessionLike {
    label?: string | null;
    working_dir?: string | null;
    tmux_session?: string | null;
    [key: string]: unknown;
}

export interface AdoptResponse {
    session?: SessionLike | null;
    initial_scrollback_b64?: string | null;
    fifo_start_offset?: number | null;
    [key: string]: unknown;
}

export interface NavHost {
    adoptSession(tmuxName: string, attach: boolean): Promise<AdoptResponse>;
    getSession(
        id?: string | null,
        options?: Record<string, unknown>,
    ): Promise<SessionLike | { session?: SessionLike }>;
    detachSession(): Promise<unknown>;
    createSession(payload: Record<string, unknown>): Promise<SessionLike>;
    createProject(row: Record<string, unknown>): Promise<unknown>;
    chooseProvider(projectDefault?: string | null, accounts?: boolean): Promise<Record<string, unknown> | null>;
    terminalDims(): Record<string, unknown>;
    reloadProjects(): Promise<unknown>;
    reloadRunningSessions(): Promise<unknown>;
    runningSessions(): RunningSessionRow[];
    runningListingOk(): boolean;
    /* could not be read */
    runningListingReason(): string | null;
    announceSessionCreated(detail: Record<string, unknown>): void;
    rejectTarget(name: string): boolean;
    prepareTerminal(): Promise<{ cols: number; rows: number }>;
    returnToExistingTerminal(session: SessionLike): void;
    wait(ms: number): Promise<void>;
}

interface LegacyApi {
    adoptSession(name: string, attach: boolean): Promise<AdoptResponse>;
    getSession(id?: string | null, options?: Record<string, unknown>): Promise<SessionLike>;
    detachSession(): Promise<unknown>;
    createSession(payload: Record<string, unknown>): Promise<SessionLike>;
    createProject(row: Record<string, unknown>): Promise<unknown>;
}

const FRAME_TIMEOUT_MS = 250;

function twoFrames(): Promise<void> {
    return new Promise<void>((resolve) => {
        let done = false;
        const finish = () => {
            if (done) return;
            done = true;
            resolve();
        };
        setTimeout(finish, FRAME_TIMEOUT_MS);
        requestAnimationFrame(() => requestAnimationFrame(finish));
    });
}

/* could not */
async function browserPrepareTerminal(): Promise<{ cols: number; rows: number }> {
    const win = hostWindow() as unknown as Record<string, unknown> | undefined;
    const doc = hostDocument();
    const app = win?.App as { hideAllScreens?: () => void } | undefined;
    if (app && typeof app.hideAllScreens === 'function') {
        app.hideAllScreens();
    } else {
        doc?.querySelectorAll('.screen').forEach((s) => s.classList.remove('active'));
    }
    doc?.getElementById('terminal-screen')?.classList.add('active');

    const controller = win?.TerminalController as
        | {
              term?: { cols?: number; rows?: number } | null;
              init?: () => Promise<unknown>;
          }
        | undefined;
    if (controller && !controller.term && typeof controller.init === 'function') {
        await controller.init();
    }
    await twoFrames();
    try {
        const metrics = win?.TerminalMetrics as
            | { currentGrid?: () => { cols?: number; rows?: number } }
            | undefined;
        const grid =
            metrics && typeof metrics.currentGrid === 'function' ? metrics.currentGrid() : {};
        return { cols: grid.cols || 0, rows: grid.rows || 0 };
    } catch (error) {
        console.warn('CloudeWeb: rejoin pre-fit failed:', error);
        return { cols: 0, rows: 0 };
    }
}

export function browserNavHost(): NavHost {
    const win = () => hostWindow() as unknown as Record<string, unknown> | undefined;
    const api = (): LegacyApi => win()?.API as LegacyApi;
    const web = () =>
        win()?.CloudeWeb as
            | {
                  launchpad?: {
                      sessions?: {
                          runningSessions: RunningSessionRow[];
                          runningSessionsListing?: { ok?: boolean; reason?: string | null };
                      };
                      loadProjects?: (includeArchived?: boolean) => Promise<unknown>;
                      loadRunningSessions?: () => Promise<unknown>;
                      archivedProjectsVisible?: () => boolean;
                  };
              }
            | undefined;

    return {
        adoptSession: (name, attach) => api().adoptSession(name, attach),
        getSession: (id, options) => api().getSession(id ?? null, options),
        detachSession: () => api().detachSession(),
        createSession: (payload) => api().createSession(payload),
        createProject: (row) => api().createProject(row),
        chooseProvider: (projectDefault, accounts) => {
            const lp = win()?.Launchpad as
                | { showProviderModal?: (opts?: { projectDefault?: string | null; accounts?: boolean }) => Promise<Record<string, unknown> | null> }
                | undefined;
            return lp?.showProviderModal
                ? lp.showProviderModal({ projectDefault: projectDefault ?? null, accounts: accounts !== false })
                : Promise.resolve<Record<string, unknown> | null>(null);
        },
        terminalDims: () => {
            const metrics = win()?.TerminalMetrics as
                | { currentGrid?: () => Record<string, unknown> }
                | undefined;
            if (metrics && typeof metrics.currentGrid === 'function') {
                return metrics.currentGrid();
            }
            console.warn('CloudeWeb: TerminalMetrics unavailable for dims');
            return {};
        },
        reloadProjects: () => {
            const load = web()?.launchpad?.loadProjects;
            return load ? load() : Promise.resolve();
        },
        reloadRunningSessions: () => {
            const load = web()?.launchpad?.loadRunningSessions;
            return load ? load() : Promise.resolve();
        },
        runningSessions: () => web()?.launchpad?.sessions?.runningSessions ?? [],
        runningListingOk: () => web()?.launchpad?.sessions?.runningSessionsListing?.ok !== false,
        runningListingReason: () =>
            web()?.launchpad?.sessions?.runningSessionsListing?.reason ?? null,
        announceSessionCreated(detail) {
            const w = hostWindow() as unknown as Window | undefined;
            w?.dispatchEvent(new CustomEvent('session-created', { detail }));
        },
        rejectTarget(name) {
            const router = win()?.Router as { rejectTarget?: (n: string) => void } | undefined;
            if (router && typeof router.rejectTarget === 'function') {
                router.rejectTarget(name);
                return true;
            }
            return false;
        },
        prepareTerminal: browserPrepareTerminal,
        returnToExistingTerminal(session) {
            const app = win()?.App as
                | { returnToExistingTerminal?: (s: SessionLike) => void }
                | undefined;
            app?.returnToExistingTerminal?.(session);
        },
        wait: (ms) => new Promise<void>((resolve) => setTimeout(resolve, ms)),
    };
}

export type { ProjectRow };
