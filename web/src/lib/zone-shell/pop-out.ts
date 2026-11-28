import type { WidgetManifest } from '../../opscenter/widgets/types';
import type { SessionScope } from '../../opscenter/widgets/session-scope';
import { viewOfPlacement } from '../../opscenter/widgets/views';
import { panels } from '../../opscenter/engine/plugin-kinds';
import { isWidgetId, openWidgetPopout, parseWidgetTarget, type PopoutPlacement } from '../../popout/popout';
import { popoutWidgetFor } from '../../plugins/host/popout-widgets';

export function popOutFor(
  manifest: Pick<WidgetManifest, 'id' | 'fits' | 'views'>,
  cell: Pick<WidgetManifest, 'instancing'>,
  view: string | null | undefined,
  scope: SessionScope | null,
  options: Readonly<Record<string, unknown>> | undefined,
  pinned = false,
  target: string | null | undefined = null,
): (() => void) | null {
  let popId = manifest.id;
  if (manifest.id.startsWith('core.')) {
    if (cell.instancing !== 'singleton' || !isWidgetId(manifest.id)) return null;
  } else {
    popId = target ? `${manifest.id}:${target}` : manifest.id;
    if (!isWidgetId(popId)) return null;
    const { kind } = parseWidgetTarget(popId);
    if (panels().canPopOut?.(kind) !== true && popoutWidgetFor(popId)?.enabled !== true) return null;
  }
  const placement: PopoutPlacement = {
    sessionId: scope?.sessionId ?? null,
    view: viewOfPlacement(manifest, view)?.id ?? null,
    options: options as PopoutPlacement['options'],
    ...(pinned ? { pinned: true } : {}),
  };
  return () => void openWidgetPopout(popId, manifest.fits, window, placement);
}
