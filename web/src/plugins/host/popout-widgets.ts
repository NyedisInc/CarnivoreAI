/* list, so the */
import { POPOUT_CPLUGS } from '../popout';
import type { CplugWidget } from '../sdk';
import { cplugEnablement, cplugEnabled } from './enablement.svelte';

export interface PopoutWidget {
  widget: CplugWidget;
  enabled: boolean;
}

export function popoutWidgetFor(slot: string): PopoutWidget | null {
  const kind = slot.split(':')[0] ?? '';
  for (const cplug of POPOUT_CPLUGS) {
    const widget = (cplug.widgets ?? []).find((w) => `${cplug.id}.${w.name}` === kind);
    if (widget) return { widget, enabled: cplugEnabled(cplug.manifest) };
  }
  return null;
}

export function enablementKnown(): boolean {
  return cplugEnablement.read;
}
