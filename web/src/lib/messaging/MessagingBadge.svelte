
<script lang="ts">
    import { t } from '../i18n/index.svelte';
    import { badgePlan } from './badge';

    interface Props {
        mark: unknown;
    }
    const { mark }: Props = $props();
    const plan = $derived(badgePlan(mark, t));
</script>

{#if plan}
    <span class="messaging-badge" data-messaging-badge={plan.tone} data-messaging-direction={plan.direction} data-messaging-held={plan.held > 0 ? plan.held : undefined} role="img" aria-label={plan.title} title={plan.title}>
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M2 3h12v8H7l-3 3v-3H2Z" />
            {#if plan.direction === 'in'}
                <path data-arrow="in" d="M10.5 7H5.5M7 5.5 5.5 7 7 8.5" />
            {:else if plan.direction === 'out'}
                <path data-arrow="out" d="M5.5 7h5M9 5.5 10.5 7 9 8.5" />
            {:else}
                <path data-arrow="in" d="M10.5 5.5H5.5M7 4.3 5.7 5.5 7 6.7" />
                <path data-arrow="out" d="M5.5 8.5h5M9 7.3l1.3 1.2L9 9.7" />
            {/if}
            {#if plan.held > 0}
                <circle data-held-dot cx="13" cy="3" r="2.6" fill="currentColor" stroke="none" />
            {/if}
        </svg>
    </span>
{/if}

<style>
    @layer components {
        .messaging-badge {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 16px;
            height: 16px;
            flex-shrink: 0;
            line-height: 0;
            color: var(--oc-text-muted);
        }

        .messaging-badge[data-messaging-badge='held'] {
            color: var(--oc-yellow);
        }
    }
</style>
