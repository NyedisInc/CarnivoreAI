import { t } from '../../sdk';

const SERVER_LINE = /^status changed from (\S+) to (\S+?)(?: by .*)?$/;

export function statusLineText(text: string): string {
  const found = SERVER_LINE.exec(text.trim());
  return found ? t('cplug.huddle.tm.status_line', { from: found[1]!, to: found[2]! }) : text;
}
