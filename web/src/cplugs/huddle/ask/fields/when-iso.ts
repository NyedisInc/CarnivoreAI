
const pad = (n: number, width = 2): string => String(n).padStart(width, '0');

const WALL = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})/;

export function localToIso(local: string): string {
  const wall = WALL.exec(local)?.[1];
  const moment = new Date(local);
  if (!wall || Number.isNaN(moment.getTime())) return '';
  const offset = -moment.getTimezoneOffset();
  const sign = offset < 0 ? '-' : '+';
  const abs = Math.abs(offset);
  return `${wall}:00${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

export function isoToLocal(iso: string): string {
  const wall = WALL.exec(iso)?.[1];
  if (wall && localToIso(wall) === iso) return wall;
  const moment = new Date(iso);
  if (!iso || Number.isNaN(moment.getTime()) || moment.getFullYear() > 9999) return '';
  return `${pad(moment.getFullYear(), 4)}-${pad(moment.getMonth() + 1)}-${pad(moment.getDate())}T${pad(moment.getHours())}:${pad(moment.getMinutes())}`;
}
