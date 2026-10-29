<!-- position: relative -->
<script lang="ts">
    import { t } from '../i18n/index.svelte';
    import IconButton from '../base/IconButton.svelte';
    import { buttonAttrs } from '../base/classes';
    import './search-globals.css';
    import PromptHeader from './PromptHeader.svelte';
    import PromptRail from './PromptRail.svelte';
    import type { SearchController } from './search-controller.svelte';

    interface Props {
        controller: SearchController;
    }

    let { controller }: Props = $props();

    const CHEVRON_UP = 'M12 10 8 6l-4 4';
    const CHEVRON_DOWN = 'm4 6 4 4 4-4';

    let upward = $derived(controller.direction === 'bottom_up');

    let nextGlyph = $derived(upward ? CHEVRON_UP : CHEVRON_DOWN);
    let prevGlyph = $derived(upward ? CHEVRON_DOWN : CHEVRON_UP);

    let directionTitle = $derived(
        upward ? t('search.direction.bottom_up') : t('search.direction.top_down'),
    );

    let promptsOnlyTitle = $derived(controller.promptsOnlyTitle);

    let panelEl = $state<HTMLDivElement | null>(null);
    let inputEl = $state<HTMLInputElement | null>(null);

    $effect(() => {
        controller.setPanelElement(panelEl);
        return () => controller.setPanelElement(null);
    });

    $effect(() => {
        controller.setInputElement(inputEl);
        return () => controller.setInputElement(null);
    });
</script>

<div
    bind:this={panelEl}
    class="terminal-search-panel"
    class:is-open={controller.opened && !controller.driven}
    role="search"
    aria-label={t('terminal.search.label')}
>
    <div class="terminal-search__row">
        <!-- something else -->
        <input
            bind:this={inputEl}
            bind:value={controller.query}
            oninput={() => controller.onType()}
            type="search"
            class="terminal-search__input"
            aria-label={t('terminal.search.label')}
            placeholder={t('terminal.search.label')}
            autocomplete="off"
            autocorrect="off"
            autocapitalize="off"
            spellcheck="false"
        />
        
        <span class="terminal-search__count" aria-live="polite">{controller.countText}</span>
        
        
        <button
            type="button"
            {...buttonAttrs('quiet', 'icon')}
            data-search-key="direction"
            aria-label={t('search.direction.toggle')}
            aria-pressed={upward}
            title={directionTitle}
            onclick={() => controller.toggleDirection()}
        >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path
                    d="M8 2v12"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                />
                <path
                    d={upward ? 'M4.5 5.5 8 2l3.5 3.5' : 'M4.5 10.5 8 14l3.5-3.5'}
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                />
            </svg>
        </button>
        
        <span class="terminal-search__tip" data-tooltip={promptsOnlyTitle}>
            
            <button
                type="button"
                {...buttonAttrs('quiet', 'icon')}
                data-search-key="prompts-only"
                aria-label={t('search.prompts_only.toggle')}
                aria-pressed={controller.promptsOnly}
                disabled={!controller.promptsOnlyAvailable}
                onclick={() => controller.togglePromptsOnly()}
            >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                    <path
                        d="m3 5 7 7-7 7m10 0h8"
                        stroke="currentColor"
                        stroke-width="1.5"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                    />
                </svg>
            </button>
        </span>
        <IconButton label={t('terminal.search.prev')} variant="quiet" data-search-key="prev" onclick={() => controller.step('prev')}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path
                    d={prevGlyph}
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                />
            </svg>
        </IconButton>
        <IconButton label={t('terminal.search.next')} variant="quiet" data-search-key="next" onclick={() => controller.step('next')}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path
                    d={nextGlyph}
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                />
            </svg>
        </IconButton>
        <IconButton label={t('terminal.search.close')} variant="close" data-search-key="close" onclick={() => controller.close()}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path
                    d="m4 4 8 8M12 4l-8 8"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                />
            </svg>
        </IconButton>
    </div>
</div>

<!-- hidden  pointer-events: none -->
<div class="terminal-prompt-rail-host">
    <PromptRail rail={controller.rail} />
</div>



{#if !controller.headerHosted}
    <PromptHeader rail={controller.rail} onfocusterm={() => controller.focusTerminal()} />
{/if}

<style>
  @layer components {
        /* --color- */
        :global(.terminal-container) {
            --terminal-search-match-bg: #4d3b30;
            --terminal-search-match-border: #8a5a44;
            --terminal-search-match-ruler: #8a5a44;
            --terminal-search-active-bg: #d77757;
            --terminal-search-active-border: #e88768;
            --terminal-search-active-ruler: #d77757;
        }

        .terminal-search-panel {
            display: none;
            position: absolute;
            top: 15px;
            right: 39px;
            z-index: 1110;

            /* 560px fits a full path or a long flag beside the counter and
             * the four controls without the field collapsing, and still
             * leaves the pane readable behind it; the calc is the same
             * "never overflow" clamp as before, now counting the rail. */
            width: min(560px, calc(100% - 54px));
            box-sizing: border-box;
            padding: 6px var(--oc-space-2);

            border: 1px solid var(--oc-line-panel);
            border-radius: var(--oc-radius-sm);
            background: var(--oc-ground-raised);
            color: var(--oc-text-primary);

            font-family: var(--font-mono);
            font-size: 13px;
            line-height: 1.4;
        }

        .terminal-search-panel.is-open {
            display: block;
        }

        /* the base icon button */
        .terminal-search__row {
            --oc-ibtn-size: 26px;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        /* min-width: 0 */
        .terminal-search__input {
            flex: 1 1 auto;
            min-width: 0;
            height: 28px;
            padding: 0 var(--oc-space-2);
            border: 1px solid var(--oc-line-faint);
            border-radius: var(--oc-radius-sm);
            background: var(--oc-ground-field);
            color: var(--oc-text-primary);
            font-family: inherit;
            font-size: 13px;
        }

        .terminal-search__input:focus {
            border-color: var(--oc-orange);
            outline: none;
        }

        .terminal-search__input::-webkit-search-cancel-button {
            -webkit-appearance: none;
            appearance: none;
        }

        .terminal-search__count {
            flex: 0 0 auto;
            min-width: 0;
            color: var(--oc-text-secondary);
            font-size: var(--oc-fs-label);
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
        }

        /* the prompts-only toggle */
        .terminal-search__tip {
            display: inline-flex;
            flex: 0 0 auto;
        }

        .terminal-search__tip > button:disabled {
            pointer-events: none;
        }

        .terminal-prompt-rail-host {
            position: absolute;
            top: 0;
            right: 0;
            bottom: 0;
            width: 24px;
            z-index: 31;
            pointer-events: none;
        }

        @media (max-width: 768px) {
            .terminal-search-panel {
                top: auto;
                bottom: 15px;
                left: 8px;
                right: auto;
                width: calc(100% - 16px);
            }
        }
  }
</style>
