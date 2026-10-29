
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import { MANAGER_KEYS } from '../manager-frame/manager-model';
    import {
        CLAUDE_STATE_KEYS,
        switchable,
        targetFile,
        type ContextChoice,
        type SkillItem,
    } from './skills-model';
    import ContentsBlock from '../catalog/ContentsBlock.svelte';
    import UsageFacts from '../catalog/UsageFacts.svelte';
    import type { InstalledItem } from '../catalog/types';
    import SkillHealth from './SkillHealth.svelte';
    import SkillProvenance from './SkillProvenance.svelte';
    import type { Tripwire } from './skill-state';
    import { refusalOf, skillHost, type Fetcher, type LocalSkillMd } from './skills-api';
    import type { SkillGroupRow, SkillLocationRow } from './skills-types';
    import './skills-page.css';

    interface RemoveState {
        readonly busy: boolean;
        readonly error: string | null;
    }

    interface Props {
        item: SkillItem;
        group: SkillGroupRow;
        context: ContextChoice;
        t: Translate;
        writing: readonly string[];
        writeError: string | null;
        removals: Readonly<Record<string, RemoveState>>;
        onState: (harness: 'claude' | 'codex', choice: string) => void;
        onRemove: (location: SkillLocationRow) => void;
        onOpenCatalog: () => void;
        readMd?: (location: SkillLocationRow) => Promise<LocalSkillMd>;
        ledger?: readonly InstalledItem[];
        tripwire?: Tripwire;
        fetcher: Fetcher;
        onChanged?: () => void;
    }

    const { item, group, context, t, writing, writeError, removals, onState, onRemove, onOpenCatalog, readMd, ledger = [], tripwire, fetcher, onChanged = () => {} }: Props =
        $props();

    const CLAUDE_CHOICES = ['on', 'name-only', 'user-invocable-only', 'off'] as const;
    const CODEX_CHOICES = ['on', 'off'] as const;

    let asking = $state<string | null>(null);

    function decider(harness: 'claude' | 'codex'): SkillLocationRow | undefined {
        const mine = group.locations.filter((l) => l.harness === harness);
        return mine.find((l) => l.shadowed_by === null) ?? mine[0];
    }

    function canSwitch(harness: 'claude' | 'codex'): boolean {
        return group.locations.some((l) => l.harness === harness && switchable(l, context));
    }

    function whyNot(harness: 'claude' | 'codex'): string {
        const loc = decider(harness);
        if (harness === 'codex' && loc && loc.toggle.kind !== 'none' && !loc.read_only) {
            return t('skills.detail.codex_global_only');
        }
        return t('skills.detail.not_switchable', { reason: loc?.toggle.reason ?? loc?.scope ?? '' });
    }

    function writesNote(harness: 'claude' | 'codex'): string {
        const file = targetFile(context, harness);
        if (harness === 'codex') {
            return t(file === 'project' ? 'skills.detail.writes_codex_project' : 'skills.detail.writes_codex_user');
        }
        return t(file === 'local' ? 'skills.detail.writes_local' : 'skills.detail.writes_user');
    }

    function originOf(loc: SkillLocationRow): string {
        if (loc.scope === 'plugin') return t('skills.loc.origin_plugin', { plugin: loc.plugin ?? '' });
        if (loc.scope === 'system') return t('skills.loc.origin_system');
        const managed = loc.managed;
        if (!managed) return t('skills.loc.origin_foreign');
        const params = { item: managed.item_id ?? '', version: managed.version ?? '' };
        if (managed.source === 'sidecar') return t('skills.loc.origin_sidecar', params);
        return t(managed.update_available ? 'skills.loc.origin_catalog_update' : 'skills.loc.origin_catalog', params);
    }

    function scopeOfId(id: string | null): string {
        const winner = group.locations.find((l) => l.location_id === id);
        return winner ? t(`skills.loc.scope.${winner.scope}`) : '';
    }

    let mds = $state<Record<string, { busy: boolean; open: boolean; md: LocalSkillMd | null; error: string | null }>>({});

    async function toggleMd(loc: SkillLocationRow): Promise<void> {
        const id = loc.location_id;
        const held = mds[id];
        if (held?.md) {
            mds = { ...mds, [id]: { ...held, open: !held.open } };
            return;
        }
        if (!readMd || held?.busy) return;
        mds = { ...mds, [id]: { busy: true, open: true, md: null, error: null } };
        try {
            const md = await readMd(loc);
            mds = { ...mds, [id]: { busy: false, open: true, md, error: null } };
        } catch (error) {
            mds = { ...mds, [id]: { busy: false, open: false, md: null, error: refusalOf(error, t('skills.page.error')) } };
        }
    }

    function confirm(loc: SkillLocationRow): void {
        asking = null;
        onRemove(loc);
    }

    const description = $derived(group.locations[0]?.description ?? '');
    const host = $derived(skillHost(fetcher));
    const itemId = $derived(group.locations.find((l) => l.managed?.item_id)?.managed?.item_id ?? null);
</script>

<div class="sk-detail cat" data-skill-detail={item.id}>
    <section class="sk-section" aria-label={t('skills.detail.state')}>
        <h3 class="oc-label">{t('skills.detail.state')}</h3>
        {#each item.harnesses as harness (harness)}
            {@const loc = decider(harness)}
            <div class="sk-harness" data-harness={harness}>
                <span class="sk-harness__name">{t(`skills.harness.${harness}`)}</span>
                {#if canSwitch(harness)}
                    <div
                        class="sk-states"
                        role="group"
                        aria-label={t('skills.detail.state_label', { harness: t(`skills.harness.${harness}`), name: item.name })}
                    >
                        {#each harness === 'claude' ? CLAUDE_CHOICES : CODEX_CHOICES as choice (choice)}
                            <button
                                type="button"
                                class="oc-chip"
                                aria-pressed={loc?.state === choice}
                                data-state-choice={choice}
                                disabled={writing.includes(harness)}
                                onclick={() => onState(harness, choice)}
                                >{t(CLAUDE_STATE_KEYS[choice] ?? choice)}</button
                            >
                        {/each}
                    </div>
                    <p class="sk-note" data-skill-writes>{writesNote(harness)}</p>
                    {#if harness === 'codex'}<p class="sk-note" data-skill-codex-note>{t('skills.detail.codex_note')}</p>{/if}
                {:else}
                    <p class="sk-note" data-skill-locked>
                        {t(CLAUDE_STATE_KEYS[loc?.state ?? 'on'] ?? 'skills.state.on')}. {whyNot(harness)}
                    </p>
                {/if}
            </div>
        {/each}
        {#if writeError}<p class="oc-notice oc-notice--error" role="alert" data-mgr-error>{writeError}</p>{/if}
    </section>

    <section class="sk-section" aria-label={t('skills.detail.locations')}>
        <h3 class="oc-label">{t('skills.detail.locations')}</h3>
        {#each group.locations as loc (loc.location_id)}
            {@const removal = removals[loc.location_id]}
            <article class="sk-loc" data-location={loc.location_id}>
                <dl class="mgr-facts">
                    <dt>{t('skills.detail.state')}</dt>
                    <dd>{t(`skills.harness.${loc.harness}`)}, {t(`skills.loc.scope.${loc.scope}`)}</dd>
                    <dt>{t('skills.loc.folder')}</dt>
                    <dd>{loc.path}</dd>
                    {#if loc.is_symlink && loc.link_target}
                        <dt>{t('skills.loc.link')}</dt>
                        <dd>{loc.link_target}</dd>
                    {/if}
                    <dt>{t('skills.loc.origin')}</dt>
                    <dd data-skill-origin>{originOf(loc)}</dd>
                    {#if loc.shadowed_by}
                        <dt>{t('skills.mark.shadowed')}</dt>
                        <dd>{t('skills.loc.shadowed_by', { scope: scopeOfId(loc.shadowed_by) })}</dd>
                    {:else if loc.shadows.length > 0}
                        <dt>{t('skills.mark.shadowed')}</dt>
                        <dd>{t('skills.loc.wins')}</dd>
                    {/if}
                </dl>
                {#if loc.behind_rules}
                    <div class="sk-note" data-skill-behind-rules>
                        <p>{t('skills.loc.behind_rules', { written: loc.behind_rules.written_for, current: loc.behind_rules.current })}</p>
                        <ul>
                            {#each loc.behind_rules.changes as change (change.rev)}
                                <li>{t('skills.loc.behind_change', { rev: change.rev, summary: change.summary })}</li>
                            {/each}
                        </ul>
                    </div>
                {/if}
                {#if loc.read_only}
                    <p class="sk-note" data-skill-readonly>{t('skills.loc.read_only')}</p>
                {:else if loc.managed?.source === 'ledger'}
                    <div class="mgr-actions__row">
                        <p class="sk-note" data-skill-catalog-managed>{t('skills.loc.catalog_managed')}</p>
                        <button type="button" class="oc-btn" data-skill-open-catalog onclick={onOpenCatalog}
                            >{t('skills.loc.open_catalog')}</button
                        >
                    </div>
                {:else if asking === loc.location_id}
                    <p class="oc-notice oc-notice--error" role="alert" data-mgr-question>
                        {t('skills.loc.remove_question', { name: loc.name, scope: t(`skills.loc.scope.${loc.scope}`) })}
                    </p>
                    <div class="mgr-actions__row">
                        <button type="button" class="oc-btn oc-btn--danger" data-skill-remove-confirm onclick={() => confirm(loc)}
                            >{t('skills.loc.remove_confirm')}</button
                        >
                        <button type="button" class="oc-btn" onclick={() => (asking = null)}
                            >{t('skills.loc.remove_cancel')}</button
                        >
                    </div>
                {:else}
                    <div class="mgr-actions__row">
                        <button
                            type="button"
                            class="oc-btn oc-btn--danger"
                            data-skill-remove
                            disabled={removal?.busy === true}
                            onclick={() => (asking = loc.location_id)}
                            >{removal?.busy ? t(MANAGER_KEYS.working) : t('skills.loc.remove')}</button
                        >
                    </div>
                {/if}
                {#if removal?.error}<p class="oc-notice oc-notice--error" role="alert" data-mgr-error>{removal.error}</p>{/if}
            </article>
        {/each}
    </section>

    <section class="sk-section" aria-label={t('skills.section.usage')} data-skill-section="usage">
        <h3 class="oc-label">{t('skills.section.usage')}</h3>
        <UsageFacts skill={item.name} {host} {t} windows />
        <dl class="mgr-facts">
            <dt>{t('skills.detail.cost')}</dt>
            <dd>{t('skills.page.tokens', { count: item.tokens })}</dd>
        </dl>
    </section>

    <section class="sk-section" aria-label={t('skills.section.health')} data-skill-section="health">
        <h3 class="oc-label">{t('skills.section.health')}</h3>
        <SkillHealth name={item.name} {ledger} {tripwire} {host} {fetcher} {t} {onChanged} {onOpenCatalog} />
    </section>

    <section class="sk-section" aria-label={t('skills.section.provenance')} data-skill-section="provenance">
        <h3 class="oc-label">{t('skills.section.provenance')}</h3>
        <SkillProvenance {ledger} {itemId} {fetcher} {t} />
    </section>

    <section class="sk-section" aria-label={t('skills.section.contents')} data-skill-section="contents">
        <h3 class="oc-label">{t('skills.section.contents')}</h3>
        <p class="sk-text" data-skill-description>{description || t('skills.detail.no_description')}</p>
        {#each group.locations as loc (loc.location_id)}
            {#if readMd}
                {@const md = mds[loc.location_id]}
                <div class="mgr-actions__row">
                    <span class="sk-note">{t(`skills.harness.${loc.harness}`)}, {t(`skills.loc.scope.${loc.scope}`)}</span>
                    <button type="button" class="oc-btn" data-skill-md-toggle disabled={md?.busy === true} onclick={() => void toggleMd(loc)}
                        >{md?.busy ? t('skills.detail.md_loading') : md?.open ? t('skills.detail.hide_md') : t('skills.detail.view_md')}</button
                    >
                </div>
                {#if md?.open && md.md}
                    <pre class="sk-md" data-skill-md>{md.md.body}</pre>
                    {#if md.md.body_truncated}<p class="sk-note">{t('skills.detail.md_truncated', { size: md.md.size })}</p>{/if}
                {/if}
                {#if md?.error}<p class="oc-notice oc-notice--error" role="alert" data-mgr-error data-skill-md-error>{md.error}</p>{/if}
            {/if}
        {/each}
        <ContentsBlock {itemId} {host} {t} />
    </section>
</div>
