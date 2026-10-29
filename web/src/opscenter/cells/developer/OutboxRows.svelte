
<script lang="ts">
  import { t } from '../../../lib/i18n/index.svelte';
  import Button from '../../../lib/base/Button.svelte';
  import State from '../../../lib/base/State.svelte';
  import { compact } from '../../lib/format';
  import type { LocalRow } from './sent-model';

  interface Props {
    rows: readonly LocalRow[];
    onretry: (id: string) => void;
    oncopy: (id: string) => void;
    ondiscard: (id: string) => void;
  }

  const { rows, onretry, oncopy, ondiscard }: Props = $props();
</script>

<section class="oc-rq-section" data-sent-section="local">
  <h4 class="oc-rq-head">
    <span>{t('opscenter.sent.local_head')}</span>
    <span class="oc-rq-count" data-rq-count>{compact(rows.length)}</span>
  </h4>
  {#if rows.length === 0}
    <State inline data-rq-none title={t('opscenter.sent.local_none')} />
  {:else}
    <ul class="oc-rq-rows">
      {#each rows as row (row.id)}
        <li class="oc-rq-row oc-ob-row" data-outbox-row={row.id} data-tone={row.failed ? undefined : 'wait'} data-failed={row.failed ? 'true' : undefined}>
          <bdi class="oc-rq-name">{row.name}</bdi>
          <bdi class="oc-rq-area">{row.where}</bdi>
          <span class="oc-rq-time" data-rq-time>{row.words}</span>
          <span class="oc-ob-keys">
            <Button size="sm" data-outbox-key="retry" onclick={() => onretry(row.id)}>{t('opscenter.sent.key.retry')}</Button>
            <Button size="sm" data-outbox-key="copy" onclick={() => oncopy(row.id)}>{t('opscenter.sent.key.copy')}</Button>
            {#if row.failed}
              <Button size="sm" variant="danger" data-outbox-key="discard" onclick={() => ondiscard(row.id)}>{t('opscenter.sent.key.discard')}</Button>
            {/if}
          </span>
        </li>
      {/each}
    </ul>
  {/if}
</section>
