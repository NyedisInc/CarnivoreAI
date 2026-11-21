
import type { DelegatedUsage } from '../../opscenter/api/types';
import { t } from '../i18n/index.svelte';
import { compactTokens } from '../../../../client/js/labels/usage-panel.js';

export interface DelegatedSegment {
  text: string;
  title: string;
  live: boolean;
}

export function delegatedSegment(delegated: DelegatedUsage | null | undefined): DelegatedSegment | null {
  const running = delegated?.running ?? 0;
  const remote = delegated?.remote_jobs ?? 0;
  if (!delegated || !(delegated.jobs >= 1 || running >= 1 || remote >= 1)) return null;
  const count = (n: number): string => t(n === 1 ? 'footbar.delegated.jobs.one' : 'footbar.delegated.jobs.many', { n: String(n) });
  const elsewhere = t('footbar.delegated.running.elsewhere');
  const lines: string[] = [];
  if (running >= 1) lines.push(t('footbar.delegated.active', { n: String(running), where: (delegated.running_on ?? []).join(', ') || elsewhere }));
  const total = delegated.input_tokens + delegated.output_tokens + delegated.cache_read_tokens + delegated.cache_write_tokens;
  lines.push(t('footbar.delegated.total', { jobs: count(Math.max(remote, delegated.jobs)), tokens: compactTokens(total) ?? '0' }));
  if (delegated.jobs >= 1) {
    const tokens = { input: compactTokens(delegated.input_tokens) ?? '0', output: compactTokens(delegated.output_tokens) ?? '0' };
    lines.push(delegated.cost_usd == null
      ? t('footbar.delegated.spend.nocost', tokens)
      : t('footbar.delegated.spend', { ...tokens, cost: t('usage.cost.value', { amount: delegated.cost_usd.toFixed(2) }) }));
  }
  return {
    text: `${t('footbar.delegated.title')} ${lines.join('; ')}`,
    title: [t('footbar.delegated.title'), ...lines.map((l) => `\u2022 ${l}`)].join('\n'),
    live: running >= 1,
  };
}
