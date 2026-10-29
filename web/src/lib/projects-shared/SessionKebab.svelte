
<script lang="ts">
    import { triggerHtml } from '../item-menu/row-context';
    import type { HistorySession } from './history-api';
    import type { SessionListItem } from '../sessions/types';
    import { sessionMenuContext } from './session-menu-context';

    interface Props {
        session: HistorySession;
        live?: SessionListItem | undefined;
        unread?: boolean;
    }

    const { session, live, unread = false }: Props = $props();

    const html = $derived.by((): string => {
        const context = sessionMenuContext(session, live, unread);
        return context ? triggerHtml(context) : '';
    });
</script>

<span class="ph-kebab-host">{@html html}</span>

<style>
    @layer components {
        .ph-kebab-host {
            display: flex;
            align-items: center;
            justify-content: flex-end;
            min-width: 24px;
        }

        .ph-kebab-host :global(.session-row-menu-trigger) {
            width: 24px;
            min-width: 24px;
            height: 24px;
            align-self: center;
            border-radius: var(--oc-radius-sm);
        }

        .ph-kebab-host :global(.session-row-menu-trigger:hover),
        .ph-kebab-host :global(.session-row-menu-trigger[aria-expanded='true']) {
            background: var(--oc-ground-hover);
        }

        @container ph (max-width: 767px) {
            .ph-kebab-host {
                min-width: 44px;
            }

            .ph-kebab-host :global(.session-row-menu-trigger) {
                width: 44px;
                min-width: 44px;
                height: 44px;
            }
        }
    }
</style>
