
<script lang="ts">
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import { SUBMIT_KEYS } from '../../../../client/js/labels/skill-submit.js';
    import type { Translate } from '../sessions/types';
    import Button from '../base/Button.svelte';
    import KeyHelp from './KeyHelp.svelte';
    import { isReadonly } from './readonly';

    interface Props {
        refreshing: boolean;
        onRefresh: () => void;
        onPublish: () => void;
        onSignIn?: () => void;
        showPublish?: boolean;
        t: Translate;
    }

    const { refreshing, onRefresh, onPublish, onSignIn, showPublish = true, t }: Props = $props();
    const readonly = isReadonly();
</script>

{#if !readonly}
<Button data-warez-act size="sm" disabled={refreshing} onclick={onRefresh}>
    {refreshing ? t(SKILL_KEYS.catalogRefreshing) : t(SKILL_KEYS.catalogRefresh)}
</Button>
{#if showPublish}
    <Button data-warez-act size="sm" id="catalog-submit-open" onclick={onPublish}>
        {t(SUBMIT_KEYS.submitAction)}
    </Button>
{/if}
<KeyHelp {t} />
{#if onSignIn}
    <Button data-warez-act size="sm" data-catalog-signin-cta onclick={onSignIn}>
        {t('skills.hub.signin')}
    </Button>
{/if}
{/if}
