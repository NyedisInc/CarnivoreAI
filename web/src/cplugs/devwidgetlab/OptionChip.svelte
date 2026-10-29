<script lang="ts">
  interface Props {
    label: string;
    checked: boolean;
    kind?: 'check' | 'radio';
    bare?: boolean;
    title?: string;
    onpick: () => void;
  }

  const { label, checked, kind = 'check', bare = false, title, onpick }: Props = $props();
</script>

<button type="button" class="oc-check dwl-choice" class:oc-check--bare={bare} role={kind === 'radio' ? 'radio' : 'checkbox'} aria-checked={checked} data-on={checked ? 'yes' : 'no'} {title} onclick={onpick}>
  {#if kind === 'radio'}<span class="oc-radio" aria-hidden="true"></span>{:else}<span class="oc-check__box" aria-hidden="true"></span>{/if}
  <span class="oc-check__label">{label}</span>
</button>
