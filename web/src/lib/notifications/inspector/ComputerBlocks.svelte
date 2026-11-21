
<script lang="ts">
    import Check from '../../../opscenter/ui/Check.svelte';
    import type { Translate } from '../../sessions/types';
    import type { RoutesBody, Target } from './api';
    import { cornerAllowed, groupCol, hueClass } from './logic';

    interface Props { routes: RoutesBody; ids: readonly string[]; urgency: string; onRoute: (computer: string, target: Target, next: boolean) => void; t: Translate }
    const { routes, ids, urgency, onRoute, t }: Props = $props();
    const ROWS = ['app', 'desk', 'phone'] as const;
</script>

{#each routes.computers as c (c.install_id)}
    <div class="ins-panel ins-comp {hueClass(c.hue)}" data-comp={c.install_id} data-hue={c.hue}>
        <div class="ins-bar ins-comp__bar">
            <span class="ins-hue" aria-hidden="true"></span><h3>{c.label}</h3>
            <span class="ins-dim">{c.self ? t('notify.routing.computer.self') : ''}{c.online === null ? '' : `${c.self ? ', ' : ''}${t(c.online ? 'notify.routing.computer.online' : 'notify.routing.computer.offline')}`}</span>
        </div>
        {#if !c.syncs && !c.self}<p class="ins-warn" role="note" data-ins="sync-warning">{t('notify.routing.sync.off')}</p>{/if}
        {#each ROWS as tg (tg)}
            {@const col = groupCol(routes, ids, c.install_id, tg)}
            <div class="ins-tg" data-tg={tg} data-dis={col.state === 'none' ? '' : undefined}>
                <Check role="switch" label={t(`notify.routing.target.${tg}`)} hint={t(`notify.routing.target.${tg}.plain`, { computer: c.label })}
                    ariaLabel={`${c.label} ${t(`notify.routing.target.${tg}`)}`} checked={col.state === 'all'} mixed={col.state === 'some'} disabled={!col.writable}
                    data-ins="route" data-computer={c.install_id} data-target={tg} onToggle={() => onRoute(c.install_id, tg, col.state !== 'all')} />
                {#if !col.writable}<span class="ins-dim ins-tg__note">{t('notify.routing.cell.locked')}</span>
                {:else if col.unset}<span class="ins-dim ins-tg__note" data-ins="unset">{t('notify.routing.cell.unset')}</span>{/if}
                {#if tg === 'desk'}
                    {@const cn = groupCol(routes, ids, c.install_id, 'corner')}
                    <div class="ins-tg__sub" data-corner={c.install_id}>
                        <Check role="switch" label={t('notify.routing.corner')} ariaLabel={`${c.label} ${t('notify.routing.corner')}`} checked={cn.state === 'all'} mixed={cn.state === 'some'}
                            disabled={!cn.writable || !cornerAllowed(urgency)} data-ins="route" data-computer={c.install_id} data-target="corner" onToggle={() => onRoute(c.install_id, 'corner', cn.state !== 'all')} />
                        {#if !cornerAllowed(urgency)}<span class="ins-dim">{t('notify.routing.corner.passive')}</span>{/if}
                    </div>
                {/if}
            </div>
        {/each}
    </div>
{/each}
