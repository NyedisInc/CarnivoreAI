import { scaleStep } from '../../../../client/js/labels/usage-panel.js';
import { t } from '../i18n/index.svelte';
import type { SidebarRow } from './legacy';

export interface ContextPlan {
    pct: number;
    scale: number;
    label: string;
}

/* label: ' */
export function contextPlan(r: SidebarRow): ContextPlan | null {
    const raw = r.running_context_used_pct;
    if (typeof raw !== 'number' || !Number.isFinite(raw)) return null;
    const pct = Math.min(100, Math.max(0, raw));
    const scale = scaleStep(pct) as number | null;
    if (scale === null) return null;
    return { pct, scale, label: t('sidebar.row.context.label', { percent: Math.round(pct) }) };
}
