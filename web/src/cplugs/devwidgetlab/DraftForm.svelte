<script lang="ts">
  import { t } from '../sdk';
  import { Button, Checkbox, Field, Select } from '../sdk/ui';
  import { NEW_CATEGORIES, NEW_HOSTS, NEW_HOSTS_DEFAULT, NEW_SIZES, type DraftRequest } from './drafts-model';
  import { flipIn } from './lab-selection';

  interface Props {
    mode: 'new' | 'revision';
    widget: string;
    context: Record<string, string>;
    busy: boolean;
    error: string;
    onsubmit: (request: DraftRequest) => void;
    oncancel: () => void;
  }

  const { mode, widget, context, busy, error, onsubmit, oncancel }: Props = $props();

  let name = $state('');
  let what = $state('');
  let hosts = $state<string[]>([...NEW_HOSTS_DEFAULT]);
  let sizes = $state<string[]>(['small', 'wide']);
  let category = $state('tools');

  const ready = $derived(mode === 'new' ? name.trim() !== '' : what.trim() !== '');

  function submit(event: Event): void {
    event.preventDefault();
    if (!ready || busy) return;
    onsubmit(mode === 'new' ? { kind: 'new', name: name.trim(), what, hosts, sizes, category } : { kind: 'revision', widget, name: '', what, context });
  }
</script>

<svelte:window onkeydown={(event) => { if (event.key === 'Escape') { event.stopPropagation(); oncancel(); } }} />

<form class="dwl-form" onsubmit={submit}>
  <p class="dwl-label">{mode === 'new' ? t('cplug.devwidgetlab.drafts.form_new') : t('cplug.devwidgetlab.drafts.form_revision', { widget })}</p>
  {#if mode === 'new'}
    <Field id="dwl-draft-name" label={t('cplug.devwidgetlab.drafts.name')} maxlength={80} bind:value={name} />
    <Field id="dwl-draft-what" label={t('cplug.devwidgetlab.drafts.what_new')} multiline rows={3} maxlength={4000} bind:value={what} />
    <div class="dwl-row" role="group" aria-label={t('cplug.devwidgetlab.show_in')}>
      <span class="dwl-label">{t('cplug.devwidgetlab.show_in')}</span>
      <div class="dwl-seg">
        {#each NEW_HOSTS as one (one)}
          <Checkbox label={t(`cplug.devwidgetlab.host.${one}`)} data-host-choice={one} checked={hosts.includes(one)} onchange={() => (hosts = flipIn(hosts, one))} />
        {/each}
      </div>
    </div>
    <div class="dwl-row" role="group" aria-label={t('cplug.devwidgetlab.size')}>
      <span class="dwl-label">{t('cplug.devwidgetlab.sizes.pick')}</span>
      <div class="dwl-seg">
        {#each NEW_SIZES as one (one)}
          <Checkbox label={one} data-size-choice={one} checked={sizes.includes(one)} onchange={() => (sizes = flipIn(sizes, one))} />
        {/each}
      </div>
    </div>
    <Select id="dwl-draft-category" label={t('cplug.devwidgetlab.drafts.category')} bind:value={category}
      options={NEW_CATEGORIES.map((one) => ({ value: one, label: t(`widgets.page.category.${one}`) }))} />
  {:else}
    <Field id="dwl-draft-what" label={t('cplug.devwidgetlab.drafts.what_revision')} multiline rows={4} maxlength={4000} placeholder={t('cplug.devwidgetlab.drafts.what_placeholder')} bind:value={what} />
    <ul class="dwl-context-list">
      {#each Object.entries(context) as [key, value] (key)}<li class="dwl-hint">{key}: {value}</li>{/each}
    </ul>
  {/if}
  {#if error}<p class="dwl-note dwl-note--error">{error}</p>{/if}
  <div class="dwl-seg">
    <Button type="submit" variant="confirm" size="sm" disabled={!ready || busy}>{mode === 'new' ? t('cplug.devwidgetlab.drafts.create') : t('cplug.devwidgetlab.drafts.start_revision')}</Button>
    <Button size="sm" onclick={oncancel}>{t('cplug.devwidgetlab.drafts.cancel')}</Button>
  </div>
</form>
