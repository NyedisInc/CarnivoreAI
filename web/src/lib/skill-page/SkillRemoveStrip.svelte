
<script lang="ts">
    import type { SkillGroupRow, SkillLocationRow } from '../skills-page/skills-types';
    import type { Translate } from '../sessions/types';
    import { removeBlock } from './model';

    interface Props {
        group: SkillGroupRow;
        removals: Readonly<Record<string, { readonly busy: boolean; readonly error: string | null }>>;
        t: Translate;
        onRemove: (location: SkillLocationRow) => void;
        onClose: () => void;
        onOpenCatalog: () => void;
    }

    const { group, removals, t, onRemove, onClose, onOpenCatalog }: Props = $props();

    const locations = $derived(group.locations);
    const removable = $derived(locations.filter((l) => removeBlock(l) === null));
    const single = $derived(locations.length === 1 ? locations[0]! : null);
    let picked = $state<string | null>(null);

    const scopeWord = (loc: SkillLocationRow): string => t(`skills.loc.scope.${loc.scope}`);
    const harnessWord = (h: string): string => t(`skills.harness.${h}`);
</script>

{#snippet confirmRow(loc: SkillLocationRow, many: boolean)}
    {@const removal = removals[loc.location_id]}
    <div class="skp-rmstrip__q">
        <span class="skp-rm__q" role="alert">{many ? t('skp.rm.question_copy', { harness: harnessWord(loc.harness), name: group.name, scope: scopeWord(loc) }) : t('skills.loc.remove_question', { name: group.name, scope: scopeWord(loc) })}</span>
        <div class="skp-rm__row">
            <button type="button" class="modal-btn modal-btn-danger" data-act="confirm" disabled={removal?.busy === true} onclick={() => onRemove(loc)}>{t('skills.loc.remove_confirm')}</button>
            <button type="button" class="modal-btn modal-btn-secondary" data-act="keep" onclick={() => { if (many) picked = null; else onClose(); }}>{t('skills.loc.remove_cancel')}</button>
        </div>
        {#if removal?.error}<span class="skp-rm__ro" role="alert" data-skill-remove-error>{removal.error}</span>{/if}
    </div>
{/snippet}

<section class="skp-rmstrip" id="skp-rm" aria-label={t('skp.rm.aria', { name: group.name })} data-skill-remove-strip>
    {#if single && removeBlock(single) === 'read_only'}
        <span class="skp-rm__ro">{t('skp.rm.read_only')}</span>
        <button type="button" class="modal-btn modal-btn-secondary" data-act="close" onclick={onClose}>{t('skp.rm.close')}</button>
    {:else if single && removeBlock(single) === 'catalog'}
        <span class="skp-rm__ro">{t('skp.rm.catalog')}</span>
        <div class="skp-rm__row"><button type="button" class="modal-btn modal-btn-secondary" data-act="warez" onclick={onOpenCatalog}>{t('skp.rm.warez')}</button></div>
    {:else if single}
        {@render confirmRow(single, false)}
    {:else}
        <div class="skp-rmstrip__h">
            <span class="skp-rm__q">{removable.length > 0 ? t('skp.rm.which') : t('skp.rm.none')}</span>
            <button type="button" class="modal-btn modal-btn-secondary" data-act="close" onclick={onClose}>{t('skp.rm.close')}</button>
        </div>
        <ul class="skp-rmlist" aria-label={t('skp.rm.copies')}>
            {#each locations as loc (loc.location_id)}
                {@const block = removeBlock(loc)}
                <li data-loc={loc.location_id}>
                    <span class="skp-loc__h">{harnessWord(loc.harness)}</span>
                    <span class="skp-loc__path">{loc.path}</span>
                    {#if block === 'read_only'}<span class="skp-rm__ro">{t('skp.rm.read_only')}</span>
                    {:else if block === 'catalog'}<span class="skp-rm__ro">{t('skp.rm.catalog')}</span>
                    {:else if picked === loc.location_id}{@render confirmRow(loc, true)}
                    {:else}<button type="button" class="modal-btn modal-btn-secondary" data-act="remove-copy" onclick={() => (picked = loc.location_id)}>{t('skp.rm.this_copy')}</button>{/if}
                </li>
            {/each}
        </ul>
    {/if}
</section>
