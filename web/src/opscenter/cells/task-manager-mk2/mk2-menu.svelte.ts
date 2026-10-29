/* list, so the */
import type { ActionBindings, WidgetDefinition } from '../../widgets/shell/define-widget.svelte';
import { setAccordion, setHideCompleted, setView, taskManagerPrefs } from '../../../cplugs/huddle/task-manager-prefs.svelte';
import { completedLists, removeCompleted } from '../../../cplugs/huddle/huddle.svelte';
import { AGGREGATE } from '../../../cplugs/huddle/huddle-model';
import { openModal } from '../../../lib/modal';
import { t } from '../../../lib/i18n/index.svelte';
import Mk2DeleteClosedModal from './Mk2DeleteClosedModal.svelte';
import { countBadges, setCountsHidden } from '../../../cplugs/huddle/task-manager-status-folds.svelte';
import type { LocalStateField } from '../../widgets/shell/widget-state.svelte';
import { isSavedView, type Mk2SavedView } from './mk2-view-state.svelte';
import { isMk2State, MK2_DEFAULT_STATE } from './mk2-task-state';
import type { TaskState } from '../../../lib/base/task-wrapper';

const isBool = (value: unknown): value is boolean => typeof value === 'boolean';

const shown = (): LocalStateField<boolean> => ({ home: 'device', default: true, valid: isBool });

export const MK2_STATE = {
  'project-colors': shown(),
  'status-bar': shown(),
  view: { home: 'placement', default: null, valid: isSavedView } as LocalStateField<Mk2SavedView | null>,
  'task-state': { home: 'placement', default: MK2_DEFAULT_STATE, valid: isMk2State } as LocalStateField<TaskState>,
} as const;

export type Mk2SideState = { 'project-colors': boolean; 'status-bar': boolean; 'task-state': TaskState };

export const MK2_ACTIONS = [
  { id: 'group-by-area', labelKey: 'cplug.huddle.view.area', kind: 'switch', group: 'view' },
  { id: 'density-compact', labelKey: 'cplug.huddle.tm.state_compact', kind: 'choice', group: 'density' },
  { id: 'density-cozy', labelKey: 'cplug.huddle.tm.state_opened', kind: 'choice', group: 'density' },
  { id: 'density-detailed', labelKey: 'cplug.huddle.tm.state_detailed', kind: 'choice', group: 'density' },
  { id: 'accordion', labelKey: 'cplug.huddle.accordion', kind: 'switch', group: 'show' },
  { id: 'show-completed', labelKey: 'opscenter.cell.task_manager_mk2.show_completed', kind: 'switch', group: 'show' },
  { id: 'show-counts', labelKey: 'opscenter.cell.task_manager_mk2.show_counts', kind: 'switch', group: 'show' },
  { id: 'project-colors', labelKey: 'opscenter.cell.task_manager_mk2.project_colors', kind: 'switch', group: 'show' },
  { id: 'status-bar', labelKey: 'opscenter.cell.task_manager_mk2.status_bar', kind: 'switch', group: 'show' },
  { id: 'delete-closed', labelKey: 'opscenter.cell.task_manager_mk2.delete_closed', group: 'clean' },
] as const;

export function closedCount(view: string): number {
  return completedLists(view).reduce((n, row) => n + row.count, 0);
}

/* nothing is deleted */
export async function confirmDeleteClosed(view: string): Promise<void> {
  const count = closedCount(view);
  if (count === 0) return;
  const confirmed = await openModal(Mk2DeleteClosedModal, { count, everywhere: view === AGGREGATE });
  if (confirmed === true) await removeCompleted(view);
}

export function mk2Bindings(side: Mk2SideState, view: string): ActionBindings<WidgetDefinition<typeof MK2_ACTIONS>> {
  return {
    'group-by-area': { on: taskManagerPrefs.view === 'area', run: () => void setView(taskManagerPrefs.view === 'area' ? 'status' : 'area') },
    'density-compact': { on: side['task-state'] === 'compact', run: () => { side['task-state'] = 'compact'; } },
    'density-cozy': { on: side['task-state'] === 'opened', run: () => { side['task-state'] = 'opened'; } },
    'density-detailed': { on: side['task-state'] === 'detailed', run: () => { side['task-state'] = 'detailed'; } },
    accordion: { on: taskManagerPrefs.accordion, run: () => void setAccordion(!taskManagerPrefs.accordion) },
    'show-completed': { on: !taskManagerPrefs.hideCompleted, run: () => void setHideCompleted(!taskManagerPrefs.hideCompleted) },
    'show-counts': { on: !countBadges.hidden, run: () => setCountsHidden(!countBadges.hidden) },
    'project-colors': { on: side['project-colors'], run: () => { side['project-colors'] = !side['project-colors']; } },
    'status-bar': { on: side['status-bar'], run: () => { side['status-bar'] = !side['status-bar']; } },
    'delete-closed': { run: () => void confirmDeleteClosed(view), ...(closedCount(view) === 0 ? { blocked: t('opscenter.cell.task_manager_mk2.delete_closed_none') } : {}) },
  };
}
