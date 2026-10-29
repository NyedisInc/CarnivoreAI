<script lang="ts">
  import Icon from '../../opscenter/ui/Icon.svelte';
  import { MAX_BOARD_NAME } from '../../opscenter/engine/home-boards';
  import type { Layout } from '../../opscenter/engine/types';
  import { t } from '../i18n/index.svelte';
  import BoardPreview from './BoardPreview.svelte';
  import { boardShape } from './board-shape';
  import { dashboardsUi, downloadDashboard, makeHome, openDashboard, removeDashboard, renameTo, showDashboard } from './dashboard-actions.svelte';

  let {
    id,
    name,
    home,
    layout,
    onEditHome,
  }: {
    id: string;
    name: string;
    home: boolean;
    layout: Layout | undefined;
    onEditHome: () => void;
  } = $props();

  let renaming = $state(false);
  let draft = $state('');
  let confirming = $state(false);

  const shape = $derived(boardShape(layout));
  const meta = $derived(
    shape.widgets === 0
      ? t('dashboards.meta_empty')
      : t(shape.widgets === 1 ? 'dashboards.meta_one' : 'dashboards.meta', { widgets: shape.widgets, rows: shape.rows }),
  );

  function focusSelect(node: HTMLInputElement): void {
    node.focus();
    node.select();
  }

  function startRename(): void {
    confirming = false;
    draft = name;
    renaming = true;
  }

  function commitRename(): void {
    if (!renaming) return;
    renaming = false;
    void renameTo(id, draft);
  }

  function onNameKey(event: KeyboardEvent): void {
    if (event.key === 'Enter') {
      event.preventDefault();
      commitRename();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      renaming = false;
    }
  }

  function remove(): void {
    confirming = false;
    void removeDashboard(id);
  }
</script>

<li class="dash-card" class:dash-card--home={home} data-dashboard={id}>
  <BoardPreview {layout} {home} />
  <div class="dash-card__head">
    {#if renaming}
      <input
        class="dash-card__input"
        type="text"
        maxlength={MAX_BOARD_NAME}
        aria-label={t('dashboards.name_label')}
        bind:value={draft}
        onkeydown={onNameKey}
        onblur={commitRename}
        use:focusSelect
        data-dashboard-name-input
      />
    {:else}
      <button
        type="button"
        class="dash-card__name"
        disabled={dashboardsUi.busy}
        aria-label={t('dashboards.rename_aria', { name })}
        data-dashboard-rename
        onclick={startRename}>{name}</button
      >
    {/if}
    {#if home}
      <span class="dash-card__home" data-dashboard-active><Icon name="home" size={11} />{t('dashboards.active_badge')}</span>
    {/if}
  </div>
  <div class="dash-card__meta-row">
    <p class="dash-card__meta">{meta}</p>
    <span class="dash-card__end">
      <button type="button" class="oc-btn oc-btn--sm oc-btn--ghost" aria-label={t('opscenter.boards.export_aria', { name })} data-dashboard-export onclick={() => void downloadDashboard(id)}
        >{t('opscenter.boards.export')}</button
      >
      {#if !home}
        <button
          type="button"
          class="oc-btn oc-btn--sm oc-btn--ghost dash-card__delete"
          disabled={dashboardsUi.busy}
          aria-label={t('dashboards.delete_aria', { name })}
          aria-expanded={confirming}
          data-dashboard-delete
          onclick={() => (confirming = !confirming)}>{t('dashboards.delete')}</button
        >
      {/if}
    </span>
  </div>
  <div class="dash-card__actions">
    {#if home}
      <button type="button" class="oc-btn oc-btn--sm" data-dashboard-edit aria-label={t('dashboards.edit_home_aria', { name })} onclick={onEditHome}
        ><Icon name="layout" size={11} />{t('dashboards.edit_home')}</button
      >
    {:else}
      <button
        type="button"
        class="oc-btn oc-btn--sm"
        disabled={dashboardsUi.busy}
        aria-label={t('dashboards.activate_aria', { name })}
        data-dashboard-activate
        onclick={() => void makeHome(id)}><Icon name="home" size={11} />{t('dashboards.activate')}</button
      >
      <button type="button" class="oc-btn oc-btn--sm" aria-label={t('dashboards.open_aria', { name })} data-dashboard-open onclick={() => showDashboard(id)}
        ><Icon name="layout" size={11} />{t('dashboards.open')}</button
      >
      <button type="button" class="oc-btn oc-btn--sm" aria-label={t('dashboards.edit_aria', { name })} data-dashboard-edit onclick={() => openDashboard(id, true)}
        ><Icon name="layout" size={11} />{t('dashboards.edit')}</button
      >
    {/if}
  </div>
  {#if confirming}
    <div class="dash-card__confirm" role="alert">
      <p class="dash-card__confirm-text">{t('dashboards.delete_confirm', { name })}</p>
      <div class="dash-card__confirm-row">
        <button type="button" class="modal-btn modal-btn-secondary" onclick={() => (confirming = false)}>{t('dashboards.delete_keep')}</button>
        <button type="button" class="modal-btn modal-btn-danger" data-dashboard-delete-confirm onclick={remove}>{t('dashboards.delete_go')}</button>
      </div>
    </div>
  {/if}
</li>

<style>
  @layer components {
    .dash-card {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-2);
      min-width: 0;
      padding: var(--oc-space-2);
      background: var(--oc-ground-raised);
      border: var(--oc-border, 1px) solid var(--oc-line-faint);
      border-radius: var(--oc-radius-sm, 2px);
      font-family: var(--font-mono);
    }

    .dash-card--home {
      border-color: color-mix(in srgb, var(--oc-green) 55%, var(--oc-line-faint));
      box-shadow: inset 2px 0 0 var(--oc-green);
    }

    .dash-card__head {
      display: flex;
      align-items: center;
      gap: var(--oc-space-2);
      min-width: 0;
      min-height: 24px;
    }

    .dash-card__name {
      flex: 1 1 auto;
      min-width: 0;
      padding: 2px 4px;
      margin-left: -4px;
      overflow: hidden;
      border: var(--oc-border, 1px) solid transparent;
      border-radius: var(--oc-radius-sm, 2px);
      background: transparent;
      color: var(--oc-text-primary);
      font-family: inherit;
      font-size: var(--oc-fs-status);
      text-align: left;
      text-overflow: ellipsis;
      white-space: nowrap;
      cursor: text;
    }

    .dash-card__name:hover:not(:disabled) {
      border-color: var(--oc-line-rule);
    }

    .dash-card__input {
      flex: 1 1 auto;
      min-width: 0;
      padding: 2px 6px;
      border: var(--oc-border, 1px) solid var(--oc-line-rule);
      border-radius: var(--oc-radius-sm, 2px);
      background: var(--oc-ground-field, var(--oc-ground-page));
      color: var(--oc-text-primary);
      font-family: inherit;
      font-size: var(--oc-fs-status);
    }

    .dash-card__home {
      display: inline-flex;
      flex: none;
      align-items: center;
      gap: 4px;
      padding: 1px 6px;
      border: var(--oc-border, 1px) solid color-mix(in srgb, var(--oc-green) 55%, transparent);
      border-radius: var(--oc-radius-sm, 2px);
      font-size: var(--oc-fs-micro);
      letter-spacing: var(--oc-tracking-label, 0.6px);
      text-transform: uppercase;
      color: var(--oc-green);
    }

    .dash-card__meta {
      margin: 0;
      font-size: var(--oc-fs-label);
      color: var(--oc-text-muted);
    }

    .dash-card__actions {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--oc-space-1);
      padding-top: var(--oc-space-2);
      box-shadow: inset 0 1px 0 var(--oc-line-faint);
    }

    .dash-card__meta-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--oc-space-2);
      min-width: 0;
    }

    .dash-card__end {
      display: inline-flex;
      flex: none;
      gap: 2px;
    }

    .dash-card__actions :global(.oc-btn) {
      --_bd: var(--oc-control-line-hi);
      border-color: var(--oc-control-line-hi);
    }

    .dash-card__delete:hover:not(:disabled),
    .dash-card__delete[aria-expanded='true'] {
      color: var(--oc-coral);
    }

    .dash-card__confirm {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-2);
    }

    .dash-card__confirm-text {
      margin: 0;
      font-size: var(--oc-fs-label);
      color: var(--oc-text-secondary);
    }

    .dash-card__confirm-row {
      display: flex;
      gap: var(--oc-space-2);
    }

    .dash-card__confirm-row :global(.modal-btn) {
      flex: 1 1 0;
      min-height: var(--oc-space-6);
    }
  }
</style>
