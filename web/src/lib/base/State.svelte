<!-- title="could not read the list" -->
<script lang="ts" module>
  export type StateKind = 'empty' | 'loading' | 'warn' | 'error';
</script>

<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';
  import { t } from '../i18n/index.svelte';

  interface Props extends Omit<HTMLAttributes<HTMLDivElement>, 'class' | 'children'> {
    kind?: StateKind;
    title?: string;
    hint?: string;
    inline?: boolean;
    glyph?: Snippet;
    children?: Snippet;
    actions?: Snippet;
    actionLabel?: string;
    onAction?: () => void;
    role?: string;
    class?: string;
  }

  let {
    kind = 'empty', title, hint, inline = false, glyph, children, actions, actionLabel, onAction, role, class: extra = '', ...rest
  }: Props = $props();

  const DEFAULT_TITLE: Record<StateKind, string> = { empty: 'base.state.empty', loading: 'base.state.loading', warn: 'base.state.warn', error: 'base.state.error' };
  const words = $derived(title ?? t(DEFAULT_TITLE[kind]));
  const buttonWords = $derived(actionLabel ?? (kind === 'error' ? t('base.state.retry') : undefined));
</script>

<div
  {...rest}
  class={['oc-state', inline && 'oc-state--inline', extra]}
  data-state={kind}
  role={role ?? (kind === 'error' ? 'alert' : 'status')}
  aria-busy={kind === 'loading' ? 'true' : undefined}
>
  {#if glyph}<span class="oc-state__glyph" aria-hidden="true">{@render glyph()}</span>{/if}
  <p class="oc-state__title">{words}</p>
  {#if hint}<p class="oc-state__hint">{hint}</p>{/if}
  {#if children}{@render children()}{/if}
  {#if actions || (onAction && buttonWords)}
    <div class="oc-state__actions">
      {#if onAction && buttonWords}<button type="button" data-btn="secondary" data-size="sm" onclick={onAction}>{buttonWords}</button>{/if}
      {#if actions}{@render actions()}{/if}
    </div>
  {/if}
</div>
