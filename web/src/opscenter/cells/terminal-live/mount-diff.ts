import { mountInto } from '../../../lib/mount';
import GitDiffView from './GitDiffView.svelte';

export function mountDiffInto(body: Element, props: { sessionId: string; path: string; source?: string }): () => void {
  return mountInto(body, GitDiffView, props);
}
