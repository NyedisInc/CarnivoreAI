<script lang="ts">
  import './send-to.css';
  import { onMount } from 'svelte';
  import ModalShell from '../launchpad/ModalShell.svelte';
  import { ApiError } from '../../opscenter/api/auth.svelte';
  import { t } from '../i18n/index.svelte';
  import Check from '../../opscenter/ui/Check.svelte';
  import CarryChecklist from './CarryChecklist.svelte';
  import MigrateWizard from '../pack-migrate/MigrateWizard.svelte';
  import { closeMigrate, migrate, openMigrate, planMove } from '../pack-migrate/migrate-store.svelte';
  import { reveal, track } from '../pack-op-toast/pack-op-store.svelte';
  import type { PackMachine } from '../pack-machines/pack-machines-store.svelte';
  import { checkSend, postSend, reasonText, type SendCheck, type SendMode } from './send-api';

  interface Props {
    uuid: string;
    name: string;
    machine: PackMachine;
    projectName: string | null;
    onClose: () => void;
  }
  const { uuid, name, machine, projectName, onClose }: Props = $props();

  type Choice = SendMode | 'project';
  const CHOICES: Choice[] = ['move', 'copy', 'fresh', 'project'];
  const label = machine.label || machine.install_id.slice(0, 8);

  let check = $state<SendCheck | null>(null);
  let loadError = $state<string | null>(null);
  let choice = $state<Choice>('move');
  let withProject = $state(true);
  let stopRunning = $state(false);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let wizard = $state(false);
  let ticked = $state<string[]>([]);

  const missing = $derived(check !== null && !check.project_on_target && check.project_addable.ok);

  function blocked(c: Choice): string | null {
    if (c === 'project') {
      if (!projectName) return t('session.send.block.no_project');
      return machine.snapshot?.restrictions && !machine.snapshot.restrictions.may_receive_projects
        ? t('session.send.block.no_projects', { machine: label }) : null;
    }
    const verdict = check?.[c];
    if (!verdict || verdict.ok) return null;
    if (verdict.reason === 'project_not_on_target' && missing && withProject) return null;
    return verdict.detail ?? reasonText(verdict.reason);
  }

  function toggleStop(next: boolean): void {
    stopRunning = next;
    checkSend(uuid, machine.install_id, next).then((answer) => { check = answer; if (next && check.running && !blocked('move')) choice = 'move'; }, () => {  });
  }

  onMount(() => {
    checkSend(uuid, machine.install_id).then(
      (answer) => {
        check = answer;
        ticked = (answer.carry?.outside ?? []).filter((o) => o.carryable && o.tick).map((o) => o.path);
        if (blocked('move')) choice = CHOICES.find((c) => !blocked(c)) ?? 'move';
      },
      (e: unknown) => { loadError = e instanceof Error && e.message ? e.message : t('session.send.error.check'); },
    );
    return () => { if (wizard) closeMigrate(); };
  });

  $effect(() => { if (wizard && migrate.target === null) onClose(); });

  async function go(): Promise<void> {
    if (busy || blocked(choice)) return;
    error = null;
    if (choice === 'project' && projectName) {
      openMigrate({ kind: 'project', name: projectName });
      wizard = true;
      void planMove(machine.label || machine.install_id);
      return;
    }
    busy = true;
    try {
      await postSend(uuid, { machine: machine.install_id, mode: choice as SendMode, with_project: missing && withProject,
        ...(choice === 'move' && stopRunning ? { stop_running: true } : {}) });
      void track();
      onClose();
    } catch (e) {
      const running = e instanceof ApiError && e.status === 409 ? (e.payload as { detail?: { op_id?: string } } | null)?.detail?.op_id : undefined;
      if (running) {
        void reveal(running);
        onClose();
        return;
      }
      error = e instanceof Error && e.message ? e.message : t('session.send.error.failed');
      busy = false;
    }
  }
</script>

{#snippet titleRow()}
  <div class="stm-titlerow">
    <span class="stm-label">{t('session.send.label')}</span>
    <span class="stm-title" data-send="title">{t('session.send.title', { name, machine: label })}</span>
  </div>
{/snippet}

{#snippet emptyHead()}{/snippet}

{#snippet sendFooter()}
  <footer class="stm-foot">
    <button type="button" class="modal-btn modal-btn-secondary" data-send="cancel" onclick={onClose}>{t('session.send.cancel')}</button>
    <button type="button" class="modal-btn modal-btn-confirm" data-send="go" disabled={!check || busy || blocked(choice) !== null} onclick={() => void go()}>{t('session.send.go')}</button>
  </footer>
{/snippet}

<ModalShell title={t('session.send.title', { name, machine: label })} overlayClass="stm-modal" contentClass="stm popup-focus" onCancel={onClose}
  head={wizard ? emptyHead : titleRow} footer={wizard ? undefined : sendFooter} data-send-to-modal="">
  {#if wizard}
    <MigrateWizard />
  {:else}
    <div class="stm-body">
      {#if loadError}
        <p class="stm-error" role="alert" data-send="load-error">{loadError}</p>
      {:else if !check}
        <p class="stm-note" data-send="loading">{t('session.send.loading')}</p>
      {:else}
        <div class="stm-options" role="radiogroup" aria-label={t('session.send.label')}>
          {#each CHOICES as c (c)}
            {@const why = blocked(c)}
            <label class="stm-option" data-choice={c} data-blocked={why !== null} aria-disabled={why !== null}>
              <input type="radio" name="send-choice" value={c} checked={choice === c} disabled={why !== null || busy} onchange={() => (choice = c)} />
              <span class="stm-option-text">
                <span class="stm-option-title">{t(`session.send.choice.${c}`)}</span>
                <span class="stm-option-help">{t(`session.send.help.${c}`, { name, machine: label })}</span>
                {#if why}<span class="stm-option-why" data-send="why">{why}</span>{/if}
              </span>
            </label>
          {/each}
        </div>
        {#if missing && choice !== 'project'}
          <div data-send="with-project">
            <Check label={t('session.send.with_project', { machine: label })} checked={withProject} onToggle={(next) => (withProject = next)} />
          </div>
        {/if}
        {#if choice === 'move' || check.running}
          <div data-send="stop-running">
            <Check label={t('session.send.stop_running', { machine: label })} checked={stopRunning} onToggle={toggleStop} />
          </div>
        {/if}
        {#if choice === 'move' && check.stop_shells}
          <p class="stm-note" data-send="stop-shells">{t('session.send.stop_shells', { count: check.stop_shells, name })}</p>
        {/if}
        {#if check.carry && choice !== 'project'}
          <CarryChecklist carry={check.carry} machine={label} {ticked} onTick={(path, on) => (ticked = on ? [...ticked, path] : ticked.filter((p) => p !== path))} />
        {/if}
        {#if error}<p class="stm-error" role="alert" data-send="error">{error}</p>{/if}
      {/if}
    </div>
  {/if}
</ModalShell>
