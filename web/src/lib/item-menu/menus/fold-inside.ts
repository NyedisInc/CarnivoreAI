import { t } from '../../i18n/index.svelte';
import { cascadeBandFold, isBandFolded } from '../../sidebar-shell/heading-fold';
import type { ItemMenuEntry } from '../entries';

export function foldInsideEntry(bandKey: string): ItemMenuEntry {
    return { label: t(isBandFolded(bandKey) ? 'sidebar.heading.unfold_inside' : 'sidebar.heading.fold_inside'), icon: 'fold', id: 'fold-inside', onPick: () => { cascadeBandFold(bandKey); } };
}
