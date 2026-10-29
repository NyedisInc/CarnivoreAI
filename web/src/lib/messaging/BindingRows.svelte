
<script lang="ts">
    import Check from '../../opscenter/ui/Check.svelte';
    import type { Translate } from '../sessions/types';
    import { deleteBinding, patchBinding, type Binding, type Conversation, type Direction, type Fetcher } from './api';
    import { DIRECTIONS } from './directions';

    interface Props {
        t: Translate;
        bindings: Binding[];
        conversations: Conversation[];
        busy: boolean;
        act: (work: () => Promise<void>, done?: string) => Promise<boolean>;
        showSession?: boolean;
        fetcher?: Fetcher;
    }
    const { t, bindings, conversations, busy, act, showSession = true, fetcher }: Props = $props();

    const labelOf = (id: string): string => conversations.find((c) => c.id === id)?.label ?? id;
</script>

<div class="messaging-rows" data-messaging="bindings">
    {#each bindings as b (b.id)}
        <div class="messaging-row" data-messaging-binding={b.id}>
            {#if showSession}<span class="tm__srv-name">{b.session_name ?? b.session_uuid.slice(0, 8)}</span>{/if}
            <span class="tm__sub">{labelOf(b.conversation_id)}</span>
            <select class="oc-field" value={b.direction} disabled={busy} aria-label={t('messaging.ui.bind.direction')} data-messaging="direction"
                onchange={(e) => void act(async () => void (await patchBinding(b.id, { direction: e.currentTarget.value as Direction }, fetcher)))}>
                {#each DIRECTIONS as d (d)}<option value={d}>{t(`messaging.ui.direction.${d}`)}</option>{/each}
            </select>
            <Check label={t('messaging.ui.bind.default')} checked={b.default} disabled={busy} data-messaging="default"
                onToggle={(next) => void act(async () => void (await patchBinding(b.id, { default: next }, fetcher)))} />
            {#if b.held > 0}<span class="messaging-held" data-messaging="held">{t('messaging.ui.badge.held', { count: b.held })}</span>{/if}
            <button type="button" class="oc-btn oc-btn--ghost" disabled={busy} data-messaging="unbind"
                onclick={() => void act(async () => void (await deleteBinding(b.id, fetcher)))}>{t('messaging.ui.bind.unbind')}</button>
        </div>
    {/each}
    {#if bindings.length === 0}<p class="tm__sub" data-messaging="no-bindings">{t('messaging.ui.bind.none')}</p>{/if}
</div>
