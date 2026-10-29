import { readFile } from './api';
import { canOpen } from './opener';
import type { ContentsItem } from './types';

const PREVIEW_KINDS: ReadonlySet<string> = new Set(['instructions', 'skills', 'agents', 'commands', 'output_styles', 'prompts']);

const SECRET_NAME = /(^|\/)(\.env[^/]*|auth\.json|credentials[^/]*|\.claude\.json|[^/]*(secret|token)[^/]*|[^/]*\.(pem|key))$/i;

export const PREVIEW_LINES = 8;
const PREVIEW_LINE_CHARS = 160;

export function canPreview(kind: string, item: Pick<ContentsItem, 'open_root' | 'open_path'>): boolean {
  return PREVIEW_KINDS.has(kind) && canOpen(item) && !SECRET_NAME.test(item.open_path ?? '');
}

export function headLines(content: string, max: number = PREVIEW_LINES): string[] {
  return content.split('\n').slice(0, max).map((line) => line.replace(/\s+$/, '').slice(0, PREVIEW_LINE_CHARS));
}

export async function loadHead(kind: string, item: ContentsItem, workingDir: string | null): Promise<string[] | null> {
  if (!canPreview(kind, item)) return null;
  try {
    const file = await readFile(item.open_root as string, item.open_path as string, workingDir);
    return file.is_sensitive ? null : headLines(file.content);
  } catch (err) {
    console.warn('session resources: the head preview could not be read', { path: item.open_path, error: err instanceof Error ? err.message : String(err) });
    return null;
  }
}
