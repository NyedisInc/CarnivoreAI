<script lang="ts">
  import { t } from './strings';

  interface Props { revisions: Array<{ revision: string; answered: boolean }>; shown: string; pick: (revision: string) => void }
  let { revisions, shown, pick }: Props = $props();
</script>

<span class="pb-revs" role="group" aria-label={t('cplug.reviewboard.public.page.revs')}>
  {#each revisions as r (r.revision)}
    <button type="button" class="pb-rev" data-btn="quiet" data-size="sm" data-visitor-rev={r.revision} aria-pressed={r.revision === shown}
            data-answered={r.answered ? '' : undefined} title={t(r.answered ? 'cplug.reviewboard.public.page.rev_answered' : 'cplug.reviewboard.public.page.rev_open', { revision: r.revision })}
            onclick={() => pick(r.revision)}>{r.revision}</button>
  {/each}
</span>
