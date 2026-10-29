
<script lang="ts">
    import KindMark from '../catalog/KindMark.svelte';
    import { folderPhrase } from './kinds';
    import Panel from './Panel.svelte';
    import type { PageProps } from './props';
    import { KIND_TABS, KIND_WORD } from './rules-model';
    import './rules.css';

    const { t }: PageProps = $props();
</script>

<div class="d-rules" data-pp="EmptyPage">
    <h2 class="d-name">{t('publish.page.empty.title')}</h2>
    <p class="d-lead d-lead--first">{t('skill.publish.lead')}</p>
    <Panel label={t('publish.page.empty.where')}>
        <dl>
            {#each KIND_TABS as tab (tab)}
                <dt><KindMark kind={KIND_WORD[tab]} size="md" bare {t} />{t(`skill.publish.kind.${KIND_WORD[tab]}`)}</dt>
                <dd>{t(folderPhrase(tab))}</dd>
            {/each}
        </dl>
    </Panel>
    <Panel label={t('publish.page.empty.path')}>
        <ol>
            <li>{t('publish.page.empty.path_check')}</li>
            <li>{t('publish.page.empty.path_image')}</li>
            <li>{t('publish.page.empty.path_send')}</li>
            <li>{t('publish.page.empty.path_review')}</li>
        </ol>
    </Panel>
</div>
