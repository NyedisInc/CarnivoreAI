import type { SettingsMatrix, SettingsMatrixRow, WidgetSettingField, WidgetSettingsSchema } from '../../opscenter/widgets/types';
import type { SettingValue } from '../item-settings/api';

export interface BeastRule {
  id: string;
  kind: string;
  off: boolean;
  on: boolean;
  mode: string;
  handled_now: boolean;
  cells: { off: string; on: string };
  risk?: string;
}

export interface BeastRules {
  rows: readonly BeastRule[];
  cells: Readonly<Record<string, { value: boolean; default: boolean }>>;
  trust_scope: string;
  trust_scopes: readonly string[];
  unconfirmed_rows: readonly string[];
  always_asks: readonly string[];
}

export const TRUST_SCOPE_KEY = 'trustScope';

export function gridMatrix(rules: BeastRules): SettingsMatrix {
  const rows: SettingsMatrixRow[] = rules.rows.map((row) => {
    const ask = rules.unconfirmed_rows.includes(row.id);
    return {
      labelKey: `beast.settings.row.${row.id}`,
      hintKey: `beast.settings.row.${row.id}_help`,
      fields: [row.cells.off, row.cells.on],
      ...(ask ? { confirm: { [row.cells.off]: `beast.settings.confirm.${row.id}_off` } } : {}),
    };
  });
  const locked: SettingsMatrixRow[] = rules.always_asks.map((id) => ({
    labelKey: `beast.settings.locked.${id}`,
    hintKey: `beast.settings.locked.${id}_help`,
    locked: true as const,
  }));
  return { columns: ['beast.settings.column.off', 'beast.settings.column.on'], rows: [...rows, ...locked] };
}

export function gridFields(rules: BeastRules): Record<string, WidgetSettingField> {
  const fields: Record<string, WidgetSettingField> = {};
  for (const row of rules.rows) {
    for (const key of [row.cells.off, row.cells.on]) {
      fields[key] = { kind: 'boolean', labelKey: `beast.settings.row.${row.id}`, default: rules.cells[key]?.default ?? false };
    }
  }
  return fields;
}

export function gridValues(rules: BeastRules): Record<string, SettingValue> {
  return Object.fromEntries(Object.entries(rules.cells).map(([key, cell]) => [key, cell.value]));
}

export function scopeSchema(rules: BeastRules): WidgetSettingsSchema {
  return {
    version: 1,
    fields: {
      [TRUST_SCOPE_KEY]: {
        kind: 'enum',
        labelKey: 'beast.settings.trust_scope',
        hintKey: 'beast.settings.trust_scope_help',
        options: rules.trust_scopes,
        default: 'projects',
        control: 'segmented',
      },
    },
  };
}
