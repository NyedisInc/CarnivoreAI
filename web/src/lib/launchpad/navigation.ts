/* CANNOT DETERMINE */
import { HOME_KEYS, failureReason } from '../../../../client/js/labels/home-screen.js';
import { findRunningSessionBySlug } from './deep-link';
import { showError, updateStatus, explainRefusedProject } from './status-report';
import { accountFields } from './create-flow';
import { beginNav, currentNav, keepNav, withNav } from './nav-generation';
import type { NavHost, SessionLike } from './nav-host';
import type { ProjectRow, RunningSessionRow } from '../sessions/types';
import type { Translate } from './recent';

export const DEEP_LINK_ATTEMPTS = 5;

export const DEEP_LINK_BACKOFF_MS = 300;

export const DETACH_SETTLE_MS = 0;

let resolvingDeepLink = false;

export function isResolvingDeepLink(): boolean {
    return resolvingDeepLink;
}

export async function returnToActiveSession(
    sessionId: string | null,
    host: NavHost,
    t: Translate,
): Promise<void> {
    const nav = beginNav('session:' + String(sessionId ?? ''));
    try {
        const { cols, rows } = await host.prepareTerminal();
        const info = await host.getSession(sessionId, {
            includeScrollback: true,
            parallelHistory: true,
            scrollbackLines: (globalThis as { CloudeTerminal?: { SCROLLBACK_ROWS?: number } }).CloudeTerminal?.SCROLLBACK_ROWS,
            cols,
            rows,
        });
        if (!keepNav(nav, 'launcher rejoin')) return;
        if (info) host.returnToExistingTerminal(info as SessionLike);
    } catch (error) {
        showError(t(HOME_KEYS.returnFailed, { reason: failureReason(error, t) }), t);
    }
}

export async function attachRunningSession(
    tmuxName: string,
    host: NavHost,
    t: Translate,
): Promise<void> {
    const nav = beginNav('attach:' + tmuxName);
    try {
        const response = await host.adoptSession(tmuxName, true);
        const session = (response.session || response) as SessionLike;
        if (session && !session.label) {
            const known = host.runningSessions().find((row) => row.name === tmuxName);
            if (known && known.label) session.label = known.label;
        }
        const initialScrollbackB64 = response.initial_scrollback_b64 || '';
        const fifoStartOffset =
            typeof response.fifo_start_offset === 'number' ? response.fifo_start_offset : null;

        if (session && session.working_dir) {
            try {
                // the project row
                const rawName = String(session.tmux_session || tmuxName);
                await host.createProject({
                    name: rawName.replace(/^cloude_/, ''),
                    path: session.working_dir,
                    description: '',
                });
            } catch (error) {
                const message = error instanceof Error ? error.message : String(error ?? '');
                if (!message.includes('already exists')) {
                    console.error('CloudeWeb: failed to save the adopted project:', error);
                }
            }
            try {
                await host.reloadProjects();
            } catch (error) {
                console.error('CloudeWeb: failed to refresh projects after adopt:', error);
            }
        }

        host.announceSessionCreated(withNav({
            session,
            initialScrollbackB64,
            fifoStartOffset,
            adopted: true,
        }, nav));
    } catch (error) {
        showError(t(HOME_KEYS.attachFailed, { reason: failureReason(error, t) }), t);
    }
}

/* CANNOT DETERMINE */
export async function resolveDeepLink(
    target: string,
    host: NavHost,
): Promise<RunningSessionRow | null> {
    for (let attempt = 0; attempt < DEEP_LINK_ATTEMPTS; attempt += 1) {
        try {
            await host.reloadRunningSessions();
        } catch (error) {
            console.warn('CloudeWeb: session refresh during deep-link resolve failed:', error);
        }
        const match = findRunningSessionBySlug(host.runningSessions(), target);
        if (match) return match;
        if (host.runningListingOk()) return null;
        console.warn(
            'CloudeWeb: session listing unavailable during deep-link resolve ' +
                `(attempt ${attempt + 1}), reason=${host.runningListingReason() || 'unknown'}`,
        );
        await host.wait(DEEP_LINK_BACKOFF_MS);
    }
    return null;
}

export async function openProjectByName(
    name: string,
    host: NavHost,
    t: Translate,
): Promise<void> {
    resolvingDeepLink = true;
    const deepLinkNav = currentNav();
    try {
        const session = await resolveDeepLink(name, host);
        if (!keepNav(deepLinkNav, 'deep-link resolve')) return;
        if (session) {
            if (session.is_active) {
                await returnToActiveSession(session.session_id || null, host, t);
                return;
            }
            console.warn('CloudeWeb: deep-link target is not live, so it is not adopted:', name);
        } else {
            console.warn('CloudeWeb: deep-link target not found among live sessions:', name);
        }
        if (!host.rejectTarget(name)) {
            showError(t(HOME_KEYS.sessionNotFound, { name }), t);
        }
    } finally {
        resolvingDeepLink = false;
    }
}

export async function selectProject(
    project: ProjectRow,
    host: NavHost,
    t: Translate,
    providerChoice: Record<string, unknown> | null | undefined = undefined,
): Promise<void> {
    const name = String(project?.name ?? '');
    const nav = beginNav('project:' + name);
    if (resolvingDeepLink) {
        const error = new Error(t(HOME_KEYS.deepLinkRefusesCreate, { name }));
        console.error('CloudeWeb: BLOCKED create-session during deep-link resolution:', error);
        host.rejectTarget(name);
        throw error;
    }

    try {
        let choice = providerChoice;
        if (choice === undefined) {
            choice = await host.chooseProvider((project?.default_launch_profile as string | null | undefined) ?? null, !String(project?.path).startsWith('ssh://'));
            if (!choice) return;
        }
        updateStatus(t(HOME_KEYS.statusOpening, { name }));

        const payload: Record<string, unknown> = {
            working_dir: project.path,
            auto_start_claude: true,
            copy_templates: false,
            project_name: name,
            label: name,
            ...host.terminalDims(),
        };
        if (choice?.model) payload.model = choice.model;
        Object.assign(payload, accountFields(choice ?? null, !String(project?.path).startsWith('ssh://')));
        if (choice?.wrapperId) payload.agent_type = choice.wrapperId;
        else if (choice?.agentType) payload.agent_type = choice.agentType;

        const session = await host.createSession(payload);
        host.announceSessionCreated(withNav({ session, project }, nav));
    } catch (error) {
        console.error('CloudeWeb: failed to open project:', error);
        const message = error instanceof Error ? error.message : String(error ?? '');
        if (message.includes('already running')) {
            await detachAndOpenProject(project, host, t);
        } else {
            showError(t(HOME_KEYS.openFailed, { name, reason: failureReason(error, t) }), t);
        }
    }
}

export async function detachAndOpenProject(
    project: ProjectRow,
    host: NavHost,
    t: Translate,
): Promise<void> {
    try {
        updateStatus(t(HOME_KEYS.statusDetaching));
        await host.detachSession();
        await host.wait(DETACH_SETTLE_MS);
    } catch (error) {
        console.error('CloudeWeb: failed to detach session:', error);
        showError(t(HOME_KEYS.detachFailed, { reason: failureReason(error, t) }), t);
        return;
    }
    try {
        await selectProject(project, host, t);
    } catch (error) {
        console.error('CloudeWeb: failed to open the project after detach:', error);
        showError(
            t(HOME_KEYS.openFailed, {
                name: String(project?.name ?? ''),
                reason: failureReason(error, t),
            }),
            t,
        );
    }
}

export async function detachAndCreateNew(
    agentType: string | null,
    host: NavHost,
    t: Translate,
    createNew: (agentType: string | null) => Promise<unknown> | unknown,
): Promise<void> {
    try {
        updateStatus(t(HOME_KEYS.statusDetaching));
        await host.detachSession();
        await host.wait(DETACH_SETTLE_MS);
    } catch (error) {
        console.error('CloudeWeb: failed to detach session:', error);
        showError(t(HOME_KEYS.detachFailed, { reason: failureReason(error, t) }), t);
        return;
    }
    try {
        await createNew(agentType || null);
    } catch (error) {
        console.error('CloudeWeb: failed to create a session after detach:', error);
    }
}

export async function connectToExistingSession(host: NavHost, t: Translate): Promise<void> {
    const nav = beginNav('existing');
    try {
        updateStatus(t(HOME_KEYS.statusConnecting));
        const data = await host.getSession();
        const session = ((data as { session?: SessionLike }).session || data) as SessionLike;
        host.announceSessionCreated(withNav({ session }, nav));
    } catch (error) {
        console.error('CloudeWeb: failed to get the existing session:', error);
        showError(t(HOME_KEYS.connectFailed, { reason: failureReason(error, t) }), t);
    }
}

export { explainRefusedProject };
