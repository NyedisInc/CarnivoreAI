import type { Message } from './api';

type Translate = (key: string, params?: Record<string, unknown>) => string;

export interface LogRowPlan {
    readonly statusText: string;
    readonly retry: boolean;
    readonly hint: string | null;
}

export const canRetry = (m: Pick<Message, 'status' | 'direction'>): boolean => m.status === 'failed' && m.direction === 'in';

export function planLogRow(t: Translate, m: Pick<Message, 'status' | 'direction' | 'reason'>): LogRowPlan {
    return {
        statusText: `${t(`messaging.ui.status.${m.status}`)}${m.reason ? ` (${m.reason})` : ''}`,
        retry: canRetry(m),
        hint: m.status === 'unconfirmed' ? t('messaging.ui.log.unconfirmed_hint') : null,
    };
}
