import { authFetch } from '../../api/auth.svelte';
import type { SessionContents } from './types';

export function getContents(rowId: number): Promise<SessionContents> {
  return authFetch<SessionContents>(`/sessions/${rowId}/contents`);
}

/* the head preview */
export interface ConfigFileRead {
  content: string;
  is_sensitive: boolean;
}

export function readFile(root: string, path: string, projectPath: string | null): Promise<ConfigFileRead> {
  const params = new URLSearchParams({ root, path });
  if (projectPath) params.set('project_path', projectPath);
  return authFetch<ConfigFileRead>(`/config-files/read?${params.toString()}`);
}
