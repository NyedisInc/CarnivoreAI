
<script lang="ts">
    import ProjectChip from './ProjectChip.svelte';
    import type { Snippet } from 'svelte';
    import FoldChevron from '../../opscenter/ui/FoldChevron.svelte';
    import Button from '../base/Button.svelte';
    import Tag from '../base/Tag.svelte';
    import { providerMark } from '../sessions/agent-marks';
    import type { Translate } from '../sessions/types';
    import { projectColorVar } from '../project-colors/palette';
    import { projectColorOf } from '../project-colors/store.svelte';
    import type { LensGroup } from './lenses';
    import { pageRowMenu } from '../item-menu/page-row';
    import { menuNodes } from '../projects-shared/menu-nodes';
    import { SET_COLOR, companyActions } from '../projects-shared/ledger-model';
    import { agentOffered } from '../projects-shared/agent-offer';
    import { companies, type Company } from '../companies';
    import { packTag } from '../projects-shared/pack-model';
    import { projectPanels } from '../../plugins/sdk/project-panels';
    import { entryNodes } from '../item-menu/entries';
    import { projectMenuEntries } from '../item-menu/menus/project-entries';
    import { ITEM_MENU_ENV } from '../item-menu/open.svelte';
    import { showPath } from '../sidebar-shell/show-path';
    import { sleepProject } from '../sidebar-shell/heading-project-actions';

    interface Props {
        group: LensGroup;
        folded: boolean;
        t: Translate;
        onFold: (key: string) => void;
        inactive?: boolean;
        onProjectAction?: (id: string, group: LensGroup) => void;
        busy?: boolean;
        leaf?: boolean;
        automatedOnly?: boolean;
        company?: Company | null;
        onCompanyAction?: (id: string, company: Company) => void;
        inCompany?: boolean;
        children?: Snippet;
    }
    const { group, folded, t, onFold, inactive = false, onProjectAction, busy = false, leaf = false, automatedOnly = false, company = null, onCompanyAction, inCompany = false, children }: Props = $props();

    const remote = $derived(group.rows.some((r) => !!r.computer));
    const project = $derived(onProjectAction && !remote ? group.project : null);
    const companyMenu = $derived(company && onCompanyAction ? company : null);
    const companyItems = $derived(companyMenu ? companyActions(Boolean(companyMenu.has_image)) : []);
    const hasMenu = $derived(Boolean(project || companyMenu));

    const archived = $derived(Boolean(group.project?.archived_at));
    const pack = $derived(packTag(group.project?.storage, t));
    const movedTo = $derived(group.project?.pack_state === 'moved_away' ? (group.project.moved_to_label ?? '') : null);

    function pick(id: string): void {
        if (companyMenu) onCompanyAction?.(id, companyMenu);
    }

    function projectVerb(id: string): void {
        if (id === 'show-path') void showPath(project?.root ?? '', group.label);
        else if (id === 'sleep') void sleepProject(group.key);
        else onProjectAction?.(id, group);
    }

    function projectNodes() {
        if (!project) return [];
        const entries = projectMenuEntries({
            project,
            companies: companies.list,
            agentOffered: agentOffered(project),
            panels: projectPanels(),
            color: project.id != null ? { value: projectColorOf(project.id) ?? '', onPick: (key) => onProjectAction?.(`${SET_COLOR}${key}`, group) } : null,
            close: ITEM_MENU_ENV.close,
            glyph: ITEM_MENU_ENV.glyph,
            run: projectVerb,
        });
        return entryNodes(entries, ITEM_MENU_ENV.glyph, ITEM_MENU_ENV.close);
    }

    function menu() {
        if (!hasMenu || busy) return null;
        const label = companyMenu ? t('projects.page.company.menu', { name: group.label }) : t('projects.page.menu.project', { name: group.label });
        return { type: 'pagerow', ctx: { label, nodes: companyMenu ? menuNodes(companyItems, t, pick) : projectNodes() } } as const;
    }

    const block = $derived(group.project && projectColorOf(group.project.id ?? null) ? projectColorVar(projectColorOf(group.project.id ?? null)) : undefined);
    const mark = $derived(group.provider ? providerMark(group.provider) : null);
</script>

<section class="sp-sec" data-key={group.key} data-folded={folded ? '' : undefined} data-leaf={leaf ? '' : undefined} data-company={company ? '' : undefined} data-in-company={inCompany ? '' : undefined} data-inactive={inactive ? '' : undefined} data-block={block ? '' : undefined} style:--sp-block={block}>
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="sp-sec-head" {...pageRowMenu(menu)}>
        <Button variant="row" aria-expanded={leaf ? undefined : !folded} aria-disabled={leaf ? 'true' : undefined} aria-label={t('sessions.page.group.fold', { name: group.label })} data-fold={group.key} onclick={() => !leaf && onFold(group.key)}>
            <FoldChevron />
            {#if group.project}
                <ProjectChip name={group.label} projectId={group.project.id ?? null} />
            {:else if mark}
                <span class="sp-pico" aria-hidden="true">{@html mark.svg}</span>
            {/if}
            <span class="sp-sh-l">{group.label}</span>
            {#if archived}<Tag data-tag="archived">{t('projects.page.tag.archived')}</Tag>{/if}
            {#if pack}<Tag tone={pack.warn ? 'danger' : 'neutral'} data-tag="pack" title={pack.title || undefined}>{pack.text}</Tag>{/if}
            {#if movedTo !== null}<Tag data-tag="moved">{movedTo ? t('projects.page.tag.moved', { machine: movedTo }) : t('projects.page.tag.moved.unnamed')}</Tag>{/if}
            {#if automatedOnly}<Tag data-tag="automated">{t('projects.page.tag.automated')}</Tag>{/if}
            <span class="sp-sh-m">{group.bits.join(' · ')}</span>
            <span class="sp-sh-t">{group.measure}</span>
        </Button>
        {#if project && movedTo !== null}
            <Button size="sm" data-move-back disabled={busy} onclick={() => projectVerb('migrate-back')}>{t('projects.page.tag.move_back')}</Button>
        {/if}
    </div>
    {#if !folded && children}{@render children()}{/if}
</section>
