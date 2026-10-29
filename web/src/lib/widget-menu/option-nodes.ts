import type { MenuNode } from '../drawer-tabs/add-component-menu';
import type { WidgetManifest, WidgetSettingField, WidgetSettingsSchema } from '../../opscenter/widgets/types';
import { categoryKey } from '../../opscenter/layout-editor/drawer-model';
import { hasViews, viewOfPlacement } from '../../opscenter/widgets/views';
import { fieldDisabled, resolveValue, type SettingValue } from '../item-settings/api';
import { hasPlacementOptions, type PlacementOptions } from '../../opscenter/widgets/placement-options';
import { viewMenuNodes } from './view-nodes';
import { isScopeSwitch } from '../../opscenter/widgets/views';
import { CORE_ID } from './model';

export function settingFields(cell: Pick<WidgetManifest, 'settings'>): [string, WidgetSettingField][] {
  return Object.entries(cell.settings?.fields ?? {});
}

export function hasOptions(manifest: Pick<WidgetManifest, 'views'> & { id?: string }, cell: Pick<WidgetManifest, 'settings'>, editing: boolean): boolean {
  return (manifest.id !== undefined && hasPlacementOptions(manifest.id)) || (editing && (hasViews(manifest) || settingFields(cell).length > 0));
}

export interface OptionNodesInput {
  manifest: WidgetManifest;
  cell: WidgetManifest;
  view: string | null | undefined;
  values: Readonly<Record<string, unknown>> | undefined;
  translate: (key: string) => string;
  pickView: (view: string) => void;
  write: (key: string, value: SettingValue) => void;
  openForm: () => void;
  placement?: {
    schema: Pick<WidgetSettingsSchema, 'fields'>;
    values: PlacementOptions;
    write: (key: string, value: boolean) => void;
  };
}

export function lookNodes(input: OptionNodesInput): MenuNode[] {
  return hasViews(input.manifest) ? viewMenuNodes(input.manifest, input.view, input.translate, input.pickView) : [];
}

export function copyOptionNodes(input: Pick<OptionNodesInput, 'placement' | 'translate'>, heading?: string): MenuNode[] {
  const placement = input.placement;
  if (!placement) return [];
  const nodes: MenuNode[] = [];
  for (const [key, field] of Object.entries(placement.schema.fields)) {
    if (field.kind !== 'boolean') continue;
    const on = resolveValue(field, placement.values[key]) === true;
    const label = input.translate(field.labelKey);
    const blocked = fieldDisabled(placement.schema, key, placement.values) ? label : undefined;
    nodes.push({ id: `option:${key}`, label, checked: on, toggle: true, keepOpen: true, blocked, run: () => placement.write(key, !on) });
  }
  return heading && nodes.length > 0 ? [{ id: 'copy-options', label: heading, children: nodes }] : nodes;
}

export function settingNodes(input: OptionNodesInput): MenuNode[][] {
  const ticks: MenuNode[] = [];
  const branches: MenuNode[][] = [];
  let needsForm = false;
  for (const [key, field] of settingFields(input.cell)) {
    const current = resolveValue(field, input.values?.[key]);
    if (field.kind === 'boolean') {
      ticks.push({ id: key, label: input.translate(field.labelKey), checked: current === true, toggle: true, run: () => input.write(key, current !== true) });
    } else if (field.kind === 'enum') {
      branches.push([{
        id: key,
        label: input.translate(field.labelKey),
        children: field.options.map((option) => ({ id: `${key}:${option}`, label: input.translate(`${field.labelKey}.option.${option}`), checked: current === option, run: () => input.write(key, option) })),
      }]);
    } else needsForm = true;
  }
  const form: MenuNode[] = needsForm ? [{ id: CORE_ID.settings, label: input.translate('widgets.menu.settings'), icon: 'settings', run: input.openForm }] : [];
  return [ticks, ...branches, form].filter((group) => group.length > 0);
}

export function railTip(manifest: WidgetManifest, view: string | null | undefined, translate: (key: string) => string, name?: string): string {
  const picked = viewOfPlacement(manifest, view);
  return [name ?? translate(manifest.titleKey), picked ? translate(picked.titleKey) : translate(categoryKey(manifest.category)), translate('session_rail.tip.options')].join('\n');
}

export function scopeSwitchNodes(
  manifest: Pick<WidgetManifest, 'views'> | undefined,
  view: string | null | undefined,
  translate: (key: string) => string,
  pick: (view: string) => void,
): MenuNode[] {
  return manifest && isScopeSwitch(manifest) ? viewMenuNodes(manifest, view, translate, pick) : [];
}
