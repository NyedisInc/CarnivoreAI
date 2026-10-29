
<script lang="ts">
    import { t } from '../i18n/index.svelte';
    import IconButton from '../base/IconButton.svelte';

    interface Props {
        hasPrev: boolean;
        hasNext: boolean;
        overflows: boolean;
        expanded: boolean;
        onpress: (event: MouseEvent) => void;
        onprev: () => void;
        onnext: () => void;
        ontoggle: () => void;
    }

    let {
        hasPrev,
        hasNext,
        overflows,
        expanded,
        onpress,
        onprev,
        onnext,
        ontoggle,
    }: Props = $props();
</script>


{#if overflows}
    <IconButton
        label={expanded ? t('prompt_header.less') : t('prompt_header.more')}
        variant="quiet"
        data-prompt-key="more"
        aria-expanded={expanded}
        onclick={ontoggle}
    >
        <svg
            width="14"
            height="14"
            viewBox="0 0 16 16"
            fill={expanded ? 'none' : 'currentColor'}
            aria-hidden="true"
        >
            {#if expanded}
                <path d="M12 10 8 6l-4 4" stroke="currentColor" stroke-width="1.5"
                      stroke-linecap="round" stroke-linejoin="round" />
            {:else}
                <circle cx="3" cy="8" r="1.4" />
                <circle cx="8" cy="8" r="1.4" />
                <circle cx="13" cy="8" r="1.4" />
            {/if}
        </svg>
    </IconButton>
{/if}
<IconButton
    label={t('prompt_header.previous')}
    variant="quiet"
    data-prompt-key="prev"
    disabled={!hasPrev}
    onmousedown={onpress}
    onclick={onprev}
>
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path d="M12 10 8 6l-4 4" stroke="currentColor" stroke-width="1.5"
              stroke-linecap="round" stroke-linejoin="round" />
    </svg>
</IconButton>
<IconButton
    label={t('prompt_header.next')}
    variant="quiet"
    data-prompt-key="next"
    disabled={!hasNext}
    onmousedown={onpress}
    onclick={onnext}
>
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path d="m4 6 4 4 4-4" stroke="currentColor" stroke-width="1.5"
              stroke-linecap="round" stroke-linejoin="round" />
    </svg>
</IconButton>

<style>
  @layer components {
      :global([data-prompt-key]) {
          --oc-ibtn-size: 22px;
      }

      @media (max-width: 768px) {
          :global([data-prompt-key]) {
              --oc-ibtn-size: 28px;
              --_btn-h: 28px;
              width: 28px;
              height: 28px;
          }
      }
  }
</style>
