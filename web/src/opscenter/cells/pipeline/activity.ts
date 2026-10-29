import type { KeyArea, KeyQueue, RunningKey } from '../../../lib/pipeline-status/api';
import { pluginNameKey } from '../../../lib/pipeline-status/model';
import { nextWords, runTimeWords } from '../../lib/run-chart';
import { cap, type ActivityRow, type Capped } from '../../lib/run-queue';
import { pluginWords } from './model';

export type Translate = (key: string, params?: Record<string, string | number>) => string;

export function keyArea(key: KeyArea, t: Translate): string {
  if (key.scope !== 'machine') {
    const named = key.session || key.project;
    if (named) return named;
  }
  return key.conversation || t('pipeline.chart.machine');
}

export function pipelineRunning(running: readonly RunningKey[], nowS: number, t: Translate): ActivityRow[] {
  return running.map((key) => ({
    id: `${key.kind}:${key.plugin}`,
    name: pluginWords(t, key.plugin, key.kind === 'rebuild'),
    area: keyArea(key, t),
    time: runTimeWords(Math.max(0, nowS - key.started_at) * 1000),
  }));
}

export function pipelineQueue(queue: KeyQueue, nowS: number, t: Translate): Capped<ActivityRow> {
  const rows = queue.items.map((key, index): ActivityRow => {
    const due = key.due_at !== null && key.due_at > nowS ? key.due_at - nowS : null;
    return {
      id: `${index}:${key.trigger}:${key.marked_at}`,
      name: key.plugins.length ? key.plugins.map((id) => t(pluginNameKey(id))).join(', ') : t('pipeline.queue.all_plugins'),
      area: keyArea(key, t),
      time: due !== null
        ? t('pipeline.queue.retry', { time: nextWords(due) })
        : t('opscenter.activity.waited', { time: runTimeWords(Math.max(0, nowS - key.marked_at) * 1000) }),
      ...(due !== null ? { tone: 'wait' as const } : {}),
    };
  });
  return cap(rows, queue.total);
}
