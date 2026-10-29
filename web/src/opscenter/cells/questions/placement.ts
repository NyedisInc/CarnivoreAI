import { t } from '../../../lib/i18n/index.svelte';
import type { WidgetSettingField, WidgetSettingsSchema } from '../../widgets/types';
import { registerPlacementOptions, type PlacementHead, type PlacementOptions } from '../../widgets/placement-options';
import { builtInKinds } from '../../../lib/attention-kinds/kinds';
import { ALL_OPTION, COMBINED_ICON, checkedKinds, isRetiredOption, kindOptionKey } from './sources';

const ALL_LABEL_KEY = 'opscenter.cell.questions.setting.all';

const GROUP_KEY = 'opscenter.cell.questions.setting.group.show';

export function questionsSchema(): WidgetSettingsSchema {
  const fields: Record<string, WidgetSettingField> = { [ALL_OPTION]: { kind: 'boolean', labelKey: ALL_LABEL_KEY, default: true } };
  for (const kind of builtInKinds()) {
    fields[kindOptionKey(kind.id)] = { kind: 'boolean', labelKey: kind.labelKey, default: true, disabledWhen: ALL_OPTION };
  }
  return { version: 1, fields, groups: [{ labelKey: GROUP_KEY, fields: Object.keys(fields) }] };
}

export function questionsHead(options: PlacementOptions): PlacementHead | null {
  if (options[ALL_OPTION] !== false) return { icon: COMBINED_ICON, title: t('opscenter.cell.questions.title') };
  const checked = checkedKinds(options);
  if (checked.length === 1) return { icon: checked[0]!.icon, title: t(checked[0]!.labelKey) };
  return checked.length > 1 ? { icon: COMBINED_ICON, title: t('opscenter.cell.questions.title') } : null;
}

registerPlacementOptions('core.questions', { schema: questionsSchema, head: questionsHead, isRetiredKey: isRetiredOption });
