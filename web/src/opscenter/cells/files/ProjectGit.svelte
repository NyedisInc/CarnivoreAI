<script lang="ts">
  import type { SessionGitStatus } from '../../api/types';
  import { t } from '../../../lib/i18n/index.svelte';
  import { fk } from './labels';

  let { git, narrow }: { git: SessionGitStatus | null; narrow: boolean } = $props();

  const ok = $derived(git?.state === 'ok' ? git : null);
  const branch = $derived.by(() => {
    if (!ok) return '';
    if (ok.detached) return fk('git.detached', { sha: ok.head_short ?? '' });
    return ok.unborn ? fk('git.unborn') : (ok.branch ?? '');
  });
</script>

{#if ok}
  <span class="pg" data-files-git="ok">
    <bdi class="pg-branch">{branch}</bdi>
    {#if ok.ahead}<span class="pg-num" aria-label={fk('git.ahead', { n: ok.ahead })}>&uarr;{ok.ahead}</span>{/if}
    {#if ok.behind}<span class="pg-num" aria-label={fk('git.behind', { n: ok.behind })}>&darr;{ok.behind}</span>{/if}
    {#if !narrow && ok.head_short && !ok.detached}<span class="pg-sha">{ok.head_short}</span>{/if}
  </span>
{:else if git}
  <span class="pg" data-files-git={git.state}>{t(`git.changes.${git.state}`)}</span>
{/if}

<style>
  @layer components {
    .pg {
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-1-5);
      min-width: 0;
      font-size: var(--oc-fs-label);
      color: var(--oc-text-muted);
    }

    .pg-branch {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      color: var(--oc-text-secondary);
    }

    .pg-num {
      color: var(--oc-text-secondary);
    }
  }
</style>
