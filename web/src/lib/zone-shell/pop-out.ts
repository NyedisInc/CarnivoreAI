import type { WidgetManifest } from '../../opscenter/widgets/types';
import type { SessionScope } from '../../opscenter/widgets/session-scope';
import { viewOfPlacement } from '../../opscenter/widgets/views';
import { isWidgetId, openWidgetPopout, type PopoutPlacement } from '../../popout/popout';

export function popOutFor(
  manifest: Pick<WidgetManifest, 'id' | 'fits' | 'views'>,
  cell: Pick<WidgetManifest, 'instancing'>,
  view: string | null | undefined,
  scope: SessionScope | null,
  options: Readonly<Record<string, unknown>> | undefined,
): (() => void) | null {
  if (cell.instancing !== 'singleton' || !isWidgetId(manifest.id)) return null;
  const placement: PopoutPlacement = {
    sessionId: scope?.sessionId ?? null,
    view: viewOfPlacement(manifest, view)?.id ?? null,
    options: options as PopoutPlacement['options'],
  };
  return () => void openWidgetPopout(manifest.id, manifest.fits, window, placement);
}
