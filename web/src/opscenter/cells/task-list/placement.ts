import type { WidgetSettingField, WidgetSettingsSchema } from '../../widgets/types';
import { registerPlacementOptions } from '../../widgets/placement-options';
import { BADGE_STATUSES } from '../../../cplugs/huddle/task-manager-prefs.svelte';
import { badgeLabelKey } from '../../../cplugs/huddle/task-manager-badge-menu';
import { statusOption } from './model';

export const LIST_MENU_HEADING = 'opscenter.cell.task_list.menu.heading';

export function taskManagerListSchema(): WidgetSettingsSchema {
  const fields: Record<string, WidgetSettingField> = {};
  for (const status of BADGE_STATUSES) fields[statusOption(status)] = { kind: 'boolean', labelKey: badgeLabelKey(status), default: true };
  return { version: 1, fields };
}

registerPlacementOptions('core.task-list', { schema: taskManagerListSchema, menuHeadingKey: LIST_MENU_HEADING });
