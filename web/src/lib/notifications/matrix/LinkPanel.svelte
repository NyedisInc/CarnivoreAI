
<script lang="ts">
    import { onMount } from 'svelte';
    import { t as reactiveT } from '../../i18n/index.svelte';
    import type { Translate } from '../../sessions/types';
    import Check from '../../../opscenter/ui/Check.svelte';
    import '../../settings-page/panel-kit/panel-kit.css';
    import './matrix.css';
    import type { Fetcher } from './api';
    import { linkKindKey, linkReasonKey } from './logic';
    import { attach, matrix, setPaused } from './store.svelte';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    onMount(() => attach(fetcher));
    const link = $derived(matrix.settings.link);
</script>

<div class="tm mx-link" data-mx="link-panel">
    <div class="mx-link__row">
        <span class="mx-link__kind" data-mx="link-kind">{t(linkKindKey(link.kind))}</span>
        {#if link.base}<span class="mx-link__base" data-mx="link-base">{link.base}</span>{/if}
    </div>
    <p class="tm__sub" data-mx="link-reason">{t(linkReasonKey(link.reason))}</p>
    {#if matrix.problem}<p class="tm__problem" role="alert" data-mx="link-problem">{matrix.problem}</p>{/if}
    <Check label={t('settings.notify.pause.label')} hint={t('settings.notify.pause.hint')} role="switch"
        checked={matrix.settings.paused} data-mx="pause" onToggle={(next) => void setPaused(next)} />
</div>
