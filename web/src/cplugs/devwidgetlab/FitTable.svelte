<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { t } from '../sdk';
  import { Button } from '../sdk/ui';
  import { fitTableState } from './lab-api';
  import { cellState, fitColumns, type MatrixState } from './lab-model';

  interface Props {
    seq?: number;
    onstate?: (next: MatrixState) => void;
    onpick: (widget: string, host?: string, size?: string) => void;
  }

  const { seq = 0, onstate, onpick }: Props = $props();

  const POLL_MS = 5000;

  let read = $state<MatrixState | null>(null);
  let refusal = $state('');
  let timer: ReturnType<typeof setTimeout> | null = null;

  const table = $derived(read?.table ?? null);
  const columns = $derived(table ? fitColumns(table) : []);

  async function refresh(): Promise<void> {
    try {
      read = await fitTableState();
      refusal = '';
    } catch (error) {
      console.warn('[widget lab] fit table', error);
      refusal = t('cplug.devwidgetlab.fit.unreadable');
      return;
    }
    onstate?.(read);
    if (timer !== null) clearTimeout(timer);
    timer = read.running ? setTimeout(() => void refresh(), POLL_MS) : null;
  }

  onMount(() => void refresh());
  $effect(() => {
    if (seq > 0) void refresh();
  });
  onDestroy(() => {
    if (timer !== null) clearTimeout(timer);
  });
</script>

<section class="dwl-fit">
  {#if read?.running}<p class="dwl-note">{t('cplug.devwidgetlab.fit.running')}</p>{/if}
  {#if refusal}<p class="dwl-note dwl-note--error">{refusal}</p>{/if}
  {#if read && !read.running && read.exit === 2}<p class="dwl-note dwl-note--error">{t('cplug.devwidgetlab.fit.undetermined')}</p>{/if}

  {#if table}
    <p class="dwl-note" data-testid="fit-counts">
      {t('cplug.devwidgetlab.fit.counts', { pass: table.counts.pass, fail: table.counts.fail, unsupported: table.counts.unsupported })}
      <span class="dwl-hint">{table.generated_at}</span>
    </p>
    <div class="dwl-fit-scroll">
      <table class="dwl-fit-table">
        <thead>
          <tr>
            <th class="dwl-fit-widget">{t('cplug.devwidgetlab.widget')}</th>
            {#each columns as col (col.key)}<th title={col.key}>{col.host}<br />{col.size}</th>{/each}
          </tr>
        </thead>
        <tbody>
          {#each table.widgets as row (row.widget)}
            <tr>
              <th class="dwl-fit-widget" scope="row"><Button variant="quiet" size="sm" data-fit-name onclick={() => onpick(row.widget)}>{row.widget}</Button></th>
              {#each columns as col (col.key)}
                {@const kind = cellState(row, col.key)}
                <td>
                  <Button variant="quiet" size="sm" data-fit-cell data-state={kind} aria-label={`${row.widget} ${col.key} ${kind}`} disabled={kind === 'unsupported'}
                    onclick={() => onpick(row.widget, col.host, col.size)}>{t(`cplug.devwidgetlab.fit.cell.${kind}`)}</Button>
                </td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:else if read && !read.running}
    <p class="dwl-note">{t('cplug.devwidgetlab.fit.empty')}</p>
  {/if}
</section>
