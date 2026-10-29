/* <script */
import type { CellProps } from '../../lib/cell';
import { activeTerminalSessionId } from '../../lib/active-terminal';
import { pickState } from '../../lib/states';
import { manifestById } from '../core-manifests';
import { widgetSetting } from '../../../lib/item-settings/store.svelte';
import { t } from '../../../lib/i18n/index.svelte';
import { declareWidgetActions, type DeclaredAction } from '../menu/declared-actions.svelte';
import { useFrameHeader, useTabPane, type FrameHeader } from '../../shell/frame-header.svelte';
import type { ZoneVisibility } from '../../../lib/zone-shell/zone-types';
import { useZonePane } from '../../../lib/zone-shell/zone-pane';
import { dimmest } from '../../../lib/zone-shell/zone-visibility';
import { bindState, rememberedNames, STATE_NAME, type StateSpec, type WidgetState } from './widget-state.svelte';

export type WidgetScope = 'session' | 'global';

export type WidgetSettingValue = boolean | number | string;

export interface WidgetActionSpec {
  readonly id: string;
  readonly labelKey: string;
  readonly kind?: 'action' | 'choice' | 'switch';
  readonly group?: string;
}

export interface WidgetSpec<A extends readonly WidgetActionSpec[], S extends Readonly<Record<string, WidgetSettingValue>>, T extends StateSpec = StateSpec> {
  readonly id: string;
  readonly scope: WidgetScope;
  readonly actions: A;
  readonly settings?: S;
  readonly state: T;
}

export type WidgetDefinition<A extends readonly WidgetActionSpec[] = readonly WidgetActionSpec[], S extends Readonly<Record<string, WidgetSettingValue>> = Readonly<Record<string, WidgetSettingValue>>, T extends StateSpec = StateSpec> =
  Readonly<Required<WidgetSpec<A, S, T>>>;

export type ActionIdOf<D extends WidgetDefinition> = D['actions'][number]['id'];

export interface ActionBinding {
  run: () => void;
  on?: boolean;
  blocked?: string;
}

export type ActionBindings<D extends WidgetDefinition> = { readonly [K in ActionIdOf<D>]: ActionBinding };

export type WidgetPropsIn = Partial<Pick<CellProps, 'width' | 'height' | 'meta' | 'scope' | 'instance'>>;

export interface WidgetHandle<D extends WidgetDefinition = WidgetDefinition> {
  readonly definition: D;
  readonly frame: FrameHeader | undefined;
  readonly visible: ZoneVisibility;
  readonly sessionId: string;
  readonly widthState: string;
  readonly heightState: string;
  readonly actions: readonly DeclaredAction[];
  readonly state: WidgetState<D['state']>;
  setting<K extends keyof D['settings'] & string>(key: K): D['settings'][K];
}

export const WIDGET_ACTION_SOURCE = 'widget';

/* <script */
export function defineWidget<const A extends readonly WidgetActionSpec[], const S extends Readonly<Record<string, WidgetSettingValue>> = Readonly<Record<never, WidgetSettingValue>>, const T extends StateSpec = StateSpec>(
  spec: WidgetSpec<A, S, T>,
): WidgetDefinition<A, S, T> {
  const ids = spec.actions.map((action) => action.id);
  const twice = ids.find((id, at) => ids.indexOf(id) !== at);
  if (twice) throw new Error(`${spec.id} declares the action ${twice} twice`);
  const badName = rememberedNames(spec.state).find((name) => !STATE_NAME.test(name));
  if (badName) throw new Error(`${spec.id} names its state ${badName}; names are flat lowercase (status-folds)`);
  return Object.freeze({ id: spec.id, scope: spec.scope, actions: spec.actions, settings: (spec.settings ?? {}) as S, state: spec.state });
}

export function boundAction(spec: WidgetActionSpec, binding: ActionBinding | undefined): DeclaredAction {
  if (!binding) throw new Error(`the action ${spec.id} is declared but not bound`);
  const kind = spec.kind ?? 'action';
  return {
    id: spec.id,
    label: t(spec.labelKey),
    run: binding.run,
    ...(kind === 'action' ? {} : { checked: !!binding.on }),
    ...(kind === 'switch' ? { toggle: true } : {}),
    ...(binding.blocked ? { blocked: binding.blocked } : {}),
    ...(spec.group === undefined ? {} : { group: spec.group }),
  };
}

export function readSetting<V extends WidgetSettingValue>(id: string, key: string, fallback: V): V {
  if (!manifestById(id)?.settings?.fields[key]) return fallback;
  const value = widgetSetting(id, key);
  return (typeof value === typeof fallback ? value : fallback) as V;
}

export function useWidget<D extends WidgetDefinition>(definition: D, props: () => WidgetPropsIn, bindings?: () => ActionBindings<D>): WidgetHandle<D> {
  const frame = useFrameHeader();
  const pane = useTabPane();
  const zonePane = useZonePane();
  const actions = $derived.by((): DeclaredAction[] => {
    if (!definition.actions.length) return [];
    const live = (bindings?.() ?? {}) as Readonly<Record<string, ActionBinding>>;
    return definition.actions.map((spec) => boundAction(spec, live[spec.id]));
  });
  $effect(() => {
    const host = frame?.hostId;
    const declared = actions;
    if (!host || !declared.length) return;
    return declareWidgetActions(host, WIDGET_ACTION_SOURCE, declared);
  });
  const sessionId = $derived(definition.scope === 'session' ? props().scope?.sessionId || activeTerminalSessionId() || '' : '');
  let lastWidth = '';
  let lastHeight = '';
  const widthState = $derived.by(() => (lastWidth = pickState(props().meta?.widthStates ?? [], props().width ?? 0, lastWidth)));
  const heightState = $derived.by(() => (lastHeight = pickState(props().meta?.heightStates ?? [], props().height ?? 0, lastHeight)));
  const state = bindState(definition.id, definition.state, () => props().instance ?? '') as WidgetState<D['state']>;
  const defaults = definition.settings as Readonly<Record<string, WidgetSettingValue>>;
  return {
    definition,
    frame,
    get visible() { return dimmest(pane?.visible, zonePane?.visible); },
    get sessionId() { return sessionId; },
    get widthState() { return widthState; },
    get heightState() { return heightState; },
    get actions() { return actions; },
    state,
    setting<K extends keyof D['settings'] & string>(key: K): D['settings'][K] {
      const fallback = defaults[key];
      if (fallback === undefined) throw new Error(`${definition.id} declares no setting ${key}`);
      return readSetting(definition.id, key, fallback) as D['settings'][K];
    },
  };
}
