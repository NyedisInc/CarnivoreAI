import type { LayoutStore, DropTarget } from '../../opscenter/engine/layout.svelte';
import type { InstanceKind, LayoutPage, SlotId } from '../../opscenter/engine/types';
import { refusalLine } from '../../opscenter/engine/components-actions';
import { beginCardDrag } from '../../opscenter/layout-editor/drawer-drag';
import { storeFor, surfacePage } from '../drawer-tabs/drawer-surface.svelte';
import { chatSlotId } from '../../cplugs/huddle/chat/chat-model';
import { openAgentPopout } from '../../popout/popout';
import { t } from '../i18n/index.svelte';

const CHAT_KIND = 'huddle.chat' as InstanceKind;

function currentSurface(): { page: LayoutPage; store: LayoutStore } | null {
  const page = surfacePage() ?? 'home';
  const store = storeFor(page);
  return store ? { page, store } : null;
}

export function addAgentWidget(id: number, target: DropTarget | null): boolean {
  const surface = currentSurface();
  if (!surface) return false;
  const { store } = surface;
  const refusal = store.add(CHAT_KIND, `agent:${id}`);
  if (refusal) {
    store.announce(refusalLine(refusal, CHAT_KIND));
    return false;
  }
  const last = store.state.layout.rows[store.state.layout.rows.length - 1];
  const place: DropTarget | null = target ?? (last ? { kind: 'new', after: last.id } : null);
  if (place) store.moveTo(chatSlotId(id) as SlotId, place);
  store.announce(t('cplug.huddle.swarm.drawer.widget_added'));
  return true;
}

export function popOutAgent(id: number, width: number): boolean {
  return openAgentPopout(id, { width, height: window.innerHeight }) !== null;
}

export function beginAgentBarDrag(bar: HTMLElement, event: PointerEvent, id: number, drawer: HTMLElement | null, onDropped: () => void): boolean {
  const surface = currentSurface();
  if (!surface) return false;
  return beginCardDrag(bar, event, chatSlotId(id) as SlotId, surface.store, surface.page, drawer, {
    onMove: () => {},
    onDrop: (target) => {
      if (addAgentWidget(id, target)) onDropped();
    },
    onEnd: () => {},
  });
}
