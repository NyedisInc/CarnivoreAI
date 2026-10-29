import { activeTerminalSessionId } from '../../opscenter/lib/active-terminal';
import { sessions } from '../../opscenter/api';
import { currentProjectId } from './current-project';
import { hostWindow } from './env';

export const ACTIVE_CHANNEL = 'carnivore.active-project';
const BOUND_EVENT = 'cloude:primary-session-bound';
const GONE_EVENT = 'cloude:primary-session-gone';

interface Frame {
  kind: 'active' | 'ask';
  session?: string | null;
  project?: number | null;
}

export const activeProject = $state<{ session: string | null; project: number | null }>({ session: null, project: null });

const pane = $state({ version: 0 });

function projectOf(row: unknown): number | null {
  const id = (row as { project_id?: unknown } | null)?.project_id;
  return typeof id === 'number' && Number.isInteger(id) && id > 0 ? id : null;
}

export function projectForSession(session: string): number | null {
  const row = (sessions.data ?? []).find((info) => info?.session?.id === session);
  const found = projectOf(row ?? null);
  if (found !== null) return found;
  const page = (hostWindow() as { TerminalController?: { _sessionId?: () => string | null } } | null)?.TerminalController;
  return page?._sessionId?.() === session ? currentProjectId() : null;
}

function adopt(session: string | null, project: number | null): boolean {
  if (activeProject.session === session && activeProject.project === project) return false;
  activeProject.session = session;
  activeProject.project = project;
  return true;
}

function openChannel(): BroadcastChannel | null {
  try {
    return typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel(ACTIVE_CHANNEL);
  } catch (err) {
    console.warn('active project: no broadcast channel', err);
    return null;
  }
}

let publishing: (() => void) | null = null;

export function publishActiveProject(): () => void {
  if (publishing) return publishing;
  const channel = openChannel();
  const say = (): void => channel?.postMessage({ kind: 'active', session: activeProject.session, project: activeProject.project } satisfies Frame);
  const bump = (): void => {
    pane.version += 1;
  };
  const win = hostWindow() as Window | null;
  win?.addEventListener?.(BOUND_EVENT, bump);
  win?.addEventListener?.(GONE_EVENT, bump);
  if (channel) {
    channel.onmessage = (event: MessageEvent<Frame>) => {
      const visible = typeof document === 'undefined' || document.visibilityState !== 'hidden';
      if (event.data?.kind === 'ask' && visible) say();
    };
  }
  const undo = $effect.root(() => {
    $effect(() => {
      void pane.version;
      const session = activeTerminalSessionId() || null;
      if (adopt(session, session ? projectForSession(session) : null)) say();
    });
  });
  publishing = () => {
    undo();
    channel?.close();
    win?.removeEventListener?.(BOUND_EVENT, bump);
    win?.removeEventListener?.(GONE_EVENT, bump);
    publishing = null;
  };
  return publishing;
}

let following: BroadcastChannel | null = null;

export function followActiveProject(): void {
  if (publishing || following) return;
  following = openChannel();
  if (!following) return;
  following.onmessage = (event: MessageEvent<Frame>) => {
    const frame = event.data;
    if (frame?.kind !== 'active') return;
    adopt(typeof frame.session === 'string' ? frame.session : null, projectOf({ project_id: frame.project }));
  };
  following.postMessage({ kind: 'ask' } satisfies Frame);
}

export function resetActiveProject(): void {
  publishing?.();
  following?.close();
  following = null;
  adopt(null, null);
}
