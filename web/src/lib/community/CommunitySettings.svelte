
<script lang="ts">
    import Check from '../../opscenter/ui/Check.svelte';
    import type { Translate } from '../sessions/types';
    import { browserCommunityHost, type CommunityHost } from './community';

    interface Props {
        t: Translate;
        host?: CommunityHost;
    }

    const { t, host = browserCommunityHost() }: Props = $props();

    let working = $state(false);
    let on = $state<boolean | null>(null);
    let failed = $state(false);

    $effect(() => {
        host.readNotifyReplies().then(
            (value) => (on = value),
            () => (on = null),
        );
    });

    async function choose(next: boolean): Promise<void> {
        working = true;
        failed = false;
        try {
            const answer = await host.setNotifyReplies(next);
            on = typeof answer.notify_replies === 'boolean' ? answer.notify_replies : next;
        } catch {
            failed = true;
        } finally {
            working = false;
        }
    }
</script>

<div class="cset" role="group" aria-label={t('community.settings.heading')}>
    <span class="cset__label">{t('community.settings.heading')}</span>
    <Check
        label={t('community.settings.mail')}
        checked={on === true}
        disabled={on === null || working}
        onToggle={(next) => void choose(next)}
        data-community-replies=""
    />
    {#if failed}
        <p class="cset__note cset__note--out" role="status">{t('community.settings.failed')}</p>
    {/if}
</div>

<style>
  @layer components {
    .cset { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; }
    .cset__label {
        color: var(--cat-muted);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .cset__note { margin: 0; color: var(--cat-muted); font-size: 11px; line-height: 1.45; }
    .cset__note--out {
        padding: 6px 8px;
        border-left: 2px solid var(--cat-attention);
        background: var(--cat-raised);
        color: var(--cat-text);
    }
  }
</style>
