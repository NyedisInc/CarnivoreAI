import { timeMs } from './model';
import { beganWord, busyMinutes, kindWord, markTitle, tokensWord } from './format';
import type { Bar, Gap, Mark, SessionTimeline } from './types';
import type { Item } from './plot-model';
import { clockOf, spanWords, stampOf } from './scale';
import { tx } from './strings';

export function stamp(iso: string | null | undefined): string {
  const ms = timeMs(iso);
  return ms === null ? '' : stampOf(ms);
}

export function clock(iso: string | null | undefined): string {
  const ms = timeMs(iso);
  return ms === null ? '' : clockOf(ms);
}

export function convShort(bar: Bar, index: number): string {
  return `${index + 1} ${beganWord(bar)}`;
}

export function convBegan(bar: Bar, data: SessionTimeline): string {
  const split = bar.began?.split;
  const parent = split ? data.bars.findIndex((b) => b.conversation_id === (split.conversation ?? bar.began?.from_conversation)) : -1;
  return split && parent >= 0 ? tx('conv.from', { kind: beganWord(bar), n: parent + 1, when: clock(split.at) }) : beganWord(bar);
}

export function convLine(bar: Bar, index: number): string {
  return tx('conv.summary', { n: index + 1, kind: beganWord(bar), when: stamp(bar.started_at) });
}

export function convFacts(bar: Bar, data: SessionTimeline): string[] {
  const facts: string[] = [];
  facts.push(bar.current ? tx('conv.span_now', { from: stamp(bar.started_at) }) : tx('conv.span', { from: stamp(bar.started_at), to: stamp(bar.ended_at) }));
  if (typeof bar.busy_seconds === 'number') facts.push(tx('conv.busy', { minutes: busyMinutes(bar.busy_seconds) }));
  facts.push(tx('conv.marks', { count: data.marks.filter((m) => m.conversation_id === bar.conversation_id).length }));
  if (bar.current) facts.push(tx('conv.current'));
  return facts;
}

export function sleepWords(gap: Gap, data: SessionTimeline): [string, string] {
  const from = timeMs(gap.start) ?? 0;
  const to = (gap.end === null ? timeMs(data.now) : timeMs(gap.end)) ?? from;
  return [tx('sleep.title', { span: spanWords(to - from) }), gap.end === null ? tx('conv.span_now', { from: stamp(gap.start) }) : tx('conv.span', { from: stamp(gap.start), to: stamp(gap.end) })];
}

export function markShort(mark: Mark): string {
  if (mark.kind === 'compact') return mark.pre_tokens !== null ? tx('short.compact', { tokens: tokensWord(mark.pre_tokens) }) : tx('short.compact_plain');
  if (mark.kind === 'restore') return mark.turns !== null ? tx('short.restore', { turns: mark.turns }) : tx('short.restore_plain');
  return markTitle(mark);
}

export function clusterShort(marks: readonly Mark[]): string {
  return tx('cluster.short', { count: marks.length, titles: marks.map(markShort).join(', ') });
}

export function markLine(mark: Mark): string {
  return `${kindWord(mark)}, ${markTitle(mark)}, ${stamp(mark.at)}`;
}

export function itemLabel(item: Item, data: SessionTimeline): string {
  if (item.kind === 'conversation') return convLine(item.bar, item.index);
  if (item.kind === 'mark') return markLine(item.mark);
  if (item.kind === 'sleep') return sleepWords(item.gap, data).join(', ');
  return tx('cluster.label', { count: item.marks.length });
}
