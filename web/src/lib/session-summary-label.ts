import { sessionSummaryLabel } from '../../../client/js/labels/session-summary.js';
import { t as reactiveT } from './i18n/index.svelte';

export interface SessionSummary {
    bucket?: string;
    total?: number;
    unreadCount?: number;
}

export type Translate = (key: string, params?: Record<string, unknown> | null) => string;

export function summaryLabel(summary: SessionSummary, t: Translate = reactiveT): string {
    return sessionSummaryLabel(summary, t) as string;
}
