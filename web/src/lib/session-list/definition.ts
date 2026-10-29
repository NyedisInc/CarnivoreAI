import { defineWidget } from '../../opscenter/widgets/shell/define-widget.svelte';
import { DENSITY_MODES, currentDensity, setDensity, type DensityMode } from '../drawer-tabs/density-mode';
import { SESSION_LIST_WIDGET } from '../sidebar-widgets/widget-ids';
import { VIEW_CHOICES } from './view-choices';

const isDensity = (value: unknown): value is DensityMode => DENSITY_MODES.includes(value as DensityMode);

export const SESSION_LIST_WIDGET_DEF = defineWidget({
  id: SESSION_LIST_WIDGET,
  scope: 'global',
  actions: VIEW_CHOICES.map(({ id, labelKey, kind, group }) => ({ id, labelKey, kind, group })),
  state: { density: { home: 'shared', default: 'compact' as DensityMode, valid: isDensity, via: { read: currentDensity, write: (value: unknown) => { if (isDensity(value)) setDensity(value); } } } },
});
