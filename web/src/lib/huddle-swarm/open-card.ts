import { t } from '../i18n/index.svelte';
import { authFetch, ApiError } from '../../opscenter/api/auth.svelte';
import { boardFocus } from '../swarm-board/board-focus.svelte';
import { openHuddleSwarmScreen } from './screen-host';

export interface OpenCardDeps {
  read: (path: string) => Promise<{ archived_at?: number | null }>;
  open: () => unknown;
  toast: (title: string) => void;
}

function toast(title: string): void {
  const surface = (globalThis as { ToastManager?: { add(item: Record<string, unknown>): void } }).ToastManager;
  if (surface) surface.add({ id: `swarm-card-gone:${Date.now()}`, session_id: null, kind: 'SwarmCardGone', title, body: null, local: true });
  else console.warn('[swarm-card]', title);
}

const DEFAULT_DEPS: OpenCardDeps = { read: (path) => authFetch(path), open: openHuddleSwarmScreen, toast };

export async function openCardOnBoard(id: number, deps: OpenCardDeps = DEFAULT_DEPS): Promise<boolean> {
  let card: { archived_at?: number | null };
  try {
    card = await deps.read(`/swarm/cards/${id}`);
  } catch (failure) {
    const gone = failure instanceof ApiError && failure.status === 404;
    deps.toast(gone ? t('swarm.board.card_gone', { id }) : t('swarm.board.card_open_failed', { id }));
    return false;
  }
  boardFocus.request = { id, archived: card.archived_at != null, at: Date.now() };
  deps.open();
  return true;
}
