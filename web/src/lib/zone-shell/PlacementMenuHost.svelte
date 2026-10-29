<script lang="ts">
  import CascadeMenu from '../drawer-tabs/CascadeMenu.svelte';
  import AnchoredPopup from '../dialog-frame/AnchoredPopup.svelte';
  import ItemSettingsPanel from '../item-settings/ItemSettingsPanel.svelte';
  import type { MenuNode } from '../drawer-tabs/add-component-menu';
  import { t } from '../i18n/index.svelte';
  import { writeItem } from '../item-settings/api';
  import { itemSettings, storedNode } from '../item-settings/store.svelte';
  import { untrack } from 'svelte';
  import type { WidgetManifest } from '../../opscenter/widgets/types';
  import { resolvePlacement } from '../../opscenter/widgets/placement-resolve';
  import { placementOptionsFor, type PlacementOptions } from '../../opscenter/widgets/placement-options';
  import { declaredActionsFor } from '../../opscenter/widgets/menu/declared-actions.svelte';
  import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';
  import type { RailEdge } from '../session-rail/rail-model';
  import { bodyDrawn, mountsUnseen, openingActions } from '../widget-menu/closed-key.svelte';
  import type { OptionNodesInput } from '../widget-menu/option-nodes';
  import { activeScopeFor } from '../../opscenter/widgets/active-scope';
  import { pinnedScopeFor } from '../widget-bars/pinned-scope';
  import PlacementBody from './PlacementBody.svelte';
  import { popOutFor } from './pop-out';
  import { HOST_LOOKS, type BodyHost } from './host-looks';
  import { placementMenu, type MenuHost, type PlacementMenuInput } from './placement-menu';
  import type { PlacementSource } from './source';

  type Extras = Pick<PlacementMenuInput, 'popOut' | 'focusMain' | 'header' | 'arrange' | 'editLayout' | 'close' | 'tab' | 'settings'>;

  let {
    host,
    bodyHost,
    editing: hostEditing = undefined,
    manifest,
    view = null,
    target = null,
    instance = null,
    options = undefined,
    placementKey,
    source = null,
    pickView = undefined,
    copy = undefined,
    copyHeading = undefined,
    lead = [],
    copyTail = [],
    extras = {},
    openHost = undefined,
    pinRowId = null,
    edge = 'side',
    anchor,
    label,
    onClose,
  }: {
    host: MenuHost;
    bodyHost: BodyHost | { drawn: string };
    editing?: boolean;
    manifest: WidgetManifest;
    view?: string | null;
    target?: string | null;
    instance?: string | null;
    options?: PlacementOptions;
    placementKey: string;
    source?: PlacementSource | null;
    pickView?: (view: string) => void;
    copy?: OptionNodesInput['placement'];
    copyHeading?: string;
    lead?: readonly (readonly MenuNode[])[];
    copyTail?: readonly MenuNode[];
    extras?: Extras;
    openHost?: () => void;
    pinRowId?: number | null;
    edge?: RailEdge;
    anchor: HTMLElement | null;
    label: string;
    onClose: () => void;
  } = $props();

  const resolved = $derived(resolvePlacement({ widget: manifest, view, target, instance }));
  const cell = $derived(resolved?.cell ?? manifest);
  const title = $derived(t(manifest.titleKey));
  const editing = $derived(hostEditing ?? layoutEditor.active);
  const unseenHost = $derived(typeof bodyHost === 'string' ? bodyHost : null);
  const declaredOptions = $derived(placementOptionsFor(manifest.id) ?? null);
  let form = $state(false);

  async function write(key: string, value: boolean | number | string): Promise<void> {
    try {
      await writeItem('widget', cell.id, { values: { [key]: value } });
      await itemSettings.refresh(true);
    } catch {
    }
  }

  const optionInput = $derived<OptionNodesInput>({
    manifest,
    cell,
    view,
    values: storedNode('widget', cell.id)?.values,
    translate: (key) => t(key),
    pickView: (next) => (pickView ?? ((v: string) => void source?.setView(placementKey, v)))(next),
    write: (key, value) => void write(key, value),
    openForm: () => (form = true),
    placement:
      copy ??
      (declaredOptions && source
        ? { schema: declaredOptions.schema(), values: options ?? {}, write: (key, value) => void source.setOption(placementKey, key, value) }
        : undefined),
  });

  const hostKey = $derived(typeof bodyHost === 'string' ? HOST_LOOKS[bodyHost].keyFor(cell, target, instance) : bodyHost.drawn);
  const unseen = $derived(!!unseenHost && mountsUnseen(manifest) && !untrack(() => bodyDrawn(hostKey)));
  const declared = $derived.by(() => {
    const actions = declaredActionsFor(hostKey);
    return unseen && openHost ? openingActions(actions, hostKey, openHost) : actions;
  });

  const heading = $derived(copyHeading ?? (declaredOptions?.menuHeadingKey ? t(declaredOptions.menuHeadingKey) : undefined));
  const scope = $derived(pinRowId != null ? pinnedScopeFor(cell, pinRowId) : activeScopeFor(cell));
  const popOut = $derived('popOut' in extras ? extras.popOut : popOutFor(manifest, cell, view, scope, options));

  const root = $derived(placementMenu({ host, editing, onClose, options: optionInput, declared, copyHeading: heading, lead, copyTail, ...extras, popOut }));
</script>

{#if unseen && unseenHost}
  
  <div class="pmh-unseen" hidden inert aria-hidden="true" data-menu-unseen={placementKey}>
    <PlacementBody host={unseenHost} {source} {manifest} {target} {view} {instance} {pinRowId} {options} {edge} {placementKey} unseen />
  </div>
{/if}
{#if form}
  <AnchoredPopup class="pmh-form" label={t('session_rail.menu.settings_for', { title })} placement="manual" outside="none" {onClose} data-oc-base data-widget-settings-form>
    <header class="pmh-form__bar">
      <span class="pmh-form__title">{title}</span>
      <button type="button" class="modal-btn modal-btn-secondary" onclick={onClose}>{t('session_rail.close')}</button>
    </header>
    <ItemSettingsPanel kind="widget" id={cell.id} t={(key, params) => t(key, params)} />
  </AnchoredPopup>
{:else if root.length > 0}
  <CascadeMenu {root} {anchor} {label} {onClose} />
{/if}

<style>
  @layer components {
    :global(.pmh-form) {
      position: fixed;
      left: var(--oc-space-6);
      bottom: var(--oc-space-6);
      z-index: 50;
      min-width: 0;
      max-width: calc(100vw - var(--oc-space-6) * 2);
      max-height: 70vh;
      overflow: auto;
      padding: var(--oc-space-2);
      background: var(--oc-ground-field);
      border: var(--oc-border) solid var(--oc-line-rule);
      border-radius: var(--oc-radius-sm);
      font-family: var(--oc-font);
    }
    .pmh-form__bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--oc-space-2);
      margin-bottom: var(--oc-space-2);
    }
    .pmh-form__title {
      color: var(--oc-orange);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
  }
</style>
