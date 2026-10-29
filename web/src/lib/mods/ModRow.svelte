
<script lang="ts">
  import Check from '../../opscenter/ui/Check.svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import WarezCard from '../catalog/WarezCard.svelte';
  import { t } from '../i18n/index.svelte';
  import type { ModEntry } from './mods-api';
  import { stateLabel } from './mods-format';

  let { mod, locked, busy, selected = false, card = false, onSelect, onToggle, onRemove }: {
    mod: ModEntry;
    locked: boolean;
    busy: boolean;
    selected?: boolean;
    card?: boolean;
    onSelect?: () => void;
    onToggle: (next: boolean) => void;
    onRemove: () => void;
  } = $props();

  let confirming = $state(false);

  function reveal(node: HTMLElement, on: boolean): { update(next: boolean): void } {
    const go = (next: boolean): void => { if (next) node.scrollIntoView?.({ block: 'nearest' }); };
    go(on);
    return { update: go };
  }

  const name = $derived(mod.name ?? mod.path);
  const canRemove = $derived(mod.source === 'catalog' || mod.removable);
  const switchOff = $derived(locked || busy || (!mod.present && mod.state === 'off'));
</script>

{#snippet controls()}
  <Check
    role="switch"
    label=""
    checked={mod.state === 'on'}
    disabled={switchOff}
    ariaLabel={t('mods.switch_aria', { name })}
    data-mod-switch=""
    onToggle={(next) => onToggle(next)}
  />
  <button
    type="button"
    class="oc-btn oc-btn--sm oc-btn--ghost"
    data-mod-remove
    disabled={locked || busy || !canRemove}
    title={canRemove ? undefined : t('mods.not_removable')}
    aria-expanded={confirming}
    aria-label={t('mods.remove_aria', { name })}
    onclick={() => (confirming = !confirming)}>{t('mods.remove')}</button
  >
{/snippet}

{#snippet confirmBlock()}
  <div class="mods-row__confirm" role="group">
    <p class="mods-line">{t(mod.source === 'catalog' ? 'mods.remove_confirm_catalog' : 'mods.remove_confirm_local', { name })}</p>
    <button type="button" class="modal-btn modal-btn-secondary" onclick={() => (confirming = false)}>{t('mods.remove_keep')}</button>
    <button
      type="button"
      class="modal-btn modal-btn-danger"
      data-mod-remove-confirm
      onclick={() => {
        confirming = false;
        onRemove();
      }}>{t('mods.remove_go')}</button
    >
  </div>
{/snippet}

{#snippet cardThumb()}<Icon name="mod" size={32} />{/snippet}

{#snippet cardFlags()}
  {#if mod.state === 'partial'}<span data-mod-state-label>{stateLabel(mod)}</span>{/if}
  {#if !mod.present}<span class="mods-line mods-line--warn">{t('mods.missing')}</span>{/if}
{/snippet}

{#if card}
  <li class="mods-card" data-mod={mod.mod_id} data-mod-state={mod.state} use:reveal={selected}>
    <WarezCard kind="mod" {t} {name} brief={mod.description ?? null} onOpen={onSelect ?? null} {selected} thumb={cardThumb} act={controls} flags={mod.present && mod.state !== 'partial' ? undefined : cardFlags}>
      {#if confirming}{@render confirmBlock()}{/if}
    </WarezCard>
  </li>
{:else}
<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
<li class="mods-row" class:mods-row--selected={selected} use:reveal={selected} data-mod={mod.mod_id} data-mod-state={mod.state} onclick={() => onSelect?.()}>
  <div class="mods-row__main">
    <span class="mods-row__name" data-mod-name>{name}</span>
    {#if mod.version}<span class="mods-line">{mod.version}</span>{/if}
    <span class="mods-mark" data-mod-source={mod.source}>{t(`mods.source.${mod.source}`)}</span>
    <span class="mods-line" data-mod-state-label>{stateLabel(mod)}</span>
    {#if !mod.is_mod}<span class="mods-mark">{t('mods.kind.plugin_dir')}</span>{/if}
    {#if !mod.present}<span class="mods-line mods-line--warn">{t('mods.missing')}</span>{/if}
    {#if mod.description}<span class="mods-line mods-row__desc">{mod.description}</span>{/if}
  </div>
  <div class="mods-row__side">
    {@render controls()}
  </div>
  {#if confirming}
    {@render confirmBlock()}
  {/if}
</li>
{/if}
