import { registerPluginBinding } from '../../opscenter/cells/registry';
import { registerPluginKind } from '../../opscenter/engine/plugin-kinds';
import type { PluginKind, SlotId } from '../../opscenter/engine/types';
import { registerPluginDeclaration } from '../../opscenter/widgets/fit-declarations';
import { registerPluginManifest } from '../../opscenter/widgets/core-manifests';
import { BUILTIN_CPLUGS } from '../builtin';
import type { CplugWeb } from '../sdk';
import { cplugEnabled } from './enablement.svelte';

export function registerCplugWidgets(cplug: CplugWeb): string[] {
  return (cplug.widgets ?? []).map((widget) => {
    const kind = `${cplug.id}.${widget.name}` as PluginKind;
    const block = cplug.manifest.widgets?.[widget.name];
    if (!block) throw new Error(`cplug ${cplug.id}: widget ${widget.name} has no widgets.${widget.name} block in cplug.json`);
    registerPluginKind(kind, { ...widget.meta, id: kind as SlotId });
    registerPluginDeclaration({ id: kind, instancing: block.instancing, fits: block.fits });
    registerPluginManifest(kind, { ...widget.meta, id: kind as SlotId }, widget.extras, cplug.manifest.version);
    registerPluginBinding(kind, { component: widget.component });
    return kind;
  });
}

export function registerEnabledWidgets(cplugs: readonly CplugWeb[] = BUILTIN_CPLUGS): void {
  for (const cplug of cplugs) if (cplugEnabled(cplug.manifest)) registerCplugWidgets(cplug);
}
