import type { CellMeta, SlotId } from '../../engine/types';
import { SIZE_UNIT_PX } from '../../widgets/fits';
import type { CoreExtras } from '../../widgets/core-manifests';
import type { FitSize } from '../../widgets/types';
import {
  TEMPLATE_PANEL_MIN,
  PANEL_DEFAULT_HEIGHT,
  PANEL_PANE_MIN_PX,
  PANEL_PHONE_ORDER,
  PANEL_TAIL,
  PANEL_TITLE_HEIGHT,
  PANEL_WIDE_MIN_PX,
  PLUGIN_VIEW_KIND,
} from './constants';

export const PLUGIN_VIEW_TITLE_KEY = 'opscenter.cell.plugin_view.title';

export const PLUGIN_VIEW_EXTRAS: CoreExtras = { category: 'plugins', type: 'plugin', capabilities: [], remembers: [] };

export function panelMeta(kind: string, titleKey: string, min: FitSize): CellMeta {
  return {
    id: `${kind}:${PANEL_TAIL}` as SlotId,
    titleKey,
    icon: 'plug',
    iconTone: 'oc-cyan',
    showCount: false,
    chrome: 'card',
    titleHeight: PANEL_TITLE_HEIGHT,
    defaultRow: 'r1',
    defaultIndex: 0,
    defaultFr: 1,
    defaultHeight: PANEL_DEFAULT_HEIGHT,
    minPx: min.w * SIZE_UNIT_PX.w,
    minHeight: min.h * SIZE_UNIT_PX.h,
    widthStates: [{ name: 'narrow', min: 0 }, { name: 'wide', min: PANEL_WIDE_MIN_PX }],
    heightStates: [{ name: 'strip', min: 0 }, { name: 'pane', min: PANEL_PANE_MIN_PX }],
    phoneOrder: PANEL_PHONE_ORDER,
  } as CellMeta;
}

export const PLUGIN_VIEW_TEMPLATE_META: CellMeta = panelMeta(PLUGIN_VIEW_KIND, PLUGIN_VIEW_TITLE_KEY, TEMPLATE_PANEL_MIN);
