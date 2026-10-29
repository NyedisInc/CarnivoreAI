import { describe, expect, it } from 'vitest';
import type { Translate } from '../sessions/types';
import type { SkillLocationRow } from '../skills-page/skills-types';
import { originOf } from './skill-words';

const t: Translate = (key, params) => `${key}:${JSON.stringify(params ?? {})}`;

describe('originOf', () => {
    it('names a plugin, system and foreign copy', () => {
        expect(originOf({ scope: 'plugin', plugin: 'p' } as unknown as SkillLocationRow, t)).toContain('origin_plugin');
        expect(originOf({ scope: 'system' } as unknown as SkillLocationRow, t)).toContain('origin_system');
        expect(originOf({ scope: 'user', managed: null } as unknown as SkillLocationRow, t)).toContain('origin_foreign');
    });
    it('flags a catalog copy with an update', () => {
        const loc = { scope: 'user', managed: { source: 'ledger', update_available: true } } as unknown as SkillLocationRow;
        expect(originOf(loc, t)).toContain('origin_catalog_update');
    });
});
