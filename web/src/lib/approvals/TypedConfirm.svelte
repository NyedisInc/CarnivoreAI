<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { Field } from '../base';

  let { expected, value = $bindable(''), disabled = false, id }:
    { expected: string; value?: string; disabled?: boolean; id: string } = $props();
</script>

<div class="ap-confirm" data-approval-confirm={id}>
  <p class="ap-confirm__ask">{t('approvals.type_to_confirm', { name: expected })}</p>
  <Field block maxlength={1000} autocomplete="off" spellcheck={false}
    data-approval-confirm-input bind:value {disabled} placeholder={expected}
    aria-label={t('approvals.type_to_confirm', { name: expected })} />
</div>

<style>
  @layer components {
    .ap-confirm {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-1);
      min-width: 0;
    }

    .ap-confirm__ask {
      margin: 0;
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
      color: var(--oc-coral);
      overflow-wrap: anywhere;
    }
  }
</style>
