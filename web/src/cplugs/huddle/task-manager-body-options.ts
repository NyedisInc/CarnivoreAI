
import type { TaskState } from '../sdk/ui';

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
}

export const DEFAULT_BODY_OPTIONS: Readonly<BodyOptions> = Object.freeze({ completedKeys: true, sendInAddRow: false, issueLink: true, tabbedDetail: false, replySplit: false, subtasks: true, drawerIcons: false, taskWrapper: false, baseFields: false, holdWhileLooking: false, scheduleBlocks: true });

export const BODY_OPTIONS: unique symbol = Symbol('task-manager-body-options');
