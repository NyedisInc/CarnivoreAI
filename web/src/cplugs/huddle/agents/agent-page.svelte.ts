import { openCplugPage } from '../../sdk';

export type AgentDrawerTab = 'chat' | 'tasks';

export const AGENT_PAGE = 'huddle.agent';
export const AGENT_HASH = '#agent';

export const agentPage = $state<{ id: number | null; node: string | null }>({ id: null, node: null });

export function filterKey(): string | null {
  return agentPage.node ?? (agentPage.id === null ? null : `agent:${agentPage.id}`);
}

export function toggleFilter(key: string, agentId: number | null): void {
  const same = filterKey() === key;
  agentPage.id = same || agentId === null ? null : agentId;
  agentPage.node = same || agentId !== null ? null : key;
}

export function agentIdFromHash(hash: string | null | undefined): number | null {
  const found = /^#?agent\/([1-9][0-9]{0,14})(?:[/?].*)?$/.exec((hash ?? '').trim());
  return found ? Number(found[1]) : null;
}

export function openAgentPage(id: number): boolean {
  agentPage.id = id;
  return openCplugPage(AGENT_PAGE);
}
