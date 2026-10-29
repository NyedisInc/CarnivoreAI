import { openFromDrawer, type OpenResult } from '../../../lib/open-files/open-bridge';
import type { ContentsItem } from './types';

const ROOTS = ['workdir', 'user'] as const;

export interface OpenSession {
  sessionId?: string | null;
  rowId: number | null;
}

export function canOpen(item: Pick<ContentsItem, 'open_root' | 'open_path'>): boolean {
  return !!item.open_path && ROOTS.some((root) => root === item.open_root);
}

export async function openInFiles(item: ContentsItem, session: OpenSession): Promise<OpenResult> {
  if (!canOpen(item) || session.rowId === null) return 'unavailable';
  return openFromDrawer({ sessionId: session.sessionId ?? null, sessionRowId: session.rowId, root: item.open_root as 'workdir' | 'user', path: item.open_path as string });
}
