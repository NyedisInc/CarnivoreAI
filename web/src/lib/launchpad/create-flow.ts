/* could not */
import {
    PROJECT_CREATE_KEYS,
    nameRefusal,
} from '../../../../client/js/labels/project-create.js';
import type { Translate } from '../sessions/types';
import { reasonOf } from './failure-reason';
import type { CreateHost, CreatePayload, CreatedSession, HostChoice, ProviderChoice } from './create-host';
import { LOCAL_HOST_KEY } from './create-host';
import { remoteBrowseNote, remoteFolderSource } from './remote-folders';
import type { ModalOpeners } from './modals';
import { validateName } from './project-folder';
import { beginNav } from './nav-generation';

export type CreateOutcome =
    | 'created'
    | 'cancelled_provider'
    | 'cancelled_host'
    | 'cancelled_name'
    | 'cancelled_folder'
    | 'detached_and_retried'
    | 'failed';

export interface CreateResult {
    outcome: CreateOutcome;
    session: CreatedSession | null;
    payload: CreatePayload | null;
}

/* already running */
function isAlreadyRunning(error: unknown): boolean {
    const message = error instanceof Error ? error.message : String(error ?? '');
    return message.includes('already running');
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

/* active account */
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
        const details = await askForName(
            modals,
            host,
            t,
            title,
            t(PROJECT_CREATE_KEYS.wizardNext),
        );
        if (!details) return { ...refused, outcome: 'cancelled_name' };

        const isPeer = hostChoice.key.startsWith('peer-');
        const probe = isPeer ? host.remoteFolders(hostChoice.key, null) : null;
        const remote = isLocal
            ? null
            : {
                  label: hostChoice.label,
                  creates: isPeer,
                  ...(probe ? { browse: probe.then((a) => remoteBrowseNote(a, hostChoice.label, t)) } : {}),
              };
        const folder = await modals.folder({
            name: details.name,
            defaultParent: isLocal
                ? () => host.defaultParentDir()
                : probe
                  ? async () => {
                        const a = await probe;
                        return a.status === 'ok' ? a.path : null;
                    }
                  : async () => '~',
            openPicker: isLocal
                ? host.folderPicker()
                : probe
                  ? host.folderPicker(remoteFolderSource(host, hostChoice, t))
                  : null,
            remote,
            confirmLabel: t(PROJECT_CREATE_KEYS.wizardCreate),
        });
        if (!folder) return { ...refused, outcome: 'cancelled_folder' };
        const parent = folder.parent;
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
        const session = await host.createSession(payload);

        if (isLocal) {
            await persistProjectRow(host, {
                name: details.name,
                path: String(session.working_dir ?? ''),
                description: details.description || null,
            }, t);
        }
        // <path>
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

export async function createConsoleFlow(
    host: CreateHost,
    t: Translate,
    workingDir: string = '~',
): Promise<CreateResult> {
    const sessionName = `console-${Date.now().toString(36)}`;
    const nav = beginNav('console');
    try {
        host.updateStatus(t(PROJECT_CREATE_KEYS.createConsoleStatus));
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
        host.announceSessionCreated(session, nav);
        return { outcome: 'created', session, payload };
    } catch (error) {
        console.error('CloudeWeb: failed to create console session:', error);
        if (isAlreadyRunning(error)) {
            host.detachAndCreateNew('shell');
            return { outcome: 'detached_and_retried', session: null, payload: null };
        }
        host.showError(t(PROJECT_CREATE_KEYS.createFailed, { reason: reasonOf(error, t) }));
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

/* already exists the project row */
async function persistProjectRow(
    host: CreateHost,
    row: { name: string; path: string; description?: string | null },
    t: Translate,
    showRefusal: boolean = true,
): Promise<void> {
    try {
        await host.createProject(row);
    } catch (error) {
        const body = (error as { body?: { code?: unknown } } | null)?.body;
        if (body?.code === 'project_root_refused') {
            if (showRefusal) host.showError(t(PROJECT_CREATE_KEYS.rootRefused));
            return;
        }
        const message = error instanceof Error ? error.message : String(error ?? '');
        if (!message.includes('already exists')) {
            console.error('CloudeWeb: failed to save project:', error);
        }
    }
}

/* something else */
async function refreshProjects(host: CreateHost): Promise<void> {
    try {
        await host.reloadProjects();
    } catch (error) {
        console.error('CloudeWeb: failed to refresh projects after session create:', error);
    }
}
