
import { isDemo } from './demo';
import { sessions } from './sessions.svelte';
import { recent } from './recent.svelte';
import { projects } from './projects.svelte';
import { themes } from './themes.svelte';
import type { EventFrame } from './types';
import { resourcePush } from '../../lib/resource-push/boot';

interface HostEvents {
  subscribe(handler: (frame: EventFrame) => void): () => void;
  isConnected(): boolean;
}

function host(): HostEvents | null {
  const found = (globalThis as { AppEvents?: unknown }).AppEvents as HostEvents | undefined;
  if (!found || typeof found.subscribe !== 'function') return null;
  return found;
}

export const transport = $state<{ state: 'connected' | 'disconnected' | 'unknown' }>({
  state: 'unknown',
});

export type FrameHandler = (frame: EventFrame) => void;

const handlers = new Map<string, Set<FrameHandler>>();

export function subscribe(kind: string, handler: FrameHandler): () => void {
  const held = handlers.get(kind) ?? new Set<FrameHandler>();
  held.add(handler);
  handlers.set(kind, held);
  return () => {
    held.delete(handler);
  };
}

let detach: (() => void) | null = null;

function refreshOnHello(): void {
  void sessions.refresh();
  void recent.refresh();
  if (!resourcePush().isLive('projects')) void projects.refresh();
  void themes.refresh();
}

function refreshOnRename(): void {
  void sessions.refresh(true);
}

function dispatch(frame: EventFrame): void {
  const held = handlers.get(frame.type);
  if (!held) return;
  for (const handler of held) {
    try {
      handler(frame);
    } catch {
    }
  }
}

export function startEvents(): void {
  if (isDemo()) {
    transport.state = 'connected';
    return;
  }
  if (detach) return;
  const client = host();
  if (!client) return;
  transport.state = client.isConnected() ? 'connected' : 'unknown';
  detach = client.subscribe((frame: EventFrame) => {
    if (!frame || typeof frame.type !== 'string') return;
    if (frame.type === 'events.open') {
      transport.state = 'connected';
      return;
    }
    if (frame.type === 'events.closed') {
      transport.state = 'disconnected';
      return;
    }
    if (frame.type === 'events.hello') refreshOnHello();
    if (frame.type === 'session.renamed') refreshOnRename();
    dispatch(frame);
  });
}

export function stop(): void {
  if (detach) detach();
  detach = null;
  transport.state = 'unknown';
}
