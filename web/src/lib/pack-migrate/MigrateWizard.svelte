<script lang="ts">
  import '../ledger/ledger-chrome.css';
  import './migrate-wizard.css';
  import { t } from '../i18n/index.svelte';
  import Check from '../../opscenter/ui/Check.svelte';
  import Button from '../base/Button.svelte';
  import Field from '../base/Field.svelte';
  import { packMachines, type PackMachine } from '../pack-machines/pack-machines-store.svelte';
  import { applyMove, closeMigrate, followedOp, migrate, phaseOf, planMove, publishRepo, type ProjectPlan } from './migrate-store.svelte';

  import { movePanelState, notCopiedFiles, stepProgress } from './move-panel-state';

  function toggleStop(next: boolean): void {
    migrate.stopRunning = next;
    if (migrate.machine) void planMove(migrate.machine);
  }

  const target = $derived(migrate.target);
  const op = $derived(followedOp()?.data ?? null);
  const phase = $derived(op ? phaseOf(op.state) : migrate.phase);
  const peers = $derived((packMachines.data?.machines ?? []).filter((m) => !m.is_self && m.paired));
  const oneWay = $derived(migrate.plan?.projects.some((p) => p.one_way) ?? false);
  const STEPS = ['prepare', 'code', 'rows', 'transcripts', 'verify', 'flip'];
  const panelState = $derived(movePanelState({ kind: target?.kind ?? 'project', phase: migrate.phase, machine: migrate.machine, busy: migrate.busy,
    error: migrate.error, canApply: migrate.plan?.can_apply ?? null, opState: op?.state ?? null }));
  const lostFiles = $derived(notCopiedFiles(op));
  const progress = $derived(stepProgress(op?.step ?? null, op?.steps ?? STEPS));
  let chosenHere = $state(false);
  let owner = $state('');
  let account = $state('');

  function refusal(machine: PackMachine): string | null {
    const rules = machine.snapshot?.restrictions;
    const label = machine.label || machine.install_id.slice(0, 8);
    if (machine.state !== 'connected' || !rules) return t('pack.migrate.reason.disconnected', { machine: label });
    if (!rules.may_receive_projects) return t('pack.migrate.reason.refuses', { machine: label });
    if (target?.kind === 'project' && rules.allowed_projects.length > 0 && !rules.allowed_projects.includes(target.name)) {
      return t('pack.migrate.reason.not_listed', { machine: label });
    }
    if (target?.kind === 'company' && rules.allowed_companies.length > 0 && !rules.allowed_companies.includes(target.name)) {
      return t('pack.migrate.reason.not_listed', { machine: label });
    }
    return null;
  }

  function stepState(step: string): 'done' | 'current' | 'pending' {
    const order = op?.steps ?? STEPS;
    const at = op?.step ? order.indexOf(op.step) : -1;
    const mine = order.indexOf(step);
    if (phase === 'done') return 'done';
    return mine < at ? 'done' : mine === at ? 'current' : 'pending';
  }

  function offered(plan: ProjectPlan): boolean {
    return plan.publish_card?.offered === true;
  }
</script>

{#if target}
  <section class="mw pl-panel pledger" data-migrate-wizard data-phase={phase} aria-labelledby="mw-title">
    <div class="pl-titlebar">
      <h3 class="pl-title" id="mw-title">{target.kind === 'back' ? t('pack.migrate.title_back') : t('pack.migrate.title')}</h3>
      <span class="mw-spacer"></span>
      <Button size="sm" data-mw="close" disabled={panelState === 'moving'} onclick={closeMigrate}>{t('pack.migrate.close')}</Button>
    </div>
    <div class="mw-body">
      <p class="mw-subject"><span class="pl-label">{t(`pack.migrate.kind.${target.kind === 'company' ? 'company' : 'project'}`)}</span>
        <span class="pm-name" data-mw="subject">{target.name}</span>
        {#if migrate.machine}<span class="pm-note" data-mw="machine">{t('pack.migrate.to', { machine: migrate.machine })}</span>{/if}</p>
      {#if migrate.error}<p class="pm-error" role="alert" data-mw="error">{migrate.error}</p>{/if}

      {#if panelState === 'checking'}
        <p class="pm-note" role="status" data-mw="checking">{migrate.machine ? t('pack.migrate.checking', { machine: migrate.machine }) : t('pack.migrate.checking_back')}</p>
      {/if}

      {#if panelState === 'pick' && target.kind !== 'back'}
        {#if peers.length === 0}
          <p class="pm-note" data-mw="no-targets">{t('pack.migrate.no_targets')}</p>
        {:else}
          <p class="pm-note">{t('pack.migrate.pick_help')}</p>
          <ul class="mw-machines">
            {#each peers as machine (machine.install_id)}
              {@const why = refusal(machine)}
              <li class="mw-machine" data-machine={machine.install_id} data-disabled={why !== null}>
                <Button size="sm" data-mw="pick" disabled={why !== null || migrate.busy}
                  onclick={() => { chosenHere = true; void planMove(machine.label || machine.install_id); }}>{machine.label || machine.install_id.slice(0, 8)}</Button>
                {#if why}<span class="pm-note" data-mw="reason">{why}</span>{/if}
              </li>
            {/each}
          </ul>
        {/if}
      {/if}

      {#if (panelState === 'ready' || panelState === 'refused') && target.kind === 'back' && migrate.back}
        <p class="pm-note" data-mw="back-will">{t('pack.migrate.back_will', { machine: migrate.back.machine, name: migrate.back.name })}</p>
      {/if}

      {#if (panelState === 'ready' || panelState === 'refused') && target.kind !== 'back' && migrate.plan}
        {@const plan = migrate.plan}
        {#each plan.projects as p (p.project)}
          <div class="mw-card" data-mw="project" data-rung={p.rung}>
            <div class="pm-head"><span class="pm-name">{p.project}</span>
              <span class="pm-badge" data-mw="rung">{t(`pack.migrate.rung.${p.rung}`)}</span></div>
            <p class="pm-note" data-mw="rung-reason">{p.rung_reason}</p>
            <p class="pm-stats" data-mw="summary">
              <span>{t('pack.migrate.sum.sessions', { count: p.summary.sessions ?? 0 })}</span>
              <span>{t('pack.migrate.sum.agents', { count: p.summary.agents ?? 0 })}</span>
              <span>{t('pack.migrate.sum.cards', { count: p.summary.cards ?? 0 })}</span>
              <span>{t('pack.migrate.sum.transcripts', { count: p.summary.transcript_files ?? 0 })}</span>
            </p>
            <p class="pm-note">{t('pack.migrate.lands_at', { path: p.target_root })}</p>
            <ul class="mw-checks">
              {#each p.checks as check (check.name)}
                <li class="mw-check" data-ok={check.ok} data-blocking={check.blocking && !check.ok}>{check.detail}
                  {#if check.files?.length}
                    <ul class="mw-checks" data-mw="plan-files">
                      {#each check.files as name, i (i)}<li class="mw-check" data-mw="plan-file">{name}</li>{/each}
                      {#if check.files_more}<li class="mw-check" data-mw="plan-files-more">{t('pack.migrate.files_lost_more', { count: check.files_more })}</li>{/if}
                    </ul>
                  {/if}
                </li>
              {/each}
            </ul>
            {#if offered(p) && p.publish_card}
              <div class="mw-publish" data-mw="publish">
                <h4 class="pl-label">{t('pack.migrate.publish_title')}</h4>
                <p class="pm-note">{t('pack.migrate.publish_help', { name: p.publish_card.name })}</p>
                {#if p.publish_card.asks.includes('owner')}
                  <Field label={t('pack.migrate.publish_owner')} bind:value={owner} placeholder={p.publish_card.owner ?? ''} />
                {/if}
                {#if p.publish_card.asks.includes('account')}
                  <Field label={t('pack.migrate.publish_account')} bind:value={account} placeholder={p.publish_card.account ?? ''} />
                {/if}
                <div class="mw-actions">
                  <Button size="sm" data-mw="publish-go" disabled={migrate.busy}
                    onclick={() => void publishRepo(owner, account)}>{t('pack.migrate.publish_go')}</Button>
                </div>
              </div>
            {/if}
          </div>
        {/each}
        <div data-mw="stop-running">
          <Check label={t('pack.migrate.stop_running', { machine: plan.machine })} checked={migrate.stopRunning} onToggle={toggleStop} />
        </div>
        {#if oneWay}
          <p class="pm-warn" data-mw="one-way">{t('pack.migrate.one_way_warning')}</p>
          <Check label={t('pack.migrate.one_way_ack')} checked={migrate.confirmedOneWay} data-mw="one-way-ack"
            onToggle={(next) => (migrate.confirmedOneWay = next)} />
        {/if}
        {#if !plan.can_apply}<p class="pm-error" data-mw="blocked">{t('pack.migrate.blocked', { reasons: plan.blocking.join('; ') })}</p>{/if}
      {/if}

      {#if panelState === 'moving'}
        {#if target.kind === 'back'}
          <p class="pm-note" data-mw="running">{t('pack.migrate.running_back')}</p>
        {:else}
          {#if progress}<p class="pl-label" data-mw="progress">{t('pack.migrate.progress', { n: progress.n, total: progress.total })}</p>{/if}
          <ol class="mw-steps" data-mw="steps">
            {#each op?.steps ?? STEPS as step (step)}
              <li class="mw-step" data-step={step} data-state={stepState(step)}>{t(`pack.migrate.step.${step}`)}</li>
            {/each}
          </ol>
          {#if op && op.children.length > 0}
            <ul class="mw-children">
              {#each op.children as child (child.id)}
                <li class="pm-note" data-mw="child">{child.name ?? child.id.slice(0, 8)}: {child.step ?? child.state}</li>
              {/each}
            </ul>
          {/if}
        {/if}
      {/if}

      {#if panelState === 'done'}
        <p class="mw-result" role="status" data-mw="done">{target.kind === 'back' ? t('pack.migrate.done_back', { name: target.name }) : t('pack.migrate.done', { machine: migrate.plan?.machine ?? '' })}</p>
      {/if}
      {#if panelState === 'done' && lostFiles.total > 0}
        <div class="pm-warn" role="status" data-mw="files-lost">
          <p class="pl-label">{t('pack.migrate.files_lost', { count: lostFiles.total })}</p>
          <p class="pm-note">{t('pack.migrate.files_lost_help')}</p>
          <ul class="mw-checks">
            {#each lostFiles.names as name, i (i)}<li class="mw-check" data-mw="file-lost">{name}</li>{/each}
            {#if lostFiles.total > lostFiles.names.length}
              <li class="mw-check" data-mw="files-lost-more">{t('pack.migrate.files_lost_more', { count: lostFiles.total - lostFiles.names.length })}</li>
            {/if}
          </ul>
        </div>
      {/if}
      {#if panelState === 'failed' && op}
        <p class="pm-error" role="alert" data-mw="failed">{t('pack.migrate.failed', { step: op.step ?? '', code: op.error_code ?? 'unknown' })}
          {typeof op.detail.error === 'string' ? op.detail.error : ''}</p>
        <p class="pm-note">{t('pack.migrate.failed_help')}</p>
      {/if}
    </div>
    <div class="mw-foot" data-mw="foot">
      {#if panelState === 'done' || panelState === 'failed'}
        <Button data-mw="done-close" onclick={closeMigrate}>{t('pack.migrate.close')}</Button>
      {:else}
        {#if chosenHere && (panelState === 'refused' || panelState === 'ready') && target.kind !== 'back'}
          <Button data-mw="change" onclick={() => { migrate.phase = 'pick'; migrate.plan = null; migrate.machine = null; migrate.error = null; }}>{t('pack.migrate.change_machine')}</Button>
        {/if}
        <Button data-mw="cancel" disabled={panelState === 'moving'} onclick={closeMigrate}>{t('pack.migrate.cancel')}</Button>
        {#if panelState !== 'pick'}
          <Button data-mw="confirm" variant={oneWay ? 'danger' : 'confirm'}
            disabled={panelState !== 'ready' || migrate.busy || (oneWay && !migrate.confirmedOneWay)} onclick={() => void applyMove()}>
            {panelState === 'moving' ? t('pack.migrate.moving') : target.kind === 'back' ? t('pack.migrate.confirm_back') : oneWay ? t('pack.migrate.confirm_one_way') : t('pack.migrate.confirm')}</Button>
        {/if}
      {/if}
    </div>
  </section>
{/if}
