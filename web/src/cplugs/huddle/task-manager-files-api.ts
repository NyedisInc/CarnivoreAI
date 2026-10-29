/* could not */
import { authFetch } from '../sdk';
import type { TaskManagerFile } from './huddle-model';

export type UploadedFile = Pick<TaskManagerFile, 'id' | 'name' | 'mime' | 'size'>;

export function uploadFile(itemId: number, file: File): Promise<UploadedFile> {
  const form = new FormData();
  form.append('file', file, file.name);
  return authFetch<UploadedFile>(`/cplugs/huddle/items/${itemId}/files`, { method: 'POST', body: form });
}

const blobs = new Map<string, Promise<Blob>>();

export function fetchFileBlob(itemId: number, fileId: string): Promise<Blob> {
  const key = `${itemId}/${fileId}`;
  let hit = blobs.get(key);
  if (!hit) {
    hit = authFetch<Blob>(`/cplugs/huddle/items/${itemId}/files/${fileId}`);
    hit.catch(() => blobs.delete(key));
    blobs.set(key, hit);
  }
  return hit;
}
