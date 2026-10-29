<script lang="ts">
  import './move-folder.css';
  import '../send-to/send-to.css';
  import { onMount } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import ModalShell from '../launchpad/ModalShell.svelte';
  import Check from '../../opscenter/ui/Check.svelte';
  import {
    applyMove, formatBytes, listMoveProjects, planMove, sameDestination,
    type MoveDestination, type MovePlan, type MoveProject,
  } from './move-api';

  interface Props {
    uuid: string;
    name: string;
    onClose: () => void;
  }
  const { uuid, name, onClose }: Props = $props();

  type Mode = 'project' | 'folder';

  let projects = $state<MoveProject[]>([]);
  let loadError = $state<string | null>(null);
  let mode = $state<Mode>('project');
  let projectId = $state('');
  let folder = $state('');
  let plan = $state<MovePlan | null>(null);
  let planFor = $state<MoveDestination | null>(null);
  let planning = $state(false);
  let armed = $state(false);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let done = $state<MovePlan | null>(null);
  let picker = $state(false);

  const destination: MoveDestination | null = $derived(
    mode === 'project'
      ? (projectId ? { project_id: Number(projectId) } : null)
      : (folder.trim() ? { new_folder: folder.trim() } : null),
  );
  const current = $derived(plan && sameDestination(destination, planFor) ? plan : null);
  const live = $derived(current?.kills_live_pane === true);
  const canMove = $derived(current !== null && current.ok && !busy && (!live || armed));

  onMount(() => {
    picker = typeof (globalThis as { FolderPickerModal?: { open?: unknown } }).FolderPickerModal?.open === 'function';
    listMoveProjects().then(
      (rows) => { projects = rows; },
      (e: unknown) => { loadError = e instanceof Error && e.message ? e.message : t('session.move.error.projects'); },
    );
  });

  async function check(): Promise<void> {
    if (!destination || planning || busy) return;
    const asked = destination;
    planning = true;
    error = null;
    armed = false;
    try {
      plan = await planMove(uuid, asked);
      planFor = asked;
    } catch (e) {
      plan = null;
      error = e instanceof Error && e.message ? e.message : t('session.move.error.check');
    } finally {
      planning = false;
    }
  }

  async function go(): Promise<void> {
    if (!canMove || !planFor) return;
    busy = true;
    error = null;
    try {
      done = await applyMove(uuid, planFor, live && armed);
    } catch (e) {
      error = e instanceof Error && e.message ? e.message : t('session.move.error.failed');
    } finally {
      busy = false;
    }
  }

  async function browse(): Promise<void> {
    const open = (globalThis as { FolderPickerModal?: { open(): Promise<string | null> } }).FolderPickerModal?.open;
    if (!open) return;
    const chosen = await open.call((globalThis as { FolderPickerModal?: object }).FolderPickerModal);
    if (chosen) folder = chosen;
  }
</script>

<ModalShell title={t('session.move.title', { name })} overlayClass="stm-modal" contentClass="stm popup-focus" dismissable={!busy}
  onCancel={onClose} data-move-modal="">
  {#snippet head()}
    <div class="stm-titlerow">
      <span class="stm-label">{t('session.move.label')}</span>
      <span class="stm-title" data-move="title">{t('session.move.title', { name })}</span>
    </div>
  {/snippet}
  <div class="stm-body">
    {#if done}
      <p class="stm-note" data-move="done">{t('session.move.done', { destination: done.destination ?? '', count: String(done.file_count) })}</p>
    {:else}
      <div class="stm-options" role="radiogroup" aria-label={t('session.move.label')}>
        <label class="stm-option" data-choice="project">
          <input type="radio" name="move-mode" value="project" checked={mode === 'project'} disabled={busy} onchange={() => (mode = 'project')} />
          <span class="stm-option-text">
            <span class="stm-option-title">{t('session.move.dest.project')}</span>
            <select class="modal-input" data-move="project" aria-label={t('session.move.dest.project')} bind:value={projectId} disabled={busy || mode !== 'project'}>
              <option value="">{t('session.move.project.pick')}</option>
              {#each projects as p (p.id)}<option value={String(p.id)}>{p.name}</option>{/each}
            </select>
          </span>
        </label>
        <label class="stm-option" data-choice="folder">
          <input type="radio" name="move-mode" value="folder" checked={mode === 'folder'} disabled={busy} onchange={() => (mode = 'folder')} />
          <span class="stm-option-text">
            <span class="stm-option-title">{t('session.move.dest.folder')}</span>
            <span class="mvf-row">
              <input type="text" class="modal-input" data-move="folder" aria-label={t('session.move.dest.folder')} placeholder={t('session.move.folder.placeholder')}
                autocomplete="off" spellcheck="false" bind:value={folder} disabled={busy || mode !== 'folder'} />
              {#if picker}
                <button type="button" class="modal-btn modal-btn-secondary" data-move="browse" disabled={busy || mode !== 'folder'} onclick={() => void browse()}>{t('session.move.folder.browse')}</button>
              {/if}
            </span>
            <span class="stm-option-help">{t('session.move.folder.help')}</span>
          </span>
        </label>
      </div>
      {#if loadError}<p class="stm-error" role="alert" data-move="load-error">{loadError}</p>{/if}
      {#if planning}<p class="stm-note" data-move="checking">{t('session.move.checking')}</p>{/if}
      {#if current}
        <div class="mvf-plan" data-move="plan">
          <div class="mvf-plan-row" data-move="from"><span class="mvf-plan-key">{t('session.move.plan.from')}</span><span class="mvf-plan-val">{current.source ?? ''}</span></div>
          <div class="mvf-plan-row" data-move="to"><span class="mvf-plan-key">{t('session.move.plan.to')}</span><span class="mvf-plan-val">{current.destination ?? ''}{current.creates_folder ? ` (${t('session.move.plan.creates')})` : ''}</span></div>
          <div class="mvf-plan-row" data-move="files"><span class="mvf-plan-key">{t('session.move.plan.files')}</span><span class="mvf-plan-val">{current.file_count > 0 ? t('session.move.plan.carried', { count: String(current.file_count), size: formatBytes(current.total_bytes) }) : t('session.move.plan.none')}</span></div>
          {#if current.collisions.length}
            <div class="mvf-plan-row" data-move="collisions"><span class="mvf-plan-key">{t('session.move.plan.collisions')}</span><span class="mvf-plan-val mvf-bad">{current.collisions.join(', ')}</span></div>
          {/if}
          {#if current.left_behind.length}
            <div class="mvf-plan-row" data-move="left-behind"><span class="mvf-plan-key">{t('session.move.plan.left_behind')}</span><span class="mvf-plan-val">{current.left_behind.join(', ')}</span></div>
          {/if}
        </div>
        {#each current.refusals as refusal (refusal.code)}
          <p class="stm-error" role="alert" data-move="refusal" data-code={refusal.code}>{refusal.message}</p>
        {/each}
        {#if live}
          <div class="mvf-live" data-move="live">
            <p class="stm-option-why">{t('session.move.arm.hint')}</p>
            <Check label={t('session.move.arm')} checked={armed} disabled={busy} data-move="arm" onToggle={(next) => (armed = next)} />
          </div>
        {/if}
      {/if}
      {#if error}<p class="stm-error" role="alert" data-move="error">{error}</p>{/if}
    {/if}
  </div>
  {#snippet footer()}
    <footer class="stm-foot">
      {#if done}
        <button type="button" class="modal-btn modal-btn-confirm" data-move="close" onclick={onClose}>{t('session.move.close')}</button>
      {:else}
        <button type="button" class="modal-btn modal-btn-secondary" data-move="cancel" disabled={busy} onclick={onClose}>{t('session.move.cancel')}</button>
        <button type="button" class="modal-btn modal-btn-secondary" data-move="check" disabled={!destination || planning || busy} onclick={() => void check()}>{t('session.move.check')}</button>
        {#if live}
          <button type="button" class="modal-btn modal-btn-danger" data-move="go" disabled={!canMove} onclick={() => void go()}>{t('session.move.go.live')}</button>
        {:else}
          <button type="button" class="modal-btn modal-btn-confirm" data-move="go" disabled={!canMove} onclick={() => void go()}>{t('session.move.go')}</button>
        {/if}
      {/if}
    </footer>
  {/snippet}
</ModalShell>
