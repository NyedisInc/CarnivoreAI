import type { PressureBlock } from '../pack-machines/pack-machines-store.svelte';

export type Translate = (key: string, params?: Record<string, string | number>) => string;

const num = (x: number): string => String(Number(x.toFixed(1)));

const clock = (epochSeconds: number): string =>
  new Date(epochSeconds * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });

export function pressureLine(p: PressureBlock, t: Translate): string {
  if (!p.pegged) return t('roster.can.calm');
  const parts: string[] = [];
  if (p.busy_cores != null && p.cores != null) {
    parts.push(p.line != null
      ? t('roster.can.peg.cores_line', { busy: num(p.busy_cores), cores: p.cores, line: num(p.line) })
      : t('roster.can.peg.cores', { busy: num(p.busy_cores), cores: p.cores }));
  }
  if (p.run_queue_per_core != null) parts.push(t('roster.can.peg.queue', { n: num(p.run_queue_per_core) }));
  if (p.mem === 'warn') parts.push(t('roster.can.peg.mem_warn'));
  else if (p.mem === 'critical') parts.push(t('roster.can.peg.mem_critical'));
  const head = p.since != null ? t('roster.can.peg.since', { time: clock(p.since) }) : t('roster.can.peg.now');
  return parts.length > 0 ? `${head}: ${parts.join('; ')}` : head;
}
