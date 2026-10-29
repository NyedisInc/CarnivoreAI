
<script lang="ts">
  import { t } from '../../sdk';
  import { renameAgent } from './chat-api';

  let { agentId, name, onDone, onFail }: { agentId: number; name: string; onDone: () => void; onFail: (error: unknown) => void } = $props();

  let editing = $state(false);
  let draft = $state('');

  function start(event: Event): void {
    event.stopPropagation();
    draft = name;
    editing = true;
  }

  async function save(): Promise<void> {
    const next = draft.trim();
    if (!next || next === name) { editing = false; return; }
    try {
      await renameAgent(agentId, next);
      editing = false;
      onDone();
    } catch (error) {
      onFail(error);
    }
  }
</script>

{#if editing}
  <li role="none" class="hdc-rename">
    <label class="hdc-rename-label" for="hdc-rename-input">{t('leader.rename.label')}</label>
    <input id="hdc-rename-input" class="hdc-rename-input" type="text" maxlength="25" bind:value={draft}
           onkeydown={(e) => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); void save(); } else if (e.key === 'Escape') { editing = false; } }} />
    <span class="hdc-rename-row">
      <button type="button" class="oc-btn oc-btn--sm" onclick={(e) => { e.stopPropagation(); editing = false; }}>{t('leader.confirm.cancel')}</button>
      <button type="button" class="oc-btn oc-btn--sm" onclick={(e) => { e.stopPropagation(); void save(); }}>{t('leader.rename.save')}</button>
    </span>
  </li>
{:else}
  <li role="none"><button type="button" role="menuitem" class="hdc-menu-item" data-leader-rename onclick={start}>{t('leader.rename.menu')}</button></li>
{/if}

<style>
  @layer components {
    .hdc-rename { width: 208px; display: flex; flex-direction: column; gap: var(--oc-space-2); padding: var(--oc-space-2); }
    .hdc-rename-label { color: var(--oc-text-secondary); letter-spacing: 0.08em; text-transform: uppercase; }
    .hdc-rename-input { background: var(--oc-ground-field); color: var(--oc-text-bright); border: 1px solid var(--oc-line-rule); border-radius: 2px; padding: var(--oc-space-1) var(--oc-space-2); font-family: var(--font-mono); }
    .hdc-rename-row { display: flex; gap: var(--oc-space-2); justify-content: flex-end; }
  }
</style>
