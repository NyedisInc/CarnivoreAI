import { authFetch } from '../../opscenter/api/auth.svelte';

export interface AgentCheck {
    readonly claude: boolean;
    readonly codex: boolean;
}

export type AgentFetcher = typeof authFetch;

export function parseAgentCheck(body: unknown): AgentCheck | null {
    if (!body || typeof body !== 'object') return null;
    const report = body as { checks?: unknown; agents?: { codex?: { found?: unknown } } };
    if (!Array.isArray(report.checks)) return null;
    const claude = report.checks.find((c) => (c as { name?: unknown } | null)?.name === 'claude_cli') as { status?: unknown } | undefined;
    if (!claude) return null;
    return { claude: claude.status === 'PASS', codex: report.agents?.codex?.found === true };
}

export async function fetchAgentCheck(fetcher: AgentFetcher = authFetch): Promise<AgentCheck | null> {
    try {
        return parseAgentCheck(await fetcher<unknown>('/self-check', { cache: 'no-store' }));
    } catch {
        return null;
    }
}
