
<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';
  import FoldChevron from '../../opscenter/ui/FoldChevron.svelte';

  interface Props extends Omit<HTMLAttributes<HTMLElement>, 'class' | 'children' | 'title'> {
    title?: string;
    meta?: string;
    foldable?: boolean;
    onopen?: () => void;
    open?: boolean;
    compact?: boolean;
    headingLevel?: 2 | 3 | 4 | 5 | 6;
    lead?: Snippet;
    actions?: Snippet;
    children: Snippet;
    foot?: Snippet;
  }

  const uid = $props.id();
  let {
    title, meta, foldable = false, onopen, open = $bindable(true), compact = false, headingLevel = 3, lead, actions, children, foot, ...rest
  }: Props = $props();

  const bodyId = `oc-card-body-${uid}`;
  const titleId = `oc-card-title-${uid}`;
  const shown = $derived(!foldable || open);
  const hasHead = $derived(Boolean(title || meta || lead || actions));

  $effect.pre(() => {
    if ((foldable || onopen) && !title) throw new Error('Card: foldable and onopen need a title, the button has no label without it');
  });
</script>

<section {...rest} class="oc-card" class:oc-card--compact={compact} data-oc-base data-open={shown ? 'true' : 'false'} aria-labelledby={title ? titleId : undefined}>
  {#if hasHead}<div class="oc-card__head">
    {#if lead}<span class="oc-card__lead">{@render lead()}</span>{/if}
    {#if !title}
      {#if meta}<span class="oc-card__meta">{meta}</span>{/if}
    {:else if foldable}
      <button type="button" class="oc-card__toggle" data-btn="row" aria-expanded={open} aria-controls={bodyId}
        onclick={() => (open = !open)}>
        <span class="oc-card__title" id={titleId} role="heading" aria-level={headingLevel}>{title}</span>
        {#if meta}<span class="oc-card__meta">{meta}</span>{/if}
        <FoldChevron />
      </button>
    {:else if onopen}
      <span class="oc-card__title" id={titleId} role="heading" aria-level={headingLevel}><button type="button" class="oc-card__open" onclick={(e) => { e.stopPropagation(); onopen(); }}>{title}</button></span>
      {#if meta}<span class="oc-card__meta">{meta}</span>{/if}
    {:else}
      <span class="oc-card__title" id={titleId} role="heading" aria-level={headingLevel}>{title}</span>
      {#if meta}<span class="oc-card__meta">{meta}</span>{/if}
    {/if}
    {#if actions}<div class="oc-card__actions">{@render actions()}</div>{/if}
  </div>{/if}
  <div class="oc-card__body" id={bodyId} hidden={!shown}>{@render children()}</div>
  {#if foot}<div class="oc-card__foot" hidden={!shown}>{@render foot()}</div>{/if}
</section>
