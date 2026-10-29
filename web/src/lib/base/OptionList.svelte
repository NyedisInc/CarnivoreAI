
<script lang="ts" module>
  export interface OptionItem {
    value: string;
    label: string;
    reason?: string;
    recommended?: boolean;
    disabled?: boolean;
  }
</script>

<script lang="ts">
  import { Checkbox, RadioGroup } from 'bits-ui';
  import type { Snippet } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import Tag from './Tag.svelte';
  import type { TagTone } from './classes';

  interface Props {
    options: readonly OptionItem[];
    multiple?: boolean;
    value?: string | string[];
    prompt?: string;
    number?: number | string;
    tag?: string;
    tagTone?: TagTone;
    required?: boolean;
    name?: string;
    recommendedLabel?: string;
    onValueChange?: (value: string | string[]) => void;
    foot?: Snippet;
  }

  const uid = $props.id();
  let {
    options, multiple = false, value = $bindable(multiple ? [] : ''), prompt, number, tag, tagTone = 'neutral',
    required = false, name, recommendedLabel, onValueChange, foot,
  }: Props = $props();

  const promptId = `oc-options-prompt-${uid}`;
  const recLabel = $derived(recommendedLabel ?? t('base.options.recommended'));
</script>

{#snippet head()}
  {#if prompt}
    <div class="oc-options__head">
      {#if number !== undefined}<span class="oc-options__num">{number}.</span>{/if}
      <span class="oc-options__prompt" id={promptId}>{prompt}</span>
      {#if tag}<Tag tone={tagTone}>{tag}</Tag>{/if}
    </div>
  {/if}
{/snippet}

{#snippet text(option: OptionItem)}
  <span class="oc-option__text">
    <span class="oc-option__label">{option.label}{#if option.recommended}<Tag tone="ok">{recLabel}</Tag>{/if}</span>
    {#if option.reason}<span class="oc-option__reason">{option.reason}</span>{/if}
  </span>
{/snippet}

<div class="oc-options">
  {@render head()}
  {#if multiple}
    <Checkbox.Group class="oc-options__rows" aria-labelledby={prompt ? promptId : undefined} {name} {required}
      bind:value={() => value as string[], (v) => (value = v)}
      onValueChange={(v) => onValueChange?.(v)}>
      {#each options as option (option.value)}
        <Checkbox.Root class="oc-option" data-btn="row" value={option.value} disabled={option.disabled}>
          <span class="oc-option__lead" aria-hidden="true"><span class="oc-option__box"></span></span>
          {@render text(option)}
        </Checkbox.Root>
      {/each}
    </Checkbox.Group>
  {:else}
    <RadioGroup.Root class="oc-options__rows" aria-labelledby={prompt ? promptId : undefined} {name} {required}
      bind:value={() => value as string, (v) => (value = v)}
      onValueChange={(v) => onValueChange?.(v)}>
      {#each options as option (option.value)}
        <RadioGroup.Item class="oc-option" data-btn="row" value={option.value} disabled={option.disabled}>
          <span class="oc-option__lead" aria-hidden="true"><span class="oc-radio"></span></span>
          {@render text(option)}
        </RadioGroup.Item>
      {/each}
    </RadioGroup.Root>
  {/if}
  {#if foot}<div class="oc-options__foot">{@render foot()}</div>{/if}
</div>
