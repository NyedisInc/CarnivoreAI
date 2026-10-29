import { describe, expect, test } from 'vitest';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { launchedWithText } from './running-row';

const i18n = createI18n({ locale: 'en' }) as { t(k: string, p?: Record<string, unknown> | null): string };
const t = (k: string, p?: Record<string, unknown> | null): string => i18n.t(k, p);

describe('launchedWithText', () => {
    test('reads label, account and model, in that order', () => {
        expect(launchedWithText({ profile: 'c', label: 'claude work', account: 'work', model: 'opus' }, t)).toBe('launched with: claude work · work · opus');
    });

    test('leaves out what is not known and shows nothing without a record', () => {
        expect(launchedWithText({ profile: 'c', label: 'claude', account: null, model: null }, t)).toBe('launched with: claude');
        expect(launchedWithText(null, t)).toBeNull();
        expect(launchedWithText(undefined, t)).toBeNull();
        expect(launchedWithText({ profile: 'c', label: '  ' }, t)).toBeNull();
    });
});
