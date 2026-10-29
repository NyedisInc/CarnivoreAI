
import type { Component } from 'svelte';
import { metaFor } from '../../engine/meta';
import type { CellProps } from '../../lib/cell';
import Pipeline from '../pipeline/Cell.svelte';
import ScheduledRuns from './ScheduledRuns.svelte';
import SentList from './SentList.svelte';
import LogViewer from './LogViewer.svelte';

export const meta = metaFor('developer');

export interface Monitor {
  id: string;
  labelKey: string;
  component: Component<CellProps>;
}

export const MONITORS: readonly Monitor[] = [
  { id: 'pipeline', labelKey: 'opscenter.cell.developer.tab.pipeline', component: Pipeline as unknown as Component<CellProps> },
  { id: 'scheduled', labelKey: 'opscenter.cell.developer.tab.scheduled', component: ScheduledRuns as unknown as Component<CellProps> },
  { id: 'sent', labelKey: 'opscenter.cell.developer.tab.sent', component: SentList as unknown as Component<CellProps> },
  { id: 'log', labelKey: 'opscenter.cell.developer.tab.log', component: LogViewer as unknown as Component<CellProps> },
];
