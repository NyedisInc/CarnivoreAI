import { t } from '../../i18n/index.svelte';
import type { Automation } from '../api';
import { codeWords } from '../logic/words';

export function metaLine(a: Automation): string {
  const kind = t(`automations.simple.kind.${a.target.kind}`);
  const label = kind.startsWith('automations.simple.kind.') ? a.target.kind : kind;
  if (a.target.kind === 'agent') {
    const folder = String(a.target.folder ?? '').trim();
    return [
      label,
      folder ? t('automations.simple.card.meta_folder', { folder }) : '',
      t('automations.simple.card.meta_model', {
        model: a.target.model || t('automations.simple.card.model_default'),
        effort: a.target.effort || t('automations.simple.card.model_default'),
      }),
    ]
      .filter(Boolean)
      .join(' · ');
  }
  const what = a.target.kind === 'recipe' && typeof a.target.recipe === 'string' ? codeWords('automations.recipe', `${a.target.recipe}.label`) : '';
  return [label, what, t(a.spends ? 'automations.simple.card.plan_uses' : 'automations.simple.card.plan_none')].filter(Boolean).join(' · ');
}
