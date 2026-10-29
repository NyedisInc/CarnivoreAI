import type { Component } from 'svelte';
import { META } from '../opscenter/engine/meta';
import type { CellMeta, SlotId } from '../opscenter/engine/types';
import { REGISTRY, type RegisteredCell } from '../opscenter/cells/registry';
import { registerPluginDeclaration } from '../opscenter/widgets/fit-declarations';
import { registerFixtures } from '../opscenter/widgets/fixtures';
import type { WidgetFixtures } from '../opscenter/widgets/fixtures/types';
import { i18n } from '../lib/i18n/index.svelte';
import { registerDraftEntry } from './catalog';
import { registerDraftManifest } from '../opscenter/widgets/core-manifests';
import { ownWidgetSettingsAs } from '../lib/item-settings/settings-owner';
import type { CoreExtras } from '../opscenter/widgets/core-manifests';
import type { FitZone, WidgetCapability, WidgetCategory, WidgetLooks, WidgetSettingsSchema, WidgetType, WidgetView } from '../opscenter/widgets/types';

export interface DraftSpec {
  id: string;
  slot: string;
  title: string;
  instancing: string;
  hosts: FitZone[];
  category: WidgetCategory;
  type: WidgetType;
  capabilities: WidgetCapability[];
  fits: { sizes: string[]; anySize: boolean; max_per_surface?: number };
  cell: Omit<CellMeta, 'id'>;
  settings?: WidgetSettingsSchema | null;
  scope?: 'session' | null;
  looks?: WidgetLooks | null;
  keepAlive?: 'host' | null;
  views?: readonly WidgetView[] | null;
}

export function draftExtras(spec: DraftSpec): CoreExtras {
  return {
    category: spec.category,
    type: spec.type,
    capabilities: spec.capabilities,
    ...(spec.settings ? { settings: spec.settings } : {}),
    ...(spec.scope ? { scope: spec.scope } : {}),
    ...(spec.looks ? { looks: spec.looks } : {}),
    ...(spec.keepAlive ? { keepAlive: spec.keepAlive } : {}),
    ...(spec.views ? { views: spec.views } : {}),
  };
}

const STRING_OWNER = 'devwidgetlab';

export function registerDraftWidget(input: { spec: DraftSpec; component: Component<any>; fixtures: WidgetFixtures }): void {
  const { spec, component, fixtures } = input;
  const slot = spec.slot as SlotId;
  const titleKey = `cplug.${STRING_OWNER}.draft.${spec.slot}.title`;
  i18n.extendCatalog?.(STRING_OWNER, { [titleKey]: spec.title });
  const meta = { id: slot, ...spec.cell, titleKey } as CellMeta;
  (META as Record<string, CellMeta>)[spec.slot] = meta;
  const binding: RegisteredCell = { meta, component };
  (REGISTRY as Record<string, RegisteredCell>)[spec.slot] = binding;
  registerPluginDeclaration({ id: spec.slot, instancing: spec.instancing, fits: spec.fits });
  registerDraftManifest(spec.slot, meta, draftExtras(spec), spec.hosts.filter((host) => host === 'home' || host === 'terminal'));
  ownWidgetSettingsAs(spec.id);
  registerFixtures(spec.id, fixtures);
  registerDraftEntry({ key: spec.id, slot, zones: spec.hosts });
}
