<script lang="ts">
  import { sessionGit, releaseSessionGit } from '../../api/session-git.svelte';
  import type { Resource } from '../../api/poll.svelte';
  import type { SessionGitStatus } from '../../api/types';
  import { t } from '../../../lib/i18n/index.svelte';
  import { chipParts, chipTitle } from './git-chip';

  let { sessionId, width = 0 }: { sessionId: string; width?: number } = $props();

  let res = $state<Resource<SessionGitStatus> | null>(null);

  $effect(() => {
    const id = sessionId;
    if (!id) { res = null; return; }
    res = sessionGit(id);
    return () => releaseSessionGit(id);
  });

  const data = $derived(res?.data ?? null);
  const parts = $derived(chipParts(data, width, !!res && !data && res.status !== 'loading'));
</script>

{#if parts}
  <span class="oc-gc" role="group" aria-label={t('git.chip.region')} title={chipTitle(data, t)}
    data-git-chip="" data-kind={parts.kind}>
    {#if parts.kind === 'unknown'}
      <span class="oc-gc-branch" data-gc="branch">{t('git.chip.unknown')}</span>
    {:else}
      {#if parts.repo}<span class="oc-gc-repo" data-gc="repo">{parts.repo}:</span>{/if}
      <span class="oc-gc-branch" data-gc="branch">{parts.branch || (parts.unborn ? t('git.chip.unborn') : '')}</span>
      {#if parts.dirty}<span class="oc-gc-dot" data-gc="dot" role="img" aria-label={t('git.chip.dirty')}></span>{/if}
      {#if parts.sync}<span class="oc-gc-sync" data-gc="sync">{parts.sync}</span>{/if}
    {/if}
  </span>
{/if}

<style>
  @layer components {
    .oc-gc {
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-1);
      flex: 0 1 auto;
      min-width: 0;
      padding: 0 10px 0 0;
      font-size: var(--oc-fs-label);
      white-space: nowrap;
      color: var(--oc-text-secondary);
    }

    .oc-gc-repo {
      color: var(--oc-text-dim);
      flex: 0 0 auto;
    }

    .oc-gc-branch {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .oc-gc[data-kind='unknown'] .oc-gc-branch {
      color: var(--oc-text-dim);
    }

    .oc-gc-dot {
      flex: 0 0 auto;
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--oc-yellow-bright);
    }

    .oc-gc-sync {
      flex: 0 0 auto;
      color: var(--oc-text-dim);
    }
  }
</style>
