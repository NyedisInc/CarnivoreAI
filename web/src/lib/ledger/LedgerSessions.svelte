
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Card from '../base/Card.svelte';
    import SessionFace from '../sessions/SessionFace.svelte';
    import type { Translate } from '../sessions/types';
    import { sessionTitle, type ProviderSession } from './ledger-sessions';

    interface Props {
        rows: readonly ProviderSession[];
        t: Translate;
        onOpen: (row: ProviderSession) => void;
        heading?: string;
        /* nothing at all */
        hideEmpty?: boolean;
    }

    const { rows, t, onOpen, heading, hideEmpty = false }: Props = $props();
</script>

{#snippet list()}
    {#if rows.length === 0}
        <p class="ledger-sessions__none">{t('ledger.sessions.none')}</p>
    {:else}
        <ul class="ledger-sessions__list">
            {#each rows as row (row.session.id)}
                <li>
                    <Button
                        variant="row"
                        data-ledger="session-row"
                        data-session-id={row.session.id}
                        aria-label={t('ledger.sessions.open', { name: sessionTitle(row) })}
                        onclick={() => onOpen(row)}
                    >
                        <SessionFace {row} bare name={sessionTitle(row)} nameClass="ledger-sessions__name" />
                    </Button>
                </li>
            {/each}
        </ul>
    {/if}
{/snippet}

{#if rows.length > 0 || !hideEmpty}
    {#if heading}
        <Card title={heading} headingLevel={2} data-ledger="sessions">
            {#snippet children()}{@render list()}{/snippet}
        </Card>
    {:else}
        <div class="ledger-sessions" data-ledger="sessions">
            <p class="oc-label ledger-sessions__label">{t('ledger.sessions.label')}</p>
            {@render list()}
        </div>
    {/if}
{/if}

<style>
    @layer components {
        .ledger-sessions {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-1);
            min-width: 0;
        }

        .ledger-sessions__label {
            margin: 0;
        }

        .ledger-sessions__none {
            margin: 0;
            color: var(--oc-text-muted);
            font-size: var(--oc-fs-hint);
        }

        .ledger-sessions__list {
            display: flex;
            flex-direction: column;
            margin: 0;
            padding: 0;
            list-style: none;
        }

        .ledger-sessions__list li + li {
            box-shadow: inset 0 var(--oc-border) 0 0 var(--oc-line-hairline);
        }

        .ledger-sessions__list :global([data-btn='row']) {
            justify-content: flex-start;
            width: 100%;
            min-width: 0;
        }

        .ledger-sessions__list :global(.ledger-sessions__name) {
            min-width: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
    }
</style>
