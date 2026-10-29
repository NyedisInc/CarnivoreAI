import { authFetch } from '../../../opscenter/api/auth.svelte';

export type Fetcher = typeof authFetch;

export interface McpTool { readonly name: string; readonly description: string; readonly write: boolean }

export interface McpStatus {
    readonly enabled: boolean;
    readonly endpoint: string;
    readonly gate_cross_session_actions: boolean;
    readonly tools: readonly McpTool[];
    readonly guide: string;
    readonly trusted_proxy_hosts?: readonly string[];
}

export interface McpToken {
    readonly id: string;
    readonly name: string;
    readonly scope: 'read' | 'write';
    readonly created_at: number;
    readonly last_used_at: number | null;
    readonly expires_at: number | null;
}

export async function fetchStatus(fetcher: Fetcher = authFetch): Promise<McpStatus> {
    const body = await fetcher<McpStatus>('/mcp-admin');
    if (!body || !Array.isArray(body.tools)) throw new Error('unexpected mcp response');
    return body;
}

export const fetchTokens = async (fetcher: Fetcher = authFetch): Promise<McpToken[]> =>
    (await fetcher<{ tokens?: McpToken[] }>('/mcp-admin/tokens'))?.tokens ?? [];

export const setEnabled = (enabled: boolean, fetcher: Fetcher = authFetch): Promise<{ enabled: boolean }> =>
    fetcher('/mcp-admin/settings', { method: 'PUT', body: JSON.stringify({ enabled }) });

/* app settings tools */
export interface AgentTools { readonly huddle: boolean; readonly swarm: boolean; readonly app_settings: boolean }

export async function fetchAgentTools(fetcher: Fetcher = authFetch): Promise<AgentTools> {
    const body = await fetcher<AgentTools>('/mcp-admin/agent-tools');
    if (typeof body?.huddle !== 'boolean' || typeof body?.swarm !== 'boolean' || typeof body?.app_settings !== 'boolean') {
        throw new Error('unexpected agent tools response');
    }
    return body;
}

export const setAgentTools = (change: Partial<AgentTools>, fetcher: Fetcher = authFetch): Promise<AgentTools> =>
    fetcher('/mcp-admin/agent-tools', { method: 'PUT', body: JSON.stringify(change) });

export const setTrustedProxies = (hosts: readonly string[], fetcher: Fetcher = authFetch): Promise<{ hosts: string[] }> =>
    fetcher('/mcp-admin/trusted-proxies', { method: 'PUT', body: JSON.stringify({ hosts }) });

export const mintToken = (name: string, scope: 'read' | 'write', days: number | null, fetcher: Fetcher = authFetch):
    Promise<{ token: McpToken; secret: string }> =>
    fetcher('/mcp-admin/tokens', { method: 'POST', body: JSON.stringify({ name, scope, expires_in_days: days }) });

export const revokeToken = (id: string, fetcher: Fetcher = authFetch): Promise<unknown> =>
    fetcher(`/mcp-admin/tokens/${encodeURIComponent(id)}`, { method: 'DELETE' });

export interface Snippets { readonly claude: string; readonly desktop: string; readonly ssh: string }

export function connectSnippets(endpoint: string, token = '<token>'): Snippets {
    const port = /:(\d+)\//.exec(`${endpoint}/`)?.[1] ?? '80';
    return {
        claude: `claude mcp add --transport http carnivore ${endpoint} --header "Authorization: Bearer ${token}"`,
        desktop: JSON.stringify({ mcpServers: { carnivore: { command: 'npx',
            args: ['-y', 'mcp-remote', endpoint, '--header', `Authorization: Bearer ${token}`] } } }),
        ssh: `ssh -N -L ${port}:127.0.0.1:${port} user@this-computer`,
    };
}

export async function copyText(text: string): Promise<void> {
    try {
        await navigator.clipboard.writeText(text);
        return;
    } catch {
    }
    const box = document.createElement('textarea');
    box.value = text;
    document.body.appendChild(box);
    box.select();
    const ok = document.execCommand('copy');
    box.remove();
    if (!ok) throw new Error('copy failed');
}

export type ToolSwitch = {
    readonly name: string;
    readonly description: string;
    readonly write: boolean;
    readonly enabled: boolean;
    readonly default_enabled: boolean;
    readonly family_hidden: boolean;
    readonly hidden_because: string;
    readonly sub?: string;
    readonly family?: string;
    readonly alias_of?: string;
    /* could not be read */
    readonly calls: number | null;
    readonly daily: readonly number[] | null;
};

export const DEPRECATED_GROUP = 'deprecated';

export interface ToolGroup { readonly group: string; readonly tools: readonly ToolSwitch[] }

export interface ToolSwitches {
    readonly groups: readonly ToolGroup[];
    readonly usage: { readonly since: string | null; readonly days: readonly string[] } | null;
}

function shaped(body: Partial<ToolSwitches> | undefined): ToolSwitches {
    if (!Array.isArray(body?.groups)) throw new Error('unexpected mcp tools response');
    return { groups: body.groups, usage: body.usage ?? null };
}

export async function fetchToolSwitches(fetcher: Fetcher = authFetch): Promise<ToolSwitches> {
    return shaped(await fetcher<ToolSwitches>('/mcp-admin/tools'));
}

export async function setToolSwitches(set: Readonly<Record<string, boolean>>, fetcher: Fetcher = authFetch): Promise<ToolSwitches> {
    return shaped(await fetcher<ToolSwitches>('/mcp-admin/tools', { method: 'PUT', body: JSON.stringify({ set }) }));
}

export async function resetToolUsage(fetcher: Fetcher = authFetch): Promise<ToolSwitches> {
    return shaped(await fetcher<ToolSwitches>('/mcp-admin/tools/usage/reset', { method: 'POST' }));
}
