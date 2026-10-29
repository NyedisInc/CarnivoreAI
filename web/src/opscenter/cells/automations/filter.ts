import type { Automation } from '../../../lib/automations/api';

export function sessionOf(automation: Pick<Automation, 'target'>): string | null {
  const target = automation.target;
  const uuid = target.kind === 'session_message' ? target.session_uuid : null;
  return typeof uuid === 'string' && uuid !== '' ? uuid : null;
}

function bySchedule(a: Automation, b: Automation): number {
  const an = a.enabled ? a.next_fire_at : null;
  const bn = b.enabled ? b.next_fire_at : null;
  if (an !== bn) return an === null ? 1 : bn === null ? -1 : an - bn;
  return a.name.localeCompare(b.name);
}

export function forSession(all: readonly Automation[], uuid: string | null): Automation[] {
  if (!uuid) return [];
  return all.filter((a) => sessionOf(a) === uuid).sort(bySchedule);
}

export function notTiedToSession(all: readonly Automation[]): Automation[] {
  return all.filter((a) => sessionOf(a) === null).sort(bySchedule);
}
