
<script lang="ts">
    import Button from '../base/Button.svelte';
    import { layouts } from '../layouts-bridge/api.svelte';
    import * as groupStore from '../drawer/group-store';
    import type { Translate } from '../sessions/types';
    import { membershipsOf, type Belongs } from './memberships';

    interface Props {
        sessionUuid: string;
        t: Translate;
        tick: number;
    }
    const { sessionUuid, t, tick }: Props = $props();

    const m = $derived.by(() => {
        void tick;
        return membershipsOf(sessionUuid, layouts.data ?? [], groupStore.current().groups);
    });

    function openLayout(chip: Belongs): void {
        const page = (globalThis as { CloudeWeb?: { layoutPage?: { openLayout?: (uuid: string) => unknown } } }).CloudeWeb?.layoutPage;
        if (typeof page?.openLayout === 'function') void page.openLayout(chip.uuid);
        else globalThis.location.assign(`/layout/${encodeURIComponent(chip.uuid)}`);
    }

    function showGroup(chip: Belongs): void {
        const key = groupStore.bandKeyFor(chip.uuid);
        if (typeof document === 'undefined') return;
        const toggle = [...document.querySelectorAll<HTMLElement>('[data-group-toggle]')].find((el) => el.dataset.groupToggle === key);
        if (!toggle) return;
        if (toggle.getAttribute('aria-expanded') === 'false') toggle.click();
        toggle.scrollIntoView({ block: 'nearest' });
    }
</script>

<section class="sp-pn-sec" id="sp-pn-member">
    <h3 class="pl-label">{t('sessions.page.panel.belongs')}</h3>
    <dl class="sp-pn-dl">
        <dt>{t('sessions.page.panel.layouts')}</dt>
        <dd class="sp-pn-chips">
            {#each m.layouts as c (c.uuid)}
                <Button size="sm" data-chip="layout" aria-label={t('sessions.page.panel.open_layout', { name: c.name })} onclick={() => openLayout(c)}>{c.name}</Button>
            {:else}
                <span class="sp-pn-dim" data-none>{t('sessions.page.panel.none')}</span>
            {/each}
        </dd>
        <dt>{t('sessions.page.panel.groups')}</dt>
        <dd class="sp-pn-chips">
            {#each m.groups as c (c.uuid)}
                <Button size="sm" data-chip="group" aria-label={t('sessions.page.panel.show_group', { name: c.name })} onclick={() => showGroup(c)}>{c.name}</Button>
            {:else}
                <span class="sp-pn-dim" data-none>{t('sessions.page.panel.none')}</span>
            {/each}
        </dd>
    </dl>
</section>
