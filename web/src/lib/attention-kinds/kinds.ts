import { icons } from '../../opscenter/ui/icons';
import type { AlertSourceEntry } from '../app-alerts/alerts-model';

export const APPROVALS_KIND = 'approvals';

export const TASK_MANAGER_KIND = 'huddle';

export const AUTOMATIONS_KIND = 'automations';

export const OTHER_KIND = 'other';

export type KindOrigin = 'approval' | 'huddle' | 'automation' | 'alert';

export interface AttentionKind {
  id: string;
  labelKey: string;
  icon: string;
  origin: KindOrigin;
  route: string;
  topics: readonly string[];
}

const FALLBACK_ICON = 'bell';

const BUILT_IN: readonly AttentionKind[] = [
  { id: APPROVALS_KIND, labelKey: 'attention.kind.approvals', icon: 'check-circle', origin: 'approval', route: '/approvals', topics: ['approvals'] },
  { id: TASK_MANAGER_KIND, labelKey: 'attention.kind.task_manager', icon: 'chat', origin: 'huddle', route: '/cplugs/huddle/aggregate', topics: ['cplug.huddle.delta', 'cplug.huddle.list'] },
  { id: AUTOMATIONS_KIND, labelKey: 'attention.kind.automations', icon: 'clock', origin: 'automation', route: '/automations/runs', topics: ['automations', 'automation_runs'] },
];

export function alertKindId(labelKey: string | null | undefined): string {
  const tail = (labelKey ?? '').split('.').pop() ?? '';
  const clean = tail.toLowerCase().replace(/[^a-z0-9_]/g, '_').slice(0, 20);
  return `alert_${clean || OTHER_KIND}`;
}

export function builtInKinds(): AttentionKind[] {
  return [...BUILT_IN];
}

export function attentionKinds(catalog: readonly AlertSourceEntry[]): AttentionKind[] {
  const senders: AttentionKind[] = catalog.map((entry) => ({
    id: alertKindId(entry.label_key),
    labelKey: entry.label_key,
    icon: entry.icon in icons ? entry.icon : FALLBACK_ICON,
    origin: 'alert',
    route: '/alerts',
    topics: ['app_alert.raised', 'app_alert.updated', 'app_alert.resolved'],
  }));
  return [...BUILT_IN, ...senders];
}
