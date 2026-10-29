
<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLButtonAttributes } from 'svelte/elements';

  interface Props extends Omit<HTMLButtonAttributes, 'class' | 'children' | 'role' | 'type' | 'disabled'> {
    label: string;
    icon?: Snippet;
    keyHint?: string;
    reason?: string;
    disabled?: boolean;
    element?: HTMLButtonElement | null;
  }

  let { label, icon, keyHint = '', reason, disabled = false, element = $bindable(null), ...rest }: Props = $props();
</script>

<button
  type="button"
  {...rest}
  class="session-row-menu__item"
  role="menuitem"
  tabindex="-1"
  bind:this={element}
  aria-disabled={disabled ? 'true' : undefined}
  data-tooltip={disabled ? reason : undefined}
  {...(disabled && reason ? { 'aria-description': reason } : {})}
>
  <span class="session-row-menu__icon">{#if icon}{@render icon()}{/if}</span>
  <span class="session-row-menu__label">{label}</span>
  <span class="session-row-menu__key">{keyHint}</span>
  {#if reason && !disabled}<span class="session-row-menu__reason">{reason}</span>{/if}
</button>
