import { carriesFiles, filesOf } from './task-manager-files';

export function pasteFiles(event: ClipboardEvent, add: (files: File[]) => void): void {
  const files = filesOf(event.clipboardData);
  if (files.length === 0) return;
  event.preventDefault();
  add(files);
}

export function dragOverFiles(event: DragEvent): boolean {
  if (!carriesFiles(event.dataTransfer)) return false;
  event.preventDefault();
  return true;
}

export function dropFiles(event: DragEvent, add: (files: File[]) => void): void {
  const files = filesOf(event.dataTransfer);
  if (files.length === 0) return;
  event.preventDefault();
  add(files);
}
