import type { TaskManagerFile } from './huddle-model';

export const MAX_PER_REPLY = 10;

export interface TransferLike {
  files?: ArrayLike<File> | null;
  items?: ArrayLike<{ kind: string; getAsFile(): File | null }> | null;
  types?: ArrayLike<string> | null;
}

export function carriesFiles(data: TransferLike | null | undefined): boolean {
  return !!data?.types && Array.from(data.types).includes('Files');
}

export function filesOf(data: TransferLike | null | undefined): File[] {
  if (!data) return [];
  const direct = Array.from(data.files ?? []);
  if (direct.length) return direct;
  return Array.from(data.items ?? []).filter((i) => i.kind === 'file').map((i) => i.getAsFile()).filter((f): f is File => f !== null);
}

export function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} b`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} kb`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} mb`;
}

export function readyIds(chips: ReadonlyArray<{ status: string; ref?: Pick<TaskManagerFile, 'id'> }>): string[] {
  return chips.flatMap((c) => (c.status === 'ready' && c.ref ? [c.ref.id] : []));
}
