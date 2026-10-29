<script lang="ts">
  import { t } from '../../sdk';
  import type { SwarmAgentState, SwarmCheckpoint, SwarmEarlierConversation } from './chat-api';
  import { checkpointBlock, rewindBlock } from './chat-model';

  let { agentState, commits, reason, conversations, loading, failed, busy, onRewind, onResume, onClose }: {
    agentState: SwarmAgentState | null; commits: SwarmCheckpoint[]; reason: string | null; conversations: SwarmEarlierConversation[];
    loading: boolean; failed: string; busy: string; onRewind: (sha: string) => void; onResume: (uuid: string) => void; onClose: () => void;
  } = $props();

  const block = $derived(rewindBlock(agentState));

  function short(id: string): string {
    return id.slice(0, 8);
  }

  function day(iso: string): string {
    return iso.slice(0, 16).replace('T', ' ');
  }
</script>

<section class="hdw" data-chat-rewind>
  <header class="hdw-bar">
    <span class="hdw-label">{t('cplug.huddle.chat.rewind.title')}</span>
    <span class="hdw-spacer"></span>
    <button type="button" class="oc-btn oc-btn--sm" onclick={onClose}>{t('cplug.huddle.chat.rewind.close')}</button>
  </header>
  {#if block}<p class="hdw-note">{t(block)}</p>{/if}
  {#if failed}<p class="hdw-fail" role="status">{failed}</p>{/if}
  {#if loading}
    <p class="hdw-note">{t('cplug.huddle.chat.loading')}</p>
  {:else}
    <h4 class="hdw-head">{t('cplug.huddle.chat.rewind.checkpoints')}</h4>
    {#if commits.length === 0}
      <p class="hdw-note">{reason ?? t('cplug.huddle.chat.rewind.no_checkpoints')}</p>
    {:else}
      <ul class="hdw-list">
        {#each commits as commit (commit.sha)}
          {@const why = block ?? checkpointBlock(commit.kind)}
          <li class="hdw-row" data-rewind-sha={commit.sha}>
            <span class="hdw-what">
              <span class="hdw-sha">{short(commit.sha)}</span>
              <span class="hdw-subject">{commit.subject}</span>
              <span class="hdw-when">{day(commit.at)}</span>
            </span>
            <button type="button" class="oc-btn oc-btn--sm" disabled={!!why || !!busy} title={why ? t(why) : ''}
                    onclick={() => onRewind(commit.sha)}>
              {t('cplug.huddle.chat.rewind.to_here')}
            </button>
          </li>
        {/each}
      </ul>
    {/if}
    <h4 class="hdw-head">{t('cplug.huddle.chat.rewind.conversations')}</h4>
    {#if conversations.length === 0}
      <p class="hdw-note">{t('cplug.huddle.chat.rewind.no_conversations')}</p>
    {:else}
      <ul class="hdw-list">
        {#each conversations as conv (conv.wake_id)}
          {@const why = block ?? (conv.transcript_present ? null : 'cplug.huddle.chat.rewind.block_transcript')}
          <li class="hdw-row" data-rewind-conversation={conv.conversation_uuid}>
            <span class="hdw-what">
              <span class="hdw-sha">{short(conv.conversation_uuid)}</span>
              <span class="hdw-subject">{conv.reason ?? ''}</span>
              <span class="hdw-when">{day(conv.started_at)}</span>
            </span>
            <button type="button" class="oc-btn oc-btn--sm" disabled={!!why || !!busy} title={why ? t(why) : ''}
                    onclick={() => onResume(conv.conversation_uuid)}>
              {t('cplug.huddle.chat.rewind.resume')}
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</section>

<style>
  @layer components {
    /* box-shadow */
    .hdw {
      flex: none;
      display: flex;
      flex-direction: column;
      min-width: 0;
      max-height: 55%;
      overflow-y: auto;
      overscroll-behavior: contain;
      background: var(--oc-ground-page);
      box-shadow: inset 0 -1px 0 var(--oc-line-rule);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
    }

    .hdw-bar {
      flex: none;
      display: flex;
      align-items: center;
      gap: 8px;
      height: 32px;
      padding: 0 8px;
      background: var(--oc-ground-titlerow);
      box-shadow: inset 0 -1px 0 var(--oc-line-rule);
    }

    .hdw-label {
      color: var(--oc-orange);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .hdw-spacer { flex: 1; }

    .hdw-head {
      margin: 0;
      padding: 8px 8px 4px;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
      font-weight: normal;
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .hdw-note {
      margin: 0;
      padding: 4px 8px;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-hint);
    }

    .hdw-fail {
      margin: 0;
      padding: 4px 8px;
      color: var(--oc-coral);
      font-size: var(--oc-fs-hint);
    }

    .hdw-list {
      display: flex;
      flex-direction: column;
      margin: 0;
      padding: 0;
      list-style: none;
    }

    .hdw-row {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      padding: 4px 8px;
      box-shadow: inset 0 1px 0 var(--oc-line-faint);
    }

    .hdw-what {
      flex: 1;
      display: flex;
      flex-wrap: wrap;
      gap: 0 8px;
      min-width: 0;
    }

    .hdw-sha { color: var(--oc-text-secondary); }

    .hdw-subject {
      min-width: 0;
      color: var(--oc-text-primary);
      overflow-wrap: anywhere;
    }

    .hdw-when {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
    }
  }
</style>
