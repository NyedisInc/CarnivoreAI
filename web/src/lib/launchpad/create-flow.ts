import {
    PROJECT_CREATE_KEYS,
    nameRefusal,
} from '../../../../client/js/labels/project-create.js';
import { NEW_PROJECT_KEYS } from '../../../../client/js/labels/new-project.js';
import type { Translate } from '../sessions/types';
import { reasonOf } from './failure-reason';
import type { CreateHost, CreatePayload, CreatedSession, HostChoice, ProviderChoice } from './create-host';
import { LOCAL_HOST_KEY } from './create-host';
import { remoteBrowseNote, remoteFolderSource } from './remote-folders';
import type { ModalOpeners } from './modals';
import type { NewProjectChoice } from './modal-types';
import { refusedWith } from './refusal-shape';
import { validateName } from './project-folder';
import { beginNav } from './nav-generation';

export type CreateOutcome =
    | 'created'
    | 'cancelled_provider'
    | 'cancelled_host'
    | 'cancelled_name'
    | 'cancelled_folder'
    | 'cancelled_form'
    | 'detached_and_retried'
    | 'failed';

export interface CreateResult {
    outcome: CreateOutcome;
    session: CreatedSession | null;
    payload: CreatePayload | null;
}

function isAlreadyRunning(error: unknown): boolean {
    return refusedWith(error, { code: 'session_already_running', phrase: 'already running' });
}

export async function askForName(
    modals: ModalOpeners,
    host: CreateHost,
    t: Translate,
    title: string,
    confirmLabel: string,
): Promise<{ name: string; description: string } | null> {
    let prefill = '';
    for (;;) {
        const details = await modals.name({ title, confirmLabel, defaultName: prefill });
        if (!details) return null;
        const verdict = validateName(details.name);
        if (verdict.ok) return details;
        const sentence = nameRefusal(verdict, t);
        if (sentence) host.showError(sentence);
        prefill = details.name;
    }
}

export async function askForNewProject(
    modals: ModalOpeners,
    host: CreateHost,
    t: Translate,
    title: string,
    confirmLabel: string,
): Promise<NewProjectChoice | null> {
    let prefill = '';
    for (;;) {
        const picked = await modals.newProject({ title, confirmLabel, defaultName: prefill });
        if (!picked) return null;
        const verdict = validateName(picked.name);
        if (verdict.ok) return picked;
        const sentence = nameRefusal(verdict, t);
        if (sentence) host.showError(sentence);
        prefill = picked.name;
    }
}

export function hostReasonKey(h: HostChoice): string {
    if (h.probe_detail === 'peer_not_connected') return PROJECT_CREATE_KEYS.hostPeerOffline;
    if (h.probe_detail === 'peer_refuses_hosting') return PROJECT_CREATE_KEYS.hostPeerRefuses;
    return PROJECT_CREATE_KEYS.hostNotProbed;
}

function sameWord(a: string | null, b: string): boolean {
    return a !== null && a.trim().toLowerCase() === b.trim().toLowerCase();
}

export async function chooseHost(
    host: CreateHost,
    modals: ModalOpeners,
    t: Translate,
): Promise<HostChoice | null> {
    const hosts = await host.listHosts();
    const remotes = hosts.filter((h) => !h.local);
    if (remotes.length === 0) {
        const local = hosts.find((h) => h.local);
        return local ?? { key: LOCAL_HOST_KEY, label: '', local: true, ssh_target: null, ssh_port: null, socket: null, enabled: true, session_count: 0, probe_state: 'never', probe_detail: null, probed_at: null, tmux_path: null, tmux_version: null, login_path: null, agent_paths: null, login_shell: null, machine_id: null, remote_carnivore: null, created_at: '', updated_at: '' };
    }
    const byKey = new Map(hosts.map((h) => [h.key, h] as const));
    const picked = await modals.choice({
        title: t(PROJECT_CREATE_KEYS.hostTitle),
        items: hosts.map((h) => ({
            key: h.key,
            label: h.label,
            sub: h.local || sameWord(h.ssh_target, h.label) ? null : h.ssh_target,
            disabled: !h.local && (!h.enabled || h.probe_state !== 'ok'),
            reason: !h.local && (!h.enabled || h.probe_state !== 'ok')
                ? t(hostReasonKey(h))
                : null,
        })),
    });
    if (!picked) return null;
    return byKey.get(picked) ?? null;
}

export function agentTypeFor(
    agentType: string | null,
    choice: ProviderChoice | null,
): string | null {
    if (agentType) return agentType;
    if (choice?.wrapperId) return String(choice.wrapperId);
    if (choice?.agentType) return String(choice.agentType);
    return null;
}

export function accountFields(choice: ProviderChoice | null, isLocal: boolean): { account_id?: string; account_pinned?: true } {
    if (!isLocal || !choice?.accountId) return {};
    return choice.pinAccount ? { account_id: choice.accountId, account_pinned: true } : { account_id: choice.accountId };
}

export function buildCreatePayload(
    name: string,
    parent: string,
    agentType: string | null,
    choice: ProviderChoice | null,
    dims: Record<string, unknown>,
    hostKey: string = LOCAL_HOST_KEY,
): CreatePayload {
    const isLocal = hostKey === LOCAL_HOST_KEY;
    const payload: CreatePayload = {
        auto_start_claude: true,
        copy_templates: isLocal,
        project_name: name,
        label: name,
        ...dims,
    };
    const isPeer = hostKey.startsWith('peer-');
    if (isLocal || isPeer) {
        payload.project_parent_dir = parent;
        if (isPeer) payload.host_key = hostKey;
    } else {
        payload.host_key = hostKey;
        if (parent) payload.working_dir = parent;
    }
    const resolved = agentTypeFor(agentType, choice);
    if (resolved) payload.agent_type = resolved;
    if (!isLocal && resolved && choice?.farLauncher === true && !agentType) payload.agent_type_is_far = true;
    if (isLocal && choice?.model) payload.model = choice.model;
    if (isLocal && choice?.story) payload.story_ref = choice.story;
    Object.assign(payload, accountFields(choice, isLocal));
    return payload;
}

/* the project row */
export async function createProjectFlow(
    host: CreateHost,
    modals: ModalOpeners,
    t: Translate,
    agentType: string | null = null,
): Promise<CreateResult> {
    const refused: CreateResult = { outcome: 'failed', session: null, payload: null };
    const nav = beginNav('create');
    try {
        const hostChoice = await chooseHost(host, modals, t);
        if (!hostChoice) return { ...refused, outcome: 'cancelled_host' };
        const isLocal = hostChoice.key === LOCAL_HOST_KEY;

        const choice = await host.chooseProvider(
            isLocal ? null : { key: hostChoice.key, label: hostChoice.label },
            t(PROJECT_CREATE_KEYS.wizardNext),
        );
        if (!choice) return { ...refused, outcome: 'cancelled_provider' };

        const title = agentType
            ? t(PROJECT_CREATE_KEYS.nameTitleForAgent, { agent: agentType })
            : t(PROJECT_CREATE_KEYS.nameTitle);
        const isPeer = hostChoice.key.startsWith('peer-');
        let details: { name: string; description: string };
        let parent: string;
        let companyId: number | null = null;
        if (isLocal) {
            const picked = await askForNewProject(
                modals,
                host,
                t,
                agentType ? title : t(NEW_PROJECT_KEYS.title),
                t(PROJECT_CREATE_KEYS.wizardCreate),
            );
            if (!picked) return { ...refused, outcome: 'cancelled_form' };
            details = { name: picked.name, description: '' };
            parent = picked.folder;
            companyId = picked.companyId;
        } else {
            const named = await askForName(modals, host, t, title, t(PROJECT_CREATE_KEYS.wizardNext));
            if (!named) return { ...refused, outcome: 'cancelled_name' };
            details = named;
            const probe = isPeer ? host.remoteFolders(hostChoice.key, null) : null;
            const remote = {
                label: hostChoice.label,
                creates: isPeer,
                ...(probe ? { browse: probe.then((a) => remoteBrowseNote(a, hostChoice.label, t)) } : {}),
            };
            const folder = await modals.folder({
                name: details.name,
                defaultParent: probe
                    ? async () => {
                          const a = await probe;
                          return a.status === 'ok' ? a.path : null;
                      }
                    : async () => '~',
                openPicker: probe ? host.folderPicker(remoteFolderSource(host, hostChoice, t)) : null,
                remote,
                confirmLabel: t(PROJECT_CREATE_KEYS.wizardCreate),
            });
            if (!folder) return { ...refused, outcome: 'cancelled_folder' };
            parent = folder.parent;
        }
        if (isLocal && !(await folderAllowed(host, parent, t))) return { ...refused, outcome: 'failed' };

        host.updateStatus(
            agentType
                ? t(PROJECT_CREATE_KEYS.createStatusForAgent, { agent: agentType })
                : t(PROJECT_CREATE_KEYS.createStatus),
        );

        const payload = buildCreatePayload(
            details.name,
            parent,
            agentType,
            choice,
            host.terminalDims(),
            hostChoice.key,
        );
        let session: CreatedSession;
        try {
            session = await host.createSession(payload);
        } catch (createErr) {
            // the project folder
            // the project row
            const errObj = createErr as { status?: number; body?: { code?: unknown } } | null;
            const code = typeof errObj?.body?.code === 'string' ? errObj.body.code : '';
            const isLaunchCrash =
                errObj?.status === 502 ||
                code === 'agent_exited' ||
                code === 'agent_not_installed' ||
                code === 'agent_not_installed_claude' ||
                code === 'agent_not_installed_codex' ||
                code === 'tmux_missing' ||
                code === 'session_launch_failed';
            if (isLocal && parent && isLaunchCrash) {
                await persistProjectRow(host, {
                    name: details.name,
                    path: parent,
                    description: details.description || null,
                    ...(companyId !== null ? { company_id: companyId } : {}),
                }, t);
                await refreshProjects(host);
            }
            throw createErr;
        }

        if (isLocal) {
            await persistProjectRow(host, {
                name: details.name,
                path: String(session.working_dir ?? ''),
                description: details.description || null,
                ...(companyId !== null ? { company_id: companyId } : {}),
            }, t);
        }
        host.announceSessionCreated(session, nav);
        await refreshProjects(host);
        return { outcome: 'created', session, payload };
    } catch (error) {
        console.error('CloudeWeb: failed to create session:', error);
        if (isAlreadyRunning(error)) {
            host.detachAndCreateNew(agentType);
            return { ...refused, outcome: 'detached_and_retried' };
        }
        host.showError(t(PROJECT_CREATE_KEYS.createFailed, { reason: reasonOf(error, t) }));
        return refused;
    }
}

export interface ConsoleFlowOptions {
    sessionName?: string;
    quiet?: boolean;
}

export async function createConsoleFlow(
    host: CreateHost,
    t: Translate,
    workingDir: string = '~',
    options: ConsoleFlowOptions = {},
): Promise<CreateResult> {
    const sessionName = options.sessionName ?? `console-${Date.now().toString(36)}`;
    const quiet = options.quiet === true;
    const nav = quiet ? undefined : beginNav('console');
    try {
        if (!quiet) host.updateStatus(t(PROJECT_CREATE_KEYS.createConsoleStatus));
        const payload: CreatePayload = {
            auto_start_claude: true,
            copy_templates: false,
            project_name: sessionName,
            working_dir: workingDir || '~',
            agent_type: 'shell',
            ...host.terminalDims(),
        };
        const session = await host.createSession(payload);
        await persistProjectRow(host, {
            name: sessionName,
            path: String(session.working_dir ?? ''),
        }, t, false);
        await refreshProjects(host);
        if (!quiet) host.announceSessionCreated(session, nav);
        return { outcome: 'created', session, payload };
    } catch (error) {
        console.error('CloudeWeb: failed to create console session:', error);
        if (!quiet && isAlreadyRunning(error)) {
            host.detachAndCreateNew('shell');
            return { outcome: 'detached_and_retried', session: null, payload: null };
        }
        if (!quiet) host.showError(t(PROJECT_CREATE_KEYS.createFailed, { reason: reasonOf(error, t) }));
        return { outcome: 'failed', session: null, payload: null };
    }
}

/* the project row */
async function folderAllowed(host: CreateHost, folder: string, t: Translate): Promise<boolean> {
    try {
        await host.checkProjectRoot(folder);
    } catch (error) {
        const body = (error as { body?: { code?: unknown } } | null)?.body;
        if (body?.code === 'project_root_refused') {
            host.showError(t(PROJECT_CREATE_KEYS.rootRefused));
            return false;
        }
        console.error('CloudeWeb: project folder check failed:', error);
    }
    return true;
}

async function persistProjectRow(
    host: CreateHost,
    row: { name: string; path: string; description?: string | null; company_id?: number },
    t: Translate,
    showRefusal: boolean = true,
): Promise<void> {
    try {
        await host.createProject(row);
        return;
    } catch (error) {
        const body = (error as { body?: { code?: unknown; existing_project?: { name?: unknown } } } | null)?.body;
        if (body?.code === 'project_root_refused') {
            if (showRefusal) host.showError(t(PROJECT_CREATE_KEYS.rootRefused));
            return;
        }
        const collided = refusedWith(error, { code: 'project_name_taken', phrase: 'already exists' });
        if (!collided) console.error('CloudeWeb: failed to save project:', error);
        const existing = typeof body?.existing_project?.name === 'string' ? body.existing_project.name : row.name;
        if (row.company_id !== undefined && (collided || body?.existing_project)) {
            await fileUnderCompany(host, existing, row.company_id, t);
        }
    }
}

async function fileUnderCompany(host: CreateHost, projectName: string, companyId: number, t: Translate): Promise<void> {
    try {
        await host.setProjectCompany(projectName, companyId);
    } catch (error) {
        console.error('CloudeWeb: failed to file the project under its company:', error);
        host.showError(t(PROJECT_CREATE_KEYS.createFailed, { reason: reasonOf(error, t) }));
    }
}

async function refreshProjects(host: CreateHost): Promise<void> {
    try {
        await host.reloadProjects();
    } catch (error) {
        console.error('CloudeWeb: failed to refresh projects after session create:', error);
    }
}
