<script lang="ts">
  import ProjectNameModal from '../../lib/launchpad/ProjectNameModal.svelte';
  import ChoiceModal from '../../lib/launchpad/ChoiceModal.svelte';
  import ConfirmSheet from '../../lib/catalog/ConfirmSheet.svelte';
  import { t } from '../../lib/i18n/index.svelte';

  type Open = 'name' | 'choice' | 'confirm' | 'destroy' | null;
  let open = $state<Open>(null);
  let answer = $state('nothing yet');

  function done(value: unknown): void {
    answer = value === null ? 'cancelled' : JSON.stringify(value);
    open = null;
  }
</script>

<div class="sg-row">
  <button type="button" class="modal-btn modal-btn-secondary" data-sg-open="name" onclick={() => (open = 'name')}
    >name prompt</button
  >
  <button type="button" class="modal-btn modal-btn-secondary" data-sg-open="choice" onclick={() => (open = 'choice')}
    >one of n picker</button
  >
  <button type="button" class="modal-btn modal-btn-secondary" data-sg-open="confirm" onclick={() => (open = 'confirm')}
    >confirm sheet</button
  >
  <button type="button" class="modal-btn modal-btn-secondary" data-sg-open="destroy" onclick={() => (open = 'destroy')}
    >destructive confirm</button
  >
</div>
<p class="sg-caption">last answer: <code data-sg-answer>{answer}</code></p>

{#if open === 'name'}
  <ProjectNameModal title="name the new project" confirmLabel="create" defaultName="music" pathHint="~/code/music" close={done} />
{:else if open === 'choice'}
  <ChoiceModal
    title="which harness"
    items={[
      { key: 'claude', label: 'claude', sub: 'subscription' },
      { key: 'codex', label: 'codex', sub: 'openai' },
      { key: 'local', label: 'local model', disabled: true, reason: 'no local model is configured' },
    ]}
    close={done}
  />
{:else if open === 'confirm'}
  <ConfirmSheet
    title="install music-tools"
    lead="this copies the skill into every harness folder listed below."
    linesHeading="folders"
    lines={['~/.claude/skills/music-tools', '~/.codex/skills/music-tools']}
    confirmLabel="install"
    busyLabel="installing"
    {t}
    close={done}
  />
{:else if open === 'destroy'}
  <ConfirmSheet
    title="uninstall music-tools"
    lead="this removes the skill from every harness folder listed below."
    linesHeading="folders"
    lines={['~/.claude/skills/music-tools']}
    confirmLabel="uninstall"
    busyLabel="uninstalling"
    destructive={true}
    {t}
    close={done}
  />
{/if}
