
import { readChoice, writeChoice } from '../../../lib/ui/prefs.svelte';

export type ThemesCellView = 'favorites' | 'all';

export const THEMES_CELL_VIEW_KEY = 'carnivore.themes.cellView';

const VIEWS: readonly ThemesCellView[] = ['favorites', 'all'];

class CellView {
    value = $state<ThemesCellView>(readChoice(THEMES_CELL_VIEW_KEY, VIEWS, 'favorites'));

    set(next: ThemesCellView): void {
        this.value = next;
        writeChoice(THEMES_CELL_VIEW_KEY, next);
    }
}

export const themesCellView = new CellView();
