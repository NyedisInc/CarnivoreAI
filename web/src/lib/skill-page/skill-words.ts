import { targetFile, type ContextChoice } from '../skills-page/skills-model';
import type { SkillGroupRow, SkillLocationRow } from '../skills-page/skills-types';
import type { Translate } from '../sessions/types';
import { deciderOf } from './model';

type Harness = 'claude' | 'codex';

export function whyNot(group: SkillGroupRow, harness: Harness, t: Translate): string {
    const loc = deciderOf(group, harness);
    if (harness === 'codex' && loc && loc.toggle.kind !== 'none' && !loc.read_only) return t('skills.detail.codex_global_only');
    return t('skills.detail.not_switchable', { reason: loc?.toggle.reason ?? loc?.scope ?? '' });
}

export function writesNote(context: ContextChoice, harness: Harness, t: Translate): string {
    const file = targetFile(context, harness);
    if (harness === 'codex') return t(file === 'project' ? 'skills.detail.writes_codex_project' : 'skills.detail.writes_codex_user');
    return t(file === 'local' ? 'skills.detail.writes_local' : 'skills.detail.writes_user');
}

export function originOf(loc: SkillLocationRow, t: Translate): string {
    if (loc.scope === 'plugin') return t('skills.loc.origin_plugin', { plugin: loc.plugin ?? '' });
    if (loc.scope === 'system') return t('skills.loc.origin_system');
    const managed = loc.managed;
    if (!managed) return t('skills.loc.origin_foreign');
    const params = { item: managed.item_id ?? '', version: managed.version ?? '' };
    if (managed.source === 'sidecar') return t('skills.loc.origin_sidecar', params);
    return t(managed.update_available ? 'skills.loc.origin_catalog_update' : 'skills.loc.origin_catalog', params);
}
