import { resourcePush } from '../../sdk';
import { readWaiting, type SwarmWaitingItem } from './chat-api';
import { feedTopic } from './waiting-model';

export const SETTLE_MS = 400;

export interface WaitingState {
  items: SwarmWaitingItem[];
  failed: boolean;
}

export function createWaitingStore(agentId: number): { state: WaitingState; start: () => () => void; refresh: () => Promise<void> } {
  const state = $state<WaitingState>({ items: [], failed: false });
  let stopped = false;
  let reading = false;
  let again = false;
  let pending: ReturnType<typeof setTimeout> | null = null;

  async function refresh(): Promise<void> {
    if (reading) {
      again = true;
      return;
    }
    reading = true;
    try {
      const found = await readWaiting(agentId);
      if (!stopped) {
        state.items = Array.isArray(found.items) ? found.items : [];
        state.failed = false;
      }
    } catch (error) {
      if (!stopped) {
        state.failed = true;
        console.warn('cplug.huddle.chat: the waiting tray could not be read', error);
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
      if (!topics.some(feedTopic) || pending !== null) return;
      pending = setTimeout(() => {
        pending = null;
        if (!stopped) void refresh();
      }, SETTLE_MS);
    });
    void refresh();
    return () => {
      stopped = true;
      off();
      if (pending !== null) clearTimeout(pending);
      pending = null;
    };
  }

  return { state, start, refresh };
}
