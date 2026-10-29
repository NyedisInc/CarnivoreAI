
const pad = (n: number): string => String(n).padStart(2, '0');

export function localToIso(local: string): string {
  const moment = new Date(local);
  if (!local || Number.isNaN(moment.getTime())) return '';
  const offset = -moment.getTimezoneOffset();
  const sign = offset < 0 ? '-' : '+';
  const abs = Math.abs(offset);
  return `${local.slice(0, 16)}:00${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

export function isoToLocal(iso: string): string {
  const moment = new Date(iso);
  if (!iso || Number.isNaN(moment.getTime())) return '';
  return `${moment.getFullYear()}-${pad(moment.getMonth() + 1)}-${pad(moment.getDate())}T${pad(moment.getHours())}:${pad(moment.getMinutes())}`;
}
