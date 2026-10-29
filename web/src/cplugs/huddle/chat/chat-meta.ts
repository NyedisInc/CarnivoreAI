import type { CplugWidget } from '../../sdk';

export const chatWidgetMeta: CplugWidget['meta'] = {
  id: 'huddle.chat:agent:0',
  titleKey: 'cplug.huddle.chat.title',
  icon: 'chat',
  iconTone: 'oc-cyan',
  showCount: false,
  chrome: 'card',
  titleHeight: 31,
  defaultRow: 'r1',
  defaultIndex: 0,
  defaultFr: 1,
  defaultHeight: 320,
  minPx: 360,
  minHeight: 240,
  widthStates: [{ name: 'narrow', min: 0 }, { name: 'wide', min: 560 }],
  heightStates: [{ name: 'strip', min: 0 }, { name: 'pane', min: 240 }],
  phoneOrder: 22,
};
