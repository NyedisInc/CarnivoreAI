import { t } from '../i18n/index.svelte';
import { ageWords } from '../computers/computers-format';
import type { RosterComputer } from './roster-model';

export function seenWords(c: RosterComputer, nowMs: number, card: boolean): string | null {
  if (c.isSelf) return card ? null : t('roster.card.this');
  if (c.seenFrom === 'held') return t('roster.card.held_no_card');
  if (c.seenFrom === 'none') return t('roster.card.not_heard');
  if (c.member && !c.lastSeen && !c.seenFrom) return null;
  const age = c.lastSeen ? ageWords(c.lastSeen, nowMs) : t('roster.card.never_seen');
  if (c.seenFrom === 'card' && c.lastSeen) return t(card ? 'roster.card.last_heard' : 'roster.ov.heard', { age });
  return card ? t('roster.card.last_seen', { age }) : age;
}
