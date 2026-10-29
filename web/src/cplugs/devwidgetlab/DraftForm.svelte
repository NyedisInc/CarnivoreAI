<script lang="ts">
  import { t } from '../sdk';
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
    <label class="dwl-label" for="dwl-draft-name">{t('cplug.devwidgetlab.drafts.name')}</label>
    <input id="dwl-draft-name" class="oc-field" type="text" maxlength="80" bind:value={name} />
    <label class="dwl-label" for="dwl-draft-what">{t('cplug.devwidgetlab.drafts.what_new')}</label>
    <textarea id="dwl-draft-what" class="oc-field dwl-form-text" rows="3" maxlength="4000" bind:value={what}></textarea>
    <div class="dwl-row" role="group" aria-label={t('cplug.devwidgetlab.show_in')}>
      <span class="dwl-label">{t('cplug.devwidgetlab.show_in')}</span>
      <div class="dwl-seg">
        {#each NEW_HOSTS as one (one)}
          <button type="button" class="oc-btn oc-btn--sm" aria-pressed={hosts.includes(one)} data-on={hosts.includes(one) ? 'yes' : 'no'}
            onclick={() => (hosts = flipIn(hosts, one))}>{t(`cplug.devwidgetlab.host.${one}`)}</button>
        {/each}
      </div>
    </div>
    <div class="dwl-row" role="group" aria-label={t('cplug.devwidgetlab.size')}>
      <span class="dwl-label">{t('cplug.devwidgetlab.sizes.pick')}</span>
      <div class="dwl-seg">
        {#each NEW_SIZES as one (one)}
          <button type="button" class="oc-btn oc-btn--sm" aria-pressed={sizes.includes(one)} data-on={sizes.includes(one) ? 'yes' : 'no'}
            onclick={() => (sizes = flipIn(sizes, one))}>{one}</button>
        {/each}
      </div>
    </div>
    <div class="dwl-row">
      <label class="dwl-label" for="dwl-draft-category">{t('cplug.devwidgetlab.drafts.category')}</label>
      <select id="dwl-draft-category" class="oc-field" bind:value={category}>
        {#each NEW_CATEGORIES as one (one)}<option value={one}>{t(`widgets.page.category.${one}`)}</option>{/each}
      </select>
    </div>
  {:else}
    <label class="dwl-label" for="dwl-draft-what">{t('cplug.devwidgetlab.drafts.what_revision')}</label>
    <textarea id="dwl-draft-what" class="oc-field dwl-form-text" rows="4" maxlength="4000" placeholder={t('cplug.devwidgetlab.drafts.what_placeholder')} bind:value={what}></textarea>
    <ul class="dwl-context-list">
      {#each Object.entries(context) as [key, value] (key)}<li class="dwl-hint">{key}: {value}</li>{/each}
    </ul>
  {/if}
  {#if error}<p class="dwl-note dwl-note--error">{error}</p>{/if}
  <div class="dwl-seg">
    <button type="submit" class="oc-btn oc-btn--sm oc-btn--confirm" disabled={!ready || busy}>{mode === 'new' ? t('cplug.devwidgetlab.drafts.create') : t('cplug.devwidgetlab.drafts.start_revision')}</button>
    <button type="button" class="oc-btn oc-btn--sm" onclick={oncancel}>{t('cplug.devwidgetlab.drafts.cancel')}</button>
  </div>
</form>
