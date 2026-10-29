<script lang="ts">
  import { t } from '../sdk';
  import type { TaskManagerMessage } from './huddle-model';
  import { findItem } from './huddle.svelte';
  import { formAnswerRows } from './task-manager-form-answer';

  let { message }: { message: TaskManagerMessage } = $props();

  const form = $derived(findItem(message.item_id)?.thread.find((m) => m.id === message.answers_to)?.form ?? []);
  const rows = $derived(formAnswerRows(message, t, form));
</script>

<dl class="hdfa" data-task-manager-form-answers={message.id}>
  {#each rows as row (row.id)}
    <div class="hdfa-row" data-task-manager-form-answer={row.id} data-state={row.state}>
      {#if row.prompt}<dt class="hdfa-prompt">{row.prompt}</dt>{/if}
      <dd class="hdfa-words">{row.state === 'answered' ? row.words : t(`cplug.huddle.ask.${row.state}`)}</dd>
      {#if row.note}<dd class="hdfa-note">{row.note}</dd>{/if}
    </div>
  {/each}
</dl>

<style>
  @layer components {
    .hdfa {
      display: flex;
      flex-direction: column;
      min-width: 0;
      margin: 0;
    }

    .hdfa-row {
      display: flex;
      flex-direction: column;
      gap: 1px;
      padding: 4px 0;
      min-width: 0;
    }

    .hdfa-row + .hdfa-row {
      border-top: 1px solid var(--oc-line-rule);
    }

    .hdfa-prompt {
      color: var(--oc-text-dim);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.04em;
      overflow-wrap: anywhere;
    }

    .hdfa-words,
    .hdfa-note {
      margin: 0;
      color: var(--oc-text-primary);
      overflow-wrap: anywhere;
      white-space: pre-wrap;
    }

    .hdfa-note {
      color: var(--oc-text-muted);
    }

    .hdfa-row[data-state='skipped'] .hdfa-words,
    .hdfa-row[data-state='dismissed'] .hdfa-words {
      color: var(--oc-text-muted);
    }
  }
</style>
