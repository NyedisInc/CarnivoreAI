import { authFetch } from '../../opscenter/api/auth.svelte';
import { openFromDrawer, openFromPath, type OpenResult } from '../open-files/open-bridge';
import { sessionRefFor } from '../open-files/session-ref';

export type RootId = 'workdir' | 'user';

export interface FxNode {
  name: string;
  rel_path: string;
  is_dir: boolean;
  is_executable?: boolean;
  is_sensitive?: boolean;
  read_only?: boolean;
  is_ignored?: boolean;
  children?: FxNode[];
  children_loaded?: boolean;
  list_error?: string | null;
  kind?: string;
  more_not_shown?: number;
}

export const FETCH_DEPTH = 1;

export interface TreeAnswer {
  root: string;
  tree: FxNode[];
  truncated?: boolean;
  ignore_status?: string | null;
}

export class NoProjectFolder extends Error {}

/* the project folder */
function query(root: RootId, projectPath: string | null, extra: Record<string, string>): string {
  if (root === 'workdir' && !projectPath) throw new NoProjectFolder('no project folder');
  const params = new URLSearchParams({ root });
  if (root === 'workdir' && projectPath) params.set('project_path', projectPath);
  for (const [key, value] of Object.entries(extra)) if (value) params.set(key, value);
  params.set('ignored', 'true');
  return params.toString();
}

export function readLevel(root: RootId, projectPath: string | null, path: string): Promise<TreeAnswer> {
  return authFetch<TreeAnswer>(`/config-files/tree?${query(root, projectPath, { path, depth: String(FETCH_DEPTH) })}`);
}

export function findIn(root: RootId, projectPath: string | null, q: string): Promise<TreeAnswer> {
  return authFetch<TreeAnswer>(`/config-files/find?${query(root, projectPath, { q })}`);
}

export async function openInFilesList(sessionId: string, root: RootId, path: string, kind: 'file' | 'diff'): Promise<OpenResult> {
  if (!sessionId) return 'unavailable';
  let ref;
  try {
    ref = await sessionRefFor(sessionId);
  } catch (err) {
    console.warn('files widget: the session listing could not be read', { sessionId, error: err });
    return 'unavailable';
  }
  return openFromDrawer({ ...ref, root, path, kind });
}

export function openPathInFilesList(path: string): Promise<void> {
  return openFromPath(path);
}
