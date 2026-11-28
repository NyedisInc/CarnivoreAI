import { authFetch, floorSource, openSession } from '../../sdk';
import { swarmRoster, refreshRoster } from './agent-roster.svelte';

const WAKE_WAIT_MS = 30_000;
const WAKE_STEP_MS = 1_000;

function liveSession(agentId: number): { sessionId: string; name: string } | null {
  const agent = swarmRoster.agents.find((a) => a.id === agentId);
  if (!agent) return null;
  const row = agent.session_row_id == null ? undefined : floorSource().sessions.find((s) => s.sessionRowId === agent.session_row_id);
  const sessionId = agent.session_id ?? row?.sessionId ?? null;
  const name = agent.tmux_session ?? row?.name ?? null;
  return sessionId && name ? { sessionId, name } : null;
}

async function wakeForTerminal(agentId: number): Promise<{ sessionId: string; name: string } | null> {
  await authFetch(`/swarm/agents/${agentId}/wake`, { method: 'POST' });
  for (let waited = 0; ; waited += WAKE_STEP_MS) {
    await refreshRoster();
    const found = liveSession(agentId);
    if (found || waited >= WAKE_WAIT_MS) return found;
    await new Promise((resolve) => setTimeout(resolve, WAKE_STEP_MS));
  }
}

export async function openAgentTerminal(agentId: number, wake = true): Promise<boolean> {
  if (!swarmRoster.agents.some((a) => a.id === agentId)) return false;
  try {
    const target = liveSession(agentId) ?? (wake ? await wakeForTerminal(agentId) : null);
    return target ? await openSession(target.sessionId, target.name) : false;
  } catch (error) {
    console.warn('cplug.huddle: the agent terminal could not be opened', error);
    return false;
  }
}
