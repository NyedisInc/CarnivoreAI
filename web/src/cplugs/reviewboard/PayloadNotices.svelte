<script lang="ts">
  import { t } from '../sdk';
  import type { BoardRevision } from './board-model';
  import type { PayloadLoop } from './payload-loop.svelte';
  import { savesOf } from './payload-model';
  import { confirmKey } from './round-confirm';

  interface Props {
    revision: BoardRevision;
    loop: PayloadLoop;
  }

  let { revision, loop }: Props = $props();

  const viewed = $derived(savesOf(revision).find((s) => s.n === loop.viewing) ?? null);
</script>

{#if loop.confirm || loop.failed || viewed?.note || !loop.payload}
  <div class="rb-views rb-notices" data-payload-notices>
    {#if loop.confirm}
      <p class="rb-confirm" data-confirm data-delivered={loop.confirm.delivered} data-kept={loop.confirm.kept ? 'true' : undefined} role="status">
        {t(confirmKey(loop.confirm), { title: loop.confirm.title, item: loop.confirm.item })}
      </p>
    {/if}
    {#if loop.failed}<p class="rb-warn" role="status" data-payload-failed>{t('cplug.reviewboard.payload.failed')}</p>{/if}
    {#if viewed?.note}<p class="rb-note-text" data-payload-save-note>{viewed.note}</p>{/if}
    {#if !loop.payload}<p class="rb-note-text" data-payload-waiting>{t('cplug.reviewboard.payload.waiting')}</p>{/if}
  </div>
{/if}
