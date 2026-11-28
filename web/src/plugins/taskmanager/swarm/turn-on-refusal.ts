import { t } from '../../sdk';

export function turnOnRefusal(error: unknown, name: string): string {
  const reason = error instanceof Error && error.message ? error.message : String(error);
  return t('cplug.huddle.swarm.seat.refused', { name, reason });
}
