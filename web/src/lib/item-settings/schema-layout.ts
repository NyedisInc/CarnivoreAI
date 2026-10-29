import type { EnumSettingField, SettingsMatrix, WidgetSettingsSchema } from '../../opscenter/widgets/types';

export const SEGMENTED_MAX = 4;

export interface DrawnGroup {
  labelKey: string | null;
  fields: readonly string[];
  matrix?: SettingsMatrix;
}

export function settingGroups(schema: WidgetSettingsSchema): DrawnGroup[] {
  const keys = Object.keys(schema.fields);
  if (!schema.groups?.length) return keys.length ? [{ labelKey: null, fields: keys }] : [];
  return schema.groups.map((group) => ({
    labelKey: group.labelKey,
    fields: group.fields.filter((key) => key in schema.fields),
    ...(group.matrix ? { matrix: group.matrix } : {}),
  }));
}

export function controlOf(field: EnumSettingField): 'segmented' | 'select' {
  return field.control ?? (field.options.length <= SEGMENTED_MAX ? 'segmented' : 'select');
}
