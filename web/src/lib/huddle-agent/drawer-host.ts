import { ensurePanel } from '../mount';
import { agentPage } from '../../cplugs/huddle/agents/agent-page.svelte';
import AgentDrawer from './AgentDrawer.svelte';
import { openAgentDrawer } from './agent-drawer.svelte';

export const AGENT_DRAWER_CONTAINER = 'huddle-agent-drawer';

export function openAgentDrawerHost(): boolean {
  if (agentPage.id === null) return false;
  if (!ensurePanel(AGENT_DRAWER_CONTAINER, AgentDrawer, {})) return false;
  openAgentDrawer(agentPage.id);
  return true;
}
