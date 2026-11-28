import type { CplugManifest } from '../sdk';

const KEEP_WIDGETS = 'widgets';

export function widgetKind(cplug: { id: string; manifest: CplugManifest }, name: string): string {
  const old = cplug.manifest.renamed_from;
  const kept = !!old && (cplug.manifest.renamed_from_keeps ?? []).includes(KEEP_WIDGETS);
  return kept && name.startsWith(`${old}.`) ? name : `${cplug.id}.${name}`;
}
