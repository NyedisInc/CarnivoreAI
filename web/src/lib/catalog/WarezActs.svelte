
<script lang="ts">
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import { SUBMIT_KEYS } from '../../../../client/js/labels/skill-submit.js';
    import type { Translate } from '../sessions/types';
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
<button type="button" class="modal-btn modal-btn-secondary warez-act" disabled={refreshing} onclick={onRefresh}>
    {refreshing ? t(SKILL_KEYS.catalogRefreshing) : t(SKILL_KEYS.catalogRefresh)}
</button>
{#if showPublish}
    <button type="button" class="modal-btn modal-btn-secondary warez-act" id="catalog-submit-open" onclick={onPublish}>
        {t(SUBMIT_KEYS.submitAction)}
    </button>
{/if}
<KeyHelp {t} />
{#if onSignIn}
    <button type="button" class="modal-btn modal-btn-secondary warez-act" data-catalog-signin-cta onclick={onSignIn}>
        {t('skills.hub.signin')}
    </button>
{/if}
{/if}
