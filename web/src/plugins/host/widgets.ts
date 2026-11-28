import { registerPluginBinding, unregisterPluginBinding } from '../../opscenter/cells/registry';
import { registerPluginKind, unregisterPluginKind } from '../../opscenter/engine/plugin-kinds';
import type { PluginKind, SlotId } from '../../opscenter/engine/types';
import { registerPluginDeclaration, unregisterPluginDeclaration } from '../../opscenter/widgets/fit-declarations';
import { registerPluginManifest, unregisterPluginManifest } from '../../opscenter/widgets/core-manifests';
import { BUILTIN_CPLUGS } from '../builtin';
import type { CplugWeb } from '../sdk';
import { cplugEnabled } from './enablement.svelte';
import { widgetKind } from './widget-kind';

export function registerCplugWidgets(cplug: CplugWeb): string[] {
  return (cplug.widgets ?? []).map((widget) => {
    const kind = widgetKind(cplug, widget.name) as PluginKind;
    const block = cplug.manifest.widgets?.[widget.name];
    if (!block) throw new Error(`cplug ${cplug.id}: widget ${widget.name} has no widgets.${widget.name} block in carnivore.toml / cplug.json`);
    registerPluginKind(kind, { ...widget.meta, id: kind as SlotId });
    registerPluginDeclaration({ id: kind, instancing: block.instancing, fits: block.fits });
    registerPluginManifest(kind, { ...widget.meta, id: kind as SlotId }, widget.extras, cplug.manifest.version);
    registerPluginBinding(kind, { component: widget.component });
    return kind;
  });
}

export function unregisterCplugWidgets(cplug: CplugWeb): string[] {
  const removed: string[] = [];
  for (const widget of cplug.widgets ?? []) {
    const kind = widgetKind(cplug, widget.name) as PluginKind;
    const binding = unregisterPluginBinding(kind);
    const manifest = unregisterPluginManifest(kind);
    const decl = unregisterPluginDeclaration(kind);
    const regKind = unregisterPluginKind(kind);
    if (binding || manifest || decl || regKind) removed.push(kind);
  }
  return removed;
}

export function registerEnabledWidgets(cplugs: readonly CplugWeb[] = BUILTIN_CPLUGS): void {
  for (const cplug of cplugs) {
    if (cplugEnabled(cplug.manifest)) registerCplugWidgets(cplug);
    else unregisterCplugWidgets(cplug);
  }
}
