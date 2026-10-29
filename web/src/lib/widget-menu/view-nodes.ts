import type { MenuNode } from '../drawer-tabs/add-component-menu';
import { viewOfPlacement, viewsOf } from '../../opscenter/widgets/views';
import type { WidgetManifest } from '../../opscenter/widgets/types';

export function viewMenuNodes(
  manifest: Pick<WidgetManifest, 'views'>,
  stored: string | null | undefined,
  translate: (key: string) => string,
  pick: (view: string) => void,
): MenuNode[] {
  const current = viewOfPlacement(manifest, stored)?.id;
  return viewsOf(manifest).map((view) => ({
    id: view.id,
    label: translate(view.titleKey),
    checked: view.id === current,
    run: () => pick(view.id),
  }));
}
