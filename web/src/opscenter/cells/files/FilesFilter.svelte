<script lang="ts">
  import type { Snippet } from 'svelte';
  import { Field } from '../../../lib/base';
  import { t } from '../../../lib/i18n/index.svelte';

  let {
    value = $bindable(''),
    input = $bindable(null),
    maxlength,
    placeholder,
    label,
    onkeydown,
    after,
  }: {
    value?: string;
    input?: HTMLInputElement | null;
    maxlength: number;
    placeholder: string;
    label: string;
    onkeydown: (event: KeyboardEvent) => void;
    after?: Snippet;
  } = $props();
</script>

<div class="ff-row" data-files-filter>
  <Field variant="search" block {label} bind:value bind:input {maxlength} {placeholder} {onkeydown} spellcheck="false" autocomplete="off"
    clearLabel={t('drawer.search.clear')} />
  {@render after?.()}
</div>

<style>
  @layer components {
    .ff-row {
      flex: 0 0 auto;
      display: flex;
      align-items: center;
      gap: var(--oc-space-1);
      padding: var(--oc-space-1) var(--oc-space-2);
      background: var(--oc-ground-chrome);
      border-bottom: var(--oc-border, 1px) solid var(--oc-line-panel);
    }
  }
</style>
