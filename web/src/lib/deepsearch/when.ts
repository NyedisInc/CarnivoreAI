import { stampLabel } from '../projects-shared/format';

export function hitTime(iso: string | null, now: Date = new Date()): string {
  const at = iso ? new Date(iso) : null;
  if (!at || Number.isNaN(at.getTime())) return '';
  const full = stampLabel(iso);
  const sameDay = at.getFullYear() === now.getFullYear() && at.getMonth() === now.getMonth() && at.getDate() === now.getDate();
  return sameDay ? full.slice(full.lastIndexOf(' ') + 1) : full;
}
