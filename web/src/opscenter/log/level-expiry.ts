
const REREAD_SLACK_MS = 1000;

export function formatUntil(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return '';
  return at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
}

export function msUntilReread(iso: string, now: number = Date.now()): number | null {
  const at = new Date(iso).getTime();
  return Number.isNaN(at) ? null : Math.max(0, at - now) + REREAD_SLACK_MS;
}
