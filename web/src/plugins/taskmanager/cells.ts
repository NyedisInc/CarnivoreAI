/* the Task Manager */
import type { CplugCell } from '../sdk';
import Mk2 from './mk2/Cell.svelte';
import Mk2All from './mk2-all/Cell.svelte';

export const taskManagerCells: CplugCell[] = [
  { id: 'task-manager-mk2', component: Mk2 },
  { id: 'task-manager-mk2-all', component: Mk2All },
];
