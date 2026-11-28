import { announceFailure, authFetch, openPage, postedPageOpener, t } from '../sdk';
import type { TaskManagerArtifact } from './huddle-model';

export interface ArtifactTicket {
  url: string;
  expires_in: number;
  title: string;
}

export const artifactDialog = $state<{ open: boolean; title: string; url: string; failed: boolean }>({ open: false, title: '', url: '', failed: false });

function mintTicket(itemId: number, artifactId: string): Promise<ArtifactTicket> {
  return authFetch<ArtifactTicket>(`/cplugs/huddle/items/${itemId}/artifacts/${encodeURIComponent(artifactId)}/ticket`, { method: 'POST' });
}

export async function openArtifactInTab(itemId: number, artifact: TaskManagerArtifact): Promise<boolean> {
  closeArtifact();
  try {
    const board = postedPageOpener();
    if (board && (await board({ item: itemId, title: artifact.title }).catch(() => false))) return true;
    await openPage({ huddle_artifact: { item: itemId, artifact: artifact.id }, title: artifact.title });
    return true;
  } catch (err) {
    announceFailure(t('browser.open_page_failed', { detail: err instanceof Error ? err.message : String(err) }));
    return false;
  }
}

let latest = 0;

export async function openArtifact(itemId: number, artifact: TaskManagerArtifact): Promise<void> {
  const mine = ++latest;
  Object.assign(artifactDialog, { open: true, title: artifact.title, url: '', failed: false });
  try {
    const ticket = await mintTicket(itemId, artifact.id);
    if (mine === latest) artifactDialog.url = ticket.url;
  } catch {
    if (mine === latest) artifactDialog.failed = true;
  }
}

export function closeArtifact(): void {
  latest += 1;
  Object.assign(artifactDialog, { open: false, url: '', failed: false });
}
