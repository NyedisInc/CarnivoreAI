import { expect, it } from 'vitest';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { dizModel } from './diz-model';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };

it('the detail pane credits the publisher and carries no publisher/name id line', () => {
    const card = { id: 'nyedis/11-stars', kind: 'plugin', verdict: 'unreviewed', author: 'nyedis' };
    const m = dizModel({ item: { id: card.id }, card, held: [], ratings: null, installs: 0, offline: false, origin: 'http://x', palette: null } as never, (k, p) => i18n.t(k, p));
    expect(m.byLine).toBe('by nyedis');
    expect(m.byLine).not.toContain('nyedis/11-stars');
});

it('every kind the catalog serves has a kind label, cplug included (a missing key logs an i18n error on #elite)', () => {
    for (const kind of ['skill', 'theme', 'mod', 'plugin', 'cplug', 'loadout']) {
        expect(i18n.t(`warez.elite.kind.${kind}`)).not.toBe(`warez.elite.kind.${kind}`);
    }
    expect(i18n.t('warez.elite.kind.cplug')).toBe('CPL');
});
