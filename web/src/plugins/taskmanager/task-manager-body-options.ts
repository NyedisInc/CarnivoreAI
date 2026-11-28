/* the Task Manager */

import type { TaskState } from '../sdk/ui';
import type { TaskManagerSectionKey } from './task-manager-status-sections';

export interface BodyOptions {
  completedKeys: boolean;
  sendInAddRow: boolean;
  issueLink: boolean;
  tabbedDetail: boolean;
  replySplit: boolean;
  drawerIcons: boolean;
  subtasks: boolean;
  taskWrapper: boolean;
  baseFields: boolean;
  holdWhileLooking: boolean;
  scheduleBlocks: boolean;
  readonly taskState?: TaskState;
  readonly hiddenStatuses?: readonly TaskManagerSectionKey[];
}

export const DEFAULT_BODY_OPTIONS: Readonly<BodyOptions> = Object.freeze({ completedKeys: true, sendInAddRow: false, issueLink: true, tabbedDetail: false, replySplit: false, subtasks: true, drawerIcons: false, taskWrapper: false, baseFields: false, holdWhileLooking: false, scheduleBlocks: true });

export const BODY_OPTIONS: unique symbol = Symbol('task-manager-body-options');
