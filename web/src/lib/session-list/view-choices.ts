/* the widget menu */
import type { MenuNode } from '../drawer-tabs/add-component-menu';
import { DENSITY_MODES, setDensity, type DensityMode } from '../drawer-tabs/density-mode';
import { archivedShown, setArchivedShown } from '../drawer/archived-visibility';
import { closedShown, setClosedShown } from '../drawer/closed-visibility.svelte';
import { emptySectionsHidden, setEmptySectionsHidden } from '../drawer/empty-sections.svelte';
import { leadersShown, setLeadersShown } from '../drawer/leader-visibility';
import { setStatsShown, statsShown } from '../drawer/stats-visibility.svelte';
import { t } from '../i18n/index.svelte';
import { swarmIsOn } from '../swarm-switch/control.svelte';
import { readViewState, viewState } from './view-state.svelte';

export interface ViewChoice {
  readonly id: string;
  readonly labelKey: string;
  readonly titleKey?: string;
  readonly kind: 'choice' | 'switch';
  readonly group: 'density' | 'stats' | 'rows' | 'sections';
  on(): boolean;
  run(): void;
  available?(): boolean;
}

const DENSITY_IDS: Readonly<Record<DensityMode, string>> = { compact: 'density-compact', cozy: 'density-cozy', detailed: 'density-detailed' };

const DENSITY_CHOICES: readonly ViewChoice[] = DENSITY_MODES.map((mode) => ({
  id: DENSITY_IDS[mode],
  labelKey: `drawer.density.${mode}`,
  kind: 'choice',
  group: 'density',
  on: () => viewState.density === mode,
  run: () => {
    setDensity(mode);
    readViewState();
  },
}));

export const VIEW_CHOICES: readonly ViewChoice[] = [
  ...DENSITY_CHOICES,
  { id: 'show-stats', labelKey: 'drawer.density.show_stats', kind: 'switch', group: 'stats', on: () => statsShown() !== false, run: () => setStatsShown(statsShown() === false) },
  {
    id: 'show-leaders',
    labelKey: 'drawer.density.show_leaders',
    titleKey: 'drawer.density.show_leaders_title',
    kind: 'switch',
    group: 'rows',
    available: swarmIsOn,
    on: () => viewState.leaders,
    run: () => {
      setLeadersShown(!leadersShown());
      readViewState();
    },
  },
  {
    id: 'show-archived',
    labelKey: 'drawer.density.show_archived',
    kind: 'switch',
    group: 'rows',
    on: () => viewState.archived,
    run: () => {
      setArchivedShown(!archivedShown());
      readViewState();
    },
  },
  { id: 'show-closed', labelKey: 'drawer.density.show_closed', kind: 'switch', group: 'rows', on: () => closedShown(), run: () => setClosedShown(!closedShown()) },
  { id: 'hide-empty-sections', labelKey: 'drawer.density.hide_empty_sections', kind: 'switch', group: 'sections', on: () => emptySectionsHidden(), run: () => setEmptySectionsHidden(!emptySectionsHidden()) },
];

export function viewMenuNodes(): MenuNode[] {
  const offered = VIEW_CHOICES.filter((choice) => choice.available?.() !== false);
  return offered.map((choice, at) => ({
    id: choice.id,
    label: t(choice.labelKey),
    ...(choice.titleKey ? { title: t(choice.titleKey) } : {}),
    ...(choice.kind === 'switch' ? { toggle: true } : {}),
    checked: choice.on(),
    ...(at > 0 && offered[at - 1]!.group !== choice.group ? { sep: true } : {}),
    run: choice.run,
  }));
}
