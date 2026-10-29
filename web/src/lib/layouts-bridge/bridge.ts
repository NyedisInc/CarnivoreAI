
import { addMemberAndWake } from './wake-on-add';
import {
  deleteLayout, layoutByUuid, layouts, layoutsUnavailable, renameLayout,
  reorderLayouts, setLayoutStyle, start, type Layout,
} from './api.svelte';

start();

export const layoutsBridge = {
  list: (): Layout[] => layouts.data ?? [],
  get: (uuid: string): Layout | null => layoutByUuid(uuid),
  isUnavailable: (): boolean => layoutsUnavailable.value,
  rename: renameLayout,
  delete: deleteLayout,
  reorder: reorderLayouts,
  setStyle: setLayoutStyle,
  addMember: addMemberAndWake,
};
