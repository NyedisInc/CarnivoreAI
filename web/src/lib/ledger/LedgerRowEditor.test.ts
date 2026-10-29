/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import LedgerRowEditor from './LedgerRowEditor.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';

const i18n = createI18n();
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

let app: unknown = null;

afterEach(() => {
    if (app) unmount(app as never);
    app = null;
    document.body.innerHTML = '';
});

describe('the account editor', () => {
    test('id, provider, login area and config dir are text, not fields', () => {
        app = mount(LedgerRowEditor, {
            target: document.body,
            props: {
                stored: {
                    id: 'work-1',
                    name: 'Work',
                    provider: 'claude',
                    managed: true,
                    claude_config_dir: '/Users/x/.carnivore/accounts/work-1',
                } as never,
                label: 'Work',
                onSave: () => {},
                onCancel: () => {},
                busy: false,
                refusal: null,
                t,
            },
        });
        flushSync();
        const inputs = [...document.querySelectorAll('input')];
        const ids = inputs.map((i) => i.id);
        expect(ids).toContain('ledger-edit-name');
        expect(ids).toContain('ledger-edit-short-name');
        for (const gone of ['id', 'provider', 'managed', 'path']) {
            expect(document.getElementById(`ledger-edit-${gone}`)).toBeNull();
        }
        expect(document.querySelectorAll('input[readonly]')).toHaveLength(0);
        const values = [...document.querySelectorAll('dd')].map((d) => d.textContent?.trim());
        expect(values).toContain('work-1');
        expect(values).toContain('claude');
        expect(values).toContain('/Users/x/.carnivore/accounts/work-1');
        expect(document.querySelector('dd[title]')).toBeNull();
    });
});
