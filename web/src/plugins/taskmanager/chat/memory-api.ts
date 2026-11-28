import { authFetch } from '../../sdk';

export interface MemoryFileRow {
  path: string;
  title: string;
  state: 'live' | 'held' | null;
}

export interface MemoryBackup {
  id: string;
  at: string;
}

export interface MemoryFile {
  path: string;
  text: string;
  backups: MemoryBackup[];
}

export function listMemoryFiles(agentId: number): Promise<MemoryFileRow[]> {
  return authFetch<MemoryFileRow[]>(`/swarm/agents/${agentId}/memory`);
}

export function readMemoryFile(agentId: number, path: string): Promise<MemoryFile> {
  return authFetch<MemoryFile>(`/swarm/agents/${agentId}/memory/file?path=${encodeURIComponent(path)}`);
}

export function saveMemoryFile(agentId: number, path: string, text: string): Promise<MemoryFile> {
  return authFetch<MemoryFile>(`/swarm/agents/${agentId}/memory/file`, { method: 'PUT', body: JSON.stringify({ path, text }) });
}

export function restoreMemoryFile(agentId: number, path: string, backupId?: string): Promise<MemoryFile> {
  const body = backupId === undefined ? { path } : { path, backup_id: backupId };
  return authFetch<MemoryFile>(`/swarm/agents/${agentId}/memory/restore`, { method: 'POST', body: JSON.stringify(body) });
}

export function undoAction(dirty: boolean, backups: readonly MemoryBackup[]): 'discard' | 'restore' | 'none' {
  if (dirty) return 'discard';
  return backups.length > 0 ? 'restore' : 'none';
}

export function backupLabel(backup: MemoryBackup, locale?: string): string {
  const at = new Date(backup.at);
  return Number.isNaN(at.getTime()) ? backup.id : at.toLocaleString(locale, { dateStyle: 'medium', timeStyle: 'medium' });
}
