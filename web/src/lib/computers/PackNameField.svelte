<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { errorCode, readPackName, writePackName } from '../hosts-page/federation-api';

  let value = $state('');
  let saved = $state('');
  let problem = $state<string | null>(null);
  let busy = $state(false);

  onMount(() => {
    void readPackName().then((name) => { value = saved = name ?? ''; }).catch(() => { problem = t('computers.pack_name.failed'); });
  });

  async function save(event: Event): Promise<void> {
    event.preventDefault();
    if (busy) return;
    busy = true;
    problem = null;
    try {
      const name = await writePackName(value.trim() === '' ? null : value.trim());
      value = saved = name ?? '';
    } catch (error) {
      problem = errorCode(error) === 'bad_pack_name' ? t('computers.pack_name.bad') : t('computers.pack_name.failed');
    } finally {
      busy = false;
    }
  }
</script>

<form class="cmp-region cmp-packname" data-cmp="pack-name" onsubmit={save}>
  <label class="cmp-packname__field"><span class="pl-label">{t('computers.pack_name.label')}</span>
    <span class="cmp-packname__row">
      <input class="oc-field" type="text" maxlength="32" autocomplete="off" autocapitalize="off" spellcheck="false" bind:value
        placeholder={t('computers.pack_name.placeholder')} data-cmp="pack-name-input" />
      <button type="submit" class="modal-btn modal-btn-secondary" data-cmp="pack-name-save" disabled={busy || value.trim() === saved}>{t('computers.pack_name.save')}</button>
    </span></label>
  {#if problem}<p class="cmp-blocker" role="alert" data-cmp="pack-name-error">{problem}</p>{/if}
  <p class="cmp-note" data-cmp="pack-name-note">{t('computers.pack_name.note')}</p>
</form>
