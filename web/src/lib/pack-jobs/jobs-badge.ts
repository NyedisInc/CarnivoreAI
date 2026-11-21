import { t } from '../i18n/index.svelte';
import type { BadgeItem } from '../session-badges/slot';
import { packFragment } from '../pack-page/pack-hash';
import { jobHead, isWaiting, stateWord } from './jobs-format';
import { jobsStore, type JobsStore } from './jobs-store.svelte';

export function jobsBadges(row: Record<string, unknown>, store: JobsStore = jobsStore): BadgeItem[] {
  const uuid = row.session_uuid;
  if (typeof uuid !== 'string' || !uuid) return [];
  const host = row.host_key;
  if (typeof host === 'string' && host !== '' && host !== 'local') return [];
  const jobs = store.liveFor(uuid);
  if (jobs.length === 0) return [];
  const lines = jobs.map((j) => t('pack.jobs.badge.line', { computer: j.computer ?? '', head: jobHead(j), state: stateWord(j.state) }));
  return [{
    kind: 'jobs',
    key: 'jobs',
    text: t(jobs.length === 1 ? 'pack.jobs.badge.one' : 'pack.jobs.badge.many', { count: String(jobs.length) }),
    title: lines.join('\n'),
    tone: jobs.some(isWaiting) ? 'warn' : undefined,
    activate: () => {
      store.setCaller(uuid);
      window.location.hash = packFragment('jobs');
    },
  }];
}
