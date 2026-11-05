import { contextGauge, contextPercentSpoken } from '../session-stats/context-gauge';
import { t } from '../i18n/index.svelte';
import type { SidebarRow } from './legacy';

export interface ContextPlan {
    pct: number;
    scale: number;
    label: string;
}

export function contextPlan(r: SidebarRow): ContextPlan | null {
    const gauge = contextGauge(r.running_context_used_pct);
    if (gauge === null) return null;
    return { ...gauge, label: t('sidebar.row.context.label', { percent: contextPercentSpoken(gauge.pct) }) };
}
