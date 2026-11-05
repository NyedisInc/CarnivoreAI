import type { CreatePayload, ProviderChoice } from './create-host';
import { accountFields, agentTypeFor } from './create-flow';

const REMOTE_ROOT_SCHEMES: readonly string[] = ['ssh://', 'peer://'];

export function isRemoteRoot(root: unknown): boolean {
    return typeof root === 'string' && REMOTE_ROOT_SCHEMES.some((scheme) => root.startsWith(scheme));
}

export function splitRemoteRoot(root: string): { hostKey: string; farPath: string } | null {
    const scheme = REMOTE_ROOT_SCHEMES.find((s) => root.startsWith(s));
    if (!scheme) return null;
    const rest = root.slice(scheme.length);
    const slash = rest.indexOf('/');
    if (slash <= 0) return null;
    return { hostKey: rest.slice(0, slash), farPath: rest.slice(slash) };
}

export function buildOpenProjectPayload(
    name: string,
    root: string,
    choice: ProviderChoice | null,
    dims: Record<string, unknown>,
): CreatePayload {
    const isLocal = !isRemoteRoot(root);
    const remote = splitRemoteRoot(root);
    const payload: CreatePayload = {
        working_dir: remote ? remote.farPath : root,
        auto_start_claude: true,
        copy_templates: false,
        project_name: name,
        label: typeof choice?.name === 'string' && choice.name.trim() ? choice.name.trim() : name,
        ...dims,
    };
    if (remote) payload.host_key = remote.hostKey;
    const resolved = agentTypeFor(null, choice);
    if (resolved) payload.agent_type = resolved;
    if (isLocal && choice?.model) payload.model = choice.model;
    if (isLocal && choice?.worktree) payload.worktree = choice.worktree;
    Object.assign(payload, accountFields(choice, isLocal));
    return payload;
}
