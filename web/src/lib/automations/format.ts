import { t } from '../i18n/index.svelte';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { codeWords, reasonWords } from './logic/words';
import type { Actor, Automation, RunSummary } from './api';

export function logEventLabel(line: { event: string; status?: unknown }): string {
  const word = codeWords('automations.log.event', line.event);
  const status = typeof line.status === 'string' ? line.status : '';
  return status && !word.includes(status) ? `${word} ${status}` : word;
}

export function refusalCode(error: unknown): string {
  if (!(error instanceof ApiError)) return '';
  if (error.code) return error.code;
  const detail = (error.payload as { detail?: { code?: unknown } } | null)?.detail;
  return typeof detail?.code === 'string' ? detail.code : '';
}

export function refusalText(error: unknown): string {
  const code = refusalCode(error);
  if (code) {
    const known = codeWords('automations.refused', code);
    if (known !== code) return known;
  }
  return error instanceof Error ? error.message : String(error);
}

export function whenLabel(epoch: number): string {
  return new Date(epoch * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function dayLabel(epoch: number): string {
  return new Date(epoch * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function runLine(run: RunSummary): string {
  const reason = reasonWords(run.reason);
  if (run.status !== 'skipped') return reason;
  const count = run.skip_count ?? 1;
  if (count <= 1) return t('automations.run.skipped_one', { reason });
  const first = run.first_slot_at ?? run.slot_at;
  const last = run.last_slot_at ?? first;
  const from = first == null ? '' : dayLabel(first);
  const to = last == null ? from : dayLabel(last);
  const range = from === to ? from : t('automations.run.range', { from, to });
  return t('automations.run.skipped_many', { count, range, reason });
}

export function costLabel(cost: number | null | undefined): string {
  return cost == null ? t('automations.run.cost_unmeasured') : `$${cost.toFixed(2)}`;
}

export function lastRunLine(run: RunSummary): string {
  if (run.status === 'skipped') return runLine(run);
  const reason = reasonWords(run.reason);
  return [codeWords('automations.run.status', run.status) + (reason ? `: ${reason}` : ''), costLabel(run.cost_usd)].join(', ');
}

export function actorLabel(actor: Actor | null | undefined): string {
  if (!actor) return t('automations.actor.unknown');
  if (actor.kind === 'mcp') return t('automations.actor.mcp', { who: actor.tmux || actor.session_id || actor.client || '?' });
  return codeWords('automations.actor', actor.kind);
}

export function modifiedLine(automation: Automation): string {
  return t('automations.modified', { when: whenLabel(automation.updated_at), who: actorLabel(automation.updated_actor) });
}

export function valueLabel(value: unknown): string {
  if (value === null || value === undefined || value === '') return t('automations.value.none');
  if (typeof value === 'string') return value;
  if (typeof value === 'boolean') return t(value ? 'automations.value.yes' : 'automations.value.no');
  return JSON.stringify(value);
}

export function toMinutes(seconds: number): number {
  return Math.max(1, Math.round(seconds / 60));
}

export function fieldSeconds(minutes: number, stored: number | null | undefined): number {
  const whole = Math.round(minutes);
  return stored != null && toMinutes(stored) === whole ? stored : whole * 60;
}
