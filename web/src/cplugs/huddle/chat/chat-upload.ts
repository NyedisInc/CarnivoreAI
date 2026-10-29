import { authFetch } from '../../sdk';
import type { UploadedFile } from '../task-manager-files-api';

export async function uploadToSession(sessionId: string, file: File): Promise<UploadedFile> {
  const form = new FormData();
  form.append('file', file, file.name || `paste.${(file.type.split('/')[1] || 'bin').split(';')[0]}`);
  const saved = await authFetch<{ path: string; filename: string; size: number }>(
    `/sessions/upload-file?session_id=${encodeURIComponent(sessionId)}`, { method: 'POST', body: form });
  return { id: saved.path, name: saved.filename || file.name, mime: file.type, size: saved.size };
}

export function withPaths(text: string, paths: readonly string[]): string {
  return [text, ...paths].filter(Boolean).join('\n');
}

const UPLOAD_IMAGE = /^\/(?:[^\0\n]*\/)?\.(?:carnivore|cloude)_uploads\/[^/\0\n]+\.(?:png|jpe?g|gif|webp)$/i;

export function splitSentText(text: string): { text: string; images: string[] } {
  const images: string[] = [];
  const kept = text.split('\n').filter((line) => (UPLOAD_IMAGE.test(line.trim()) ? (images.push(line.trim()), false) : true));
  return { text: images.length ? kept.join('\n').trim() : text, images };
}
