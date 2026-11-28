
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { nonEmptyErrorMessageOr } from '../errors/failure-reason';
  import { ApiError } from '../../opscenter/api/auth.svelte';
  import Button from '../base/Button.svelte';
  import Field from '../base/Field.svelte';
  import IconButton from '../base/IconButton.svelte';
  import Tag from '../base/Tag.svelte';
  import { abilitiesApi, type AbilitiesApi } from './abilities-api';

  const MAX_LABELS = 16;
  let { machine, labels, api = abilitiesApi, onSaved }: { machine: string; labels: string[]; api?: AbilitiesApi; onSaved?: () => void } = $props();

  let saved = $state<string[] | null>(null);
  let draft = $state('');
  let busy = $state(false);
  let error = $state<string | null>(null);
  const list = $derived(saved ?? labels);

  $effect(() => { void labels; saved = null; });

  async function write(next: string[]): Promise<boolean> {
    if (busy) return false;
    busy = true;
    error = null;
    try {
      saved = await api.putLabels(machine, next);
      onSaved?.();
      return true;
    } catch (failure) {
      error = failure instanceof ApiError && failure.code === 'labels_invalid'
        ? t('roster.can.labels.invalid')
        : nonEmptyErrorMessageOr(failure, t('roster.can.labels.failed'));
      return false;
    } finally {
      busy = false;
    }
  }

  async function add(): Promise<void> {
    const label = draft.trim().toLowerCase();
    if (label === '') return;
    if (list.includes(label)) { draft = ''; return; }
    if (await write([...list, label])) draft = '';
  }
</script>

<div class="pp-tools" data-pm="labels">
  {#each list as label (label)}
    <span class="pp-tool" data-label={label}><Tag>{label}</Tag>
      <IconButton label={t('roster.can.labels.remove', { label })} icon="close" variant="close" disabled={busy} data-act="remove-label" onclick={() => void write(list.filter((x) => x !== label))} />
    </span>
  {:else}<span class="pp-hint">{t('roster.can.labels.none')}</span>{/each}
</div>
{#if list.length < MAX_LABELS}
  <form class="pp-tools" onsubmit={(e) => { e.preventDefault(); void add(); }}>
    <Field aria-label={t('roster.can.labels.field')} placeholder={t('roster.can.labels.placeholder')} maxlength={32} bind:value={draft} disabled={busy} data-act="label-field" />
    <Button type="submit" size="sm" disabled={busy || draft.trim() === ''} data-act="add-label">{t('roster.can.labels.add')}</Button>
  </form>
{:else}<p class="pp-hint">{t('roster.can.labels.full')}</p>{/if}
{#if error}<p class="pp-warn" role="alert" data-act="labels-error">{error}</p>{/if}
