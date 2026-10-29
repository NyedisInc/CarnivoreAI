import * as Density from './density';
import * as StatsVisibility from './stats-visibility.svelte';
import * as SectionVisibility from './section-visibility.svelte';
import * as ClosedVisibility from './closed-visibility.svelte';

export interface FlipTarget {
    refreshNow(): Promise<void> | undefined;
    repaint(): void;
}

export function reapplyForViewClass(ctrl: FlipTarget): void {
    Density.init();
    StatsVisibility.init();
    SectionVisibility.init();
    ClosedVisibility.init();
    if (ctrl.refreshNow() === undefined) ctrl.repaint();
}
