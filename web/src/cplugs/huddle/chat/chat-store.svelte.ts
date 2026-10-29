import { resourcePush } from '../../sdk';
import { TASK_MANAGER_LIST_FAMILY, followTaskManagerDelta, type TaskManagerDeltaWire } from '../../sdk/task-manager-delta';
import { readAgent, readConversation, type SwarmAgentDetail, type SwarmEntry } from './chat-api';

export const AGENT_FAMILY = 'swarm_agent';
const LIVENESS = '$live';

export interface ChatState {
  agent: SwarmAgentDetail | null;
  entries: SwarmEntry[];
  status: 'loading' | 'ok' | 'error';
}

export interface ChatStore {
  readonly state: ChatState;
  start(): () => void;
  refresh(): Promise<void>;
}

export function createChatStore(agentId: number): ChatStore {
  const state = $state<ChatState>({ agent: null, entries: [], status: 'loading' });
  const names = new Set([`${AGENT_FAMILY}:${agentId}`, LIVENESS]);
  const listKey = agentListKey(agentId);
  const listTopic = `${TASK_MANAGER_LIST_FAMILY}:${listKey}`;
  let reading = false;
  let again = false;
  let stopped = false;

  async function refresh(): Promise<void> {
    if (reading) {
      again = true;
      return;
    }
    reading = true;
    try {
      const [agent, page] = await Promise.all([readAgent(agentId), readConversation(agentId)]);
      if (stopped) return;
      state.agent = agent;
      state.entries = Array.isArray(page.entries) ? page.entries : [];
      state.status = 'ok';
    } catch (error) {
      if (!stopped) {
        state.status = 'error';
        console.warn('cplug.huddle.chat: the conversation could not be read', error);
      }
    } finally {
      reading = false;
    }
    if (again && !stopped) {
      again = false;
      await refresh();
    }
  }

  function start(): () => void {
    stopped = false;
    const off = resourcePush().onChange((topics) => {
      if (topics.some((topic) => names.has(topic))) void refresh();
    });
    const offDelta = followTaskManagerDelta({
      touches: (delta) => listRowsMoved(delta, listKey),
      fallback: (topic) => topic === listTopic,
      refresh: () => void refresh(),
    });
    void refresh();
    return () => {
      stopped = true;
      off();
      offDelta();
    };
  }

  return { state, start, refresh };
}

export function agentListKey(agentId: number): string {
  return `agent:${agentId}`;
}

export function listRowsMoved(delta: TaskManagerDeltaWire, list: string): boolean {
  return (delta.lists ?? []).some((entry) => entry.list === list && (entry.items.length > 0 || entry.deleted.length > 0));
}
