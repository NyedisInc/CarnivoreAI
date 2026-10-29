import type { LayoutStore } from './layout.svelte';
import { instanceId } from './meta';
import { sessions } from '../api';
import { slotNameFor } from './slot-identity';
import { DECLARED_LIMITS, MAX_VIEWERS, limitVerdict, viewersOf, type AddRefusal } from './model';
import { manifestById } from '../widgets/core-manifests';
import { sizeOf } from './observe.svelte';
import { GUTTER } from './tracks';
import { isPluginSlot } from './plugin-kinds';
import type { InstanceKind, SlotId } from './types';
import { t } from '../../lib/i18n/index.svelte';
import { splitThrough } from '../layouts/transition.svelte';

/*  hidden  */
export function takenSlots(store: LayoutStore): SlotId[] {
  return [
    ...store.state.layout.rows.flatMap((row) => row.slots.map((slot) => slot.id)),
    ...store.state.layout.hidden,
  ];
}

export function addBlocked(store: LayoutStore, kind: InstanceKind, sessionId: string): string {
  if (takenSlots(store).includes(instanceId(kind, instanceNameFor(kind, sessionId)))) {
    return t('opscenter.components.add_duplicate');
  }
  if (limitVerdict(store.state.layout, kind).refused) return limitLine(kind);
  if (kind !== 'analytics' && !isPluginSlot(kind) && viewersOf(store.state.layout).length >= MAX_VIEWERS) {
    return t('opscenter.components.add_cap', { count: MAX_VIEWERS });
  }
  return '';
}

export function limitLine(kind: InstanceKind): string {
  const limit = DECLARED_LIMITS[kind];
  if (limit === undefined) return '';
  const title = t(manifestById(`core.${kind}`)!.titleKey);
  return limit === 1 ? t('opscenter.components.add_limit_one', { title }) : t('opscenter.components.add_limit', { count: limit, title });
}

function instanceNameFor(kind: InstanceKind, sessionId: string): string {
  return kind === 'terminal' ? slotNameFor(sessionId, sessions.data) : sessionId;
}

export function sessionInstanceId(kind: InstanceKind, sessionId: string): SlotId {
  return instanceId(kind, instanceNameFor(kind, sessionId));
}

export function addSession(store: LayoutStore, kind: InstanceKind, sessionId: string): AddRefusal {
  const add = (): AddRefusal => store.add(kind, instanceNameFor(kind, sessionId));
  if (kind !== 'terminal' || store.page !== 'terminal') return add();
  return splitThrough(add, (refusal) => refusal === null, 'no-row');
}

export function refusalLine(refusal: AddRefusal, kind?: InstanceKind): string {
  if (refusal === 'limit' && kind) return limitLine(kind);
  if (refusal === 'duplicate') return t('opscenter.components.add_duplicate');
  if (refusal === 'cap') return t('opscenter.components.add_cap', { count: MAX_VIEWERS });
  if (refusal) return t('opscenter.components.add_failed');
  return '';
}

export function resetSurface(store: LayoutStore): void {
  store.resetAll(sizeOf('content').height, GUTTER);
  store.announce(t('opscenter.components.layout_reset'));
}
