import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

import { createI18n } from '../../../client/js/i18n/runtime.js';

/** Repo root, two levels up from web/src/lib. */
export const repoRoot = fileURLToPath(new URL('../../..', import.meta.url));

export interface LegacyApi {
    dotHtml(status?: unknown, signals?: unknown): string;
    ledStateFor(signals?: unknown): { inner: string; outer: string };
    ledHtml(opts?: unknown): string;
    hostOffline(row?: unknown): string | null;
    usageLimitLabel(row?: unknown): string | null;
    loginExpiredLabel(row?: unknown): string | null;
    INNER_STATES: string[];
    OUTER_STATES: string[];
}

export function legacy(): LegacyApi {
    const context: Record<string, unknown> = { console, window: {}, CloudeI18n: createI18n() };
    vm.createContext(context);
    for (const file of ['i18n/tr.js', 'status-led.js', 'session-status-ui.js']) {
        const src = fs.readFileSync(path.join(repoRoot, 'client', 'js', file), 'utf8');
        vm.runInContext(src, context);
    }
    const led = context['StatusLed'] as LegacyApi;
    const ui = (context['window'] as Record<string, unknown>)[
        'SessionStatusUI'
    ] as LegacyApi;
    return {
        dotHtml: (status, signals) => ui.dotHtml(status, signals),
        ledStateFor: (signals) => led.ledStateFor(signals),
        ledHtml: (opts) => led.ledHtml(opts),
        hostOffline: (row) => led.hostOffline(row),
        usageLimitLabel: (row) => led.usageLimitLabel(row),
        loginExpiredLabel: (row) => led.loginExpiredLabel(row),
        INNER_STATES: led.INNER_STATES,
        OUTER_STATES: led.OUTER_STATES,
    };
}
