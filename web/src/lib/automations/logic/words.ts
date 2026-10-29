import { t } from '../../i18n/index.svelte';

export const DAY = 86400;

export function codeWords(prefix: string, code: string): string {
  const key = `${prefix}.${code}`;
  const text = t(key);
  return text === key ? code : text;
}

export function countWords(base: string, n: number): string {
  return t(n === 1 ? `${base}_one` : `${base}_many`, { n });
}

export function humanKey(key: string): string {
  return String(key).replace(/_/g, ' ').toLowerCase();
}

export function pathWords(path: string): string {
  return String(path)
    .replace(/\[([^\]]*)\]/g, '.$1')
    .replace(/^\./, '')
    .split('.')
    .map(humanKey)
    .join(' / ');
}

export function tileLabel(key: string): string {
  const stripped = String(key).replace(/_(ms|s|bytes|pct|usd)$/, '');
  return humanKey(stripped || key);
}

export function bytesWords(n: number | null | undefined): string {
  if (n == null) return '';
  if (n < 1024) return `${n} ${n === 1 ? 'byte' : 'bytes'}`;
  if (n < 1048576) {
    const k = n / 1024;
    return `${k < 10 ? Math.round(k * 10) / 10 : Math.round(k)} KB`;
  }
  return `${Math.round((n / 1048576) * 10) / 10} MB`;
}

function group(n: number, maxFrac = 3): string {
  return Number(n).toLocaleString('en-US', { maximumFractionDigits: maxFrac });
}

function unitOf(key: string): string | null {
  if (/_usd$/.test(key)) return 'usd';
  if (/_pct$/.test(key)) return '%';
  if (/_bytes$/.test(key)) return 'bytes';
  if (/_ms$/.test(key)) return 'ms';
  if (/_s$/.test(key)) return 's';
  return null;
}

export function fmtNum(v: number, key = '', unit?: string | null): string {
  const u = unit || unitOf(key);
  if (u === 'usd' || u === '$') {
    return `$${Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  if (u === '%') return `${group(v, 1)}%`;
  if (u === 'bytes') return bytesWords(v);
  if (u) return `${group(v, 2)} ${u}`;
  return group(v);
}

export function signed(n: number, unit = ''): string {
  return `${n > 0 ? '+' : n < 0 ? '-' : ''}${Math.abs(n)}${unit}`;
}

export function secsWords(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s)) return '';
  if (s < 10) return `${Math.round(s * 10) / 10} s`;
  if (s < 60) return `${Math.round(s)} s`;
  return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

export function tookWords(run: { started_at: number | null; ended_at: number | null }): string | null {
  if (run.started_at == null || run.ended_at == null) return null;
  return secsWords(run.ended_at - run.started_at);
}

export function feedTookWords(run: { started_at: number | null; ended_at: number | null }): string | null {
  if (run.started_at == null || run.ended_at == null) return null;
  const s = run.ended_at - run.started_at;
  if (!Number.isFinite(s) || s < 60) return secsWords(s);
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  const h = s / 3600;
  return `${h < 10 ? Math.round(h * 10) / 10 : Math.round(h)} h`;
}

export function statusWord(status: string): string {
  return codeWords('automations.run.status', status);
}

export function runStatusWord(run: { status: string; reason: string | null }): string {
  return run.status === 'failed' && run.reason === 'cancelled_by_owner' ? statusWord('cancelled') : statusWord(run.status);
}

export function reasonWords(code: string | null | undefined): string {
  if (!code) return '';
  const exit = /^exit_(\d+)$/.exec(code);
  if (exit) return t('automations.reason.exit', { n: exit[1] });
  return codeWords('automations.reason', code);
}

function dayWords(epoch: number, tz: string): string {
  return new Intl.DateTimeFormat('en-US', { timeZone: tz, month: 'short', day: 'numeric' }).format(new Date(epoch * 1000)).toLowerCase();
}

export function skipSentence(
  run: { reason: string | null; skip_count: number | null; first_slot_at?: number | null; last_slot_at?: number | null },
  tz: string,
): string {
  const reason = reasonWords(run.reason);
  const count = run.skip_count ?? 1;
  if (count > 1 && run.first_slot_at != null && run.last_slot_at != null) {
    const range = t('automations.run.range', { from: dayWords(run.first_slot_at, tz), to: dayWords(run.last_slot_at, tz) });
    return t('automations.run.skipped_many', { count, range, reason });
  }
  return t('automations.run.skipped_one', { reason });
}

export function skipReason(run: Parameters<typeof skipSentence>[0], tz: string): string {
  return skipSentence(run, tz).replace(/^skipped:?\s*/, '');
}

export function triggerKey(run: { trigger: string; attempt?: number | null }): string {
  return (run.attempt ?? 1) > 1 ? 'retry' : run.trigger || 'schedule';
}

export function triggerLabel(key: string): string {
  const word = codeWords('automations.run.trigger', key);
  return word === key ? key.replace(/_/g, ' ') : word;
}

export function triggerWord(run: { trigger: string; attempt?: number | null }, retryMax: number): string {
  const attempt = run.attempt ?? 1;
  if (attempt > 1) return t('automations.page.trigger.retry_of', { n: attempt - 1, total: Math.max(1, retryMax) });
  return run.trigger === 'schedule' || !run.trigger ? '' : triggerLabel(run.trigger);
}

export function isLive(status: string): boolean {
  return status === 'running' || status === 'claimed' || status === 'waiting_on_you';
}

export function runTime(run: { ended_at: number | null; started_at: number | null; slot_at: number | null; created_at?: number | null }): number {
  return run.ended_at ?? run.started_at ?? run.slot_at ?? run.created_at ?? 0;
}

export function meridiem(s: string): string {
  return String(s).replace(/\s?\b(am|pm)\b/gi, (_m, ap: string) => ` ${ap.toUpperCase()}`);
}

export function bucketByDay<T>(items: readonly T[], at: (item: T) => number, clock: Clock, now: number, plain = false): { key: string; label: string; items: T[] }[] {
  const out: { key: string; label: string; items: T[] }[] = [];
  const byKey = new Map<string, { key: string; label: string; items: T[] }>();
  for (const item of [...items].sort((a, b) => at(b) - at(a))) {
    const epoch = at(item);
    const key = clock.dayKey(epoch);
    let bucket = byKey.get(key);
    if (!bucket) {
      bucket = { key, label: clock.dayLabel(epoch, now, plain), items: [] };
      byKey.set(key, bucket);
      out.push(bucket);
    }
    bucket.items.push(item);
  }
  return out;
}

export function lowerWithMeridiem(s: string): string {
  return String(s).toLowerCase().replace(/\s?\b(am|pm)\b/g, (_m, ap: string) => ` ${ap.toUpperCase()}`);
}

export interface Clock {
  hms24(epoch: number): string;
  hm24(epoch: number): string;
  hm12(epoch: number): string;
  hms12(epoch: number): string;
  dayKey(epoch: number): string;
  dayLabel(epoch: number, now: number, plain?: boolean): string;
  when(epoch: number | null): string;
  whenLong(epoch: number | null): string;
  short(epoch: number | null, now: number): string;
  rel(epoch: number | null, now: number): string;
}

export function clockFor(tz: string): Clock {
  const f = (o: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat('en-US', { timeZone: tz, ...o });
  const hms = f({ hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' });
  const hm = f({ hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  const hms12 = f({ hour: 'numeric', minute: '2-digit', second: '2-digit' });
  const key = f({ year: 'numeric', month: '2-digit', day: '2-digit' });
  const label = f({ weekday: 'short', month: 'short', day: 'numeric' });
  const day = f({ month: 'short', day: 'numeric' });
  const wday = f({ weekday: 'short' });
  const clock = f({ hour: 'numeric', minute: '2-digit' });
  const d = (e: number) => new Date(e * 1000);
  const hm12 = (e: number) => meridiem(clock.format(d(e)));
  const when = (e: number | null) => (e == null ? '' : `${day.format(d(e))}, ${hm12(e)}`);
  const whenLong = (e: number | null) => (e == null ? '' : `${wday.format(d(e))} ${day.format(d(e))}, ${hm12(e)}`);
  return {
    hms24: (e) => hms.format(d(e)),
    hm24: (e) => hm.format(d(e)),
    hm12,
    hms12: (e) => lowerWithMeridiem(hms12.format(d(e))),
    dayKey: (e) => key.format(d(e)),
    dayLabel(e, now, plain = false) {
      const k = key.format(d(e));
      if (k === key.format(d(now))) return t('automations.page.day.today');
      if (k === key.format(d(now - DAY))) return t('automations.page.day.yesterday');
      if (plain) return day.format(d(e));
      const p: Record<string, string> = {};
      for (const x of label.formatToParts(d(e))) p[x.type] = x.value;
      return `${p.weekday} ${p.month} ${p.day}`.toLowerCase();
    },
    when,
    whenLong,
    short(e, now) {
      if (e == null) return '';
      return day.format(d(e)) === day.format(d(now)) ? hm12(e) : `${wday.format(d(e))} ${hm12(e)}`;
    },
    rel(e, now) {
      if (e == null) return '';
      const delta = e - now;
      const a = Math.abs(delta);
      let s: string;
      if (a < 45) s = 'now';
      else if (a < 3600) s = `${Math.round(a / 60)} min`;
      else if (a < DAY) s = `${Math.round(a / 3600)}h`;
      else s = `${Math.round(a / DAY)}d`;
      if (s === 'now') return t('automations.page.rel.now');
      return delta < 0 ? t('automations.page.rel.ago', { span: s }) : t('automations.page.rel.in', { span: s });
    },
  };
}
