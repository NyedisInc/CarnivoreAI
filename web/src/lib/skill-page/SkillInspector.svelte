
<script lang="ts">
    import { CLAUDE_STATE_KEYS, targetFile, type ContextChoice } from '../skills-page/skills-model';
    import type { SkillGroupRow, SkillLocationRow } from '../skills-page/skills-types';
    import type { Translate } from '../sessions/types';
    import { canSwitchHarness, deciderOf, shapeOf } from './model';
    import StateShape from './StateShape.svelte';

    interface Props {
        group: SkillGroupRow;
        harnesses: readonly ('claude' | 'codex')[];
        context: ContextChoice;
        writing: readonly string[];
        writeError: string | null;
        t: Translate;
        onState: (harness: 'claude' | 'codex', choice: string) => void;
        art: { readonly busy: boolean; readonly message: string | null; readonly routed: boolean | null };
        onRegenerateArt: () => void;
    }

    const { group, harnesses, context, writing, writeError, t, onState, art, onRegenerateArt }: Props = $props();

    const CHOICES = { claude: ['on', 'name-only', 'user-invocable-only', 'off'], codex: ['on', 'off'] } as const;

    let showAll = $state(false);

    const states = $derived(harnesses.map((h) => ({ harness: h, state: deciderOf(group, h)?.state ?? 'off' })));
    const stateWord = (state: string): string => t(CLAUDE_STATE_KEYS[state] ?? 'skills.state.off');
    const harnessWord = (h: string): string => t(`skills.harness.${h}`);
    const sentence = $derived.by(() => {
        if (states.length === 0) return { shape: 'off' as const, text: t('skp.live.gone'), on: false };
        const names = harnesses.map(harnessWord);
        const joined = names.length > 1 ? `${names.slice(0, -1).join(', ')} ${t('skp.live.and')} ${names[names.length - 1]}` : (names[0] ?? '');
        const first = states[0]!;
        if (states.every((s) => s.state === first.state)) {
            return { shape: shapeOf(first.state), text: t('skp.live.same', { state: stateWord(first.state), harnesses: joined }), on: first.state !== 'off' };
        }
        return { shape: 'name-only' as const, text: states.map((s) => t('skp.live.one', { state: stateWord(s.state), harness: harnessWord(s.harness) })).join(', '), on: true };
    });

    const shown = $derived(showAll ? group.locations : group.locations.slice(0, 1));
    const restHarnesses = $derived([...new Set(group.locations.slice(1).map((l) => l.harness))].join(', '));

    function writesNote(harness: 'claude' | 'codex'): string {
        const file = targetFile(context, harness);
        if (harness === 'codex') return t(file === 'project' ? 'skills.detail.writes_codex_project' : 'skills.detail.writes_codex_user');
        return t(file === 'local' ? 'skills.detail.writes_local' : 'skills.detail.writes_user');
    }

    function effectOf(state: string): string {
        if (state === 'name-only') return t('skp.eff.name_only');
        if (state === 'user-invocable-only') return t('skp.eff.on_demand', { name: group.name });
        return t(state === 'off' ? 'skp.eff.off' : 'skp.eff.on');
    }

    function whyNot(harness: 'claude' | 'codex'): string {
        const loc = deciderOf(group, harness);
        if (harness === 'codex' && loc && loc.toggle.kind !== 'none' && !loc.read_only) return t('skills.detail.codex_global_only');
        return t('skills.detail.not_switchable', { reason: loc?.toggle.reason ?? loc?.scope ?? '' });
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

    function metaOf(loc: SkillLocationRow): string {
        const parts = [`${t(`skills.loc.scope.${loc.scope}`)}, ${originOf(loc)}`];
        if (loc.is_symlink && loc.link_target) parts.push(`${t('skills.loc.link')} ${loc.link_target}`);
        return parts.join('; ');
    }

    function pieces(path: string): string[] {
        const parts = path.split('/');
        return parts.map((part, i) => (i < parts.length - 1 ? `${part}/` : part));
    }
</script>

{#snippet broken(path: string)}{#each pieces(path) as piece, i (i)}{piece}<wbr />{/each}{/snippet}

<aside class="skp-insp" aria-label={t('skp.insp.aria', { name: group.name })} data-skill-inspector>
    <div class="skp-insp__main">
        <div class="skp-live" data-on={String(sentence.on)} data-skill-live><StateShape name={sentence.shape} size={14} /><span>{sentence.text}</span></div>

        <section class="skp-sec skp-state" aria-label={t('skills.detail.state')}>
            <div class="skp-tlabel">{t('skills.detail.state')}</div>
            {#if harnesses.length === 0}
                <p class="skp-gone">{'-'} {t('skp.insp.no_harness')}</p>
            {:else}
                <div class="skp-sc-all">
                    {#each harnesses as harness (harness)}
                        {@const loc = deciderOf(group, harness)}
                        {@const can = canSwitchHarness(group, harness, context)}
                        <div class="skp-sc" data-harness={harness}>
                            <div class="skp-sc__row">
                                <span class="skp-sc__who">{harnessWord(harness)}</span>
                                <div class="skp-sc__chips" role="group" aria-label={t('skills.detail.state_label', { harness: harnessWord(harness), name: group.name })}>
                                    {#each CHOICES[harness] as choice (choice)}
                                        <button
                                            type="button"
                                            class="skp-sc__chip"
                                            data-v={choice}
                                            data-state-choice={choice}
                                            aria-pressed={loc?.state === choice}
                                            disabled={!can || writing.includes(harness)}
                                            onclick={() => { if (loc?.state !== choice) onState(harness, choice); }}
                                        ><StateShape name={shapeOf(choice)} />{stateWord(choice)}</button>
                                    {/each}
                                </div>
                            </div>
                            <div class="skp-eff" data-skill-eff>{effectOf(deciderOf(group, harness)?.state ?? 'off')}</div>
                            {#if !can}<div class="skp-sc__write" data-skill-locked>{whyNot(harness)}</div>{/if}
                            {#if harness === 'codex'}<div class="skp-sc__write" data-skill-codex-note>{t('skills.detail.codex_note')}</div>{/if}
                        </div>
                    {/each}
                </div>
                {#if writeError}<p class="skp-sc__err" role="alert" data-skill-write-error>{writeError}</p>{/if}
            {/if}
        </section>

        <section class="skp-sec skp-where" aria-label={t('skp.insp.where')}>
            <div class="skp-tlabel">{t('skp.insp.where')}</div>
            {#if group.locations.length === 0}
                <p class="skp-gone">{'-'} {t('skp.insp.no_folder')}</p>
            {:else}
                {#each shown as loc (loc.location_id)}
                    <div class="skp-loc" data-loc={loc.location_id}>
                        <span class="skp-loc__h">{harnessWord(loc.harness)}</span>
                        <span class="skp-loc__path">{@render broken(loc.path)}</span>
                        <span class="skp-loc__meta">{@render broken(metaOf(loc))}</span>
                    </div>
                {/each}
                {#if group.locations.length > 1}
                    {@const rest = group.locations.length - 1}
                    <button type="button" class="skp-more" data-act="where-more" aria-expanded={showAll} onclick={() => (showAll = !showAll)}>
                        {showAll ? t('skp.insp.fewer') : t(rest > 1 ? 'skp.insp.more_many' : 'skp.insp.more_one', { count: rest, harnesses: restHarnesses })}
                    </button>
                {/if}
            {/if}
        </section>

        {#if group.locations.length > 0}
            <section class="skp-sec skp-art" aria-label={t('skp.art.label')}>
                <div class="skp-tlabel">{t('skp.art.label')}</div>
                <div class="skp-rm__row">
                    <button type="button" class="modal-btn modal-btn-secondary" data-act="regenerate-art" disabled={art.busy || art.routed === false} onclick={onRegenerateArt}>{t('skp.art.regenerate')}</button>
                </div>
                {#if art.routed === false}<p class="skp-note" data-skill-art-note>{t('skp.art.no_route')}</p>
                {:else if art.message}<p class="skp-note" role="status" data-skill-art-note>{art.message}</p>{/if}
                {#each harnesses as harness (harness)}<p class="skp-note">{harnessWord(harness)}: {writesNote(harness)}</p>{/each}
            </section>
        {/if}
    </div>
    {#if harnesses.length > 0 && group.locations.length === 0}
        <div class="skp-insp__quiet">
            <section class="skp-sec skp-writes" aria-label={t('skp.insp.writes')}>
                {#each harnesses as harness (harness)}<p class="skp-note">{harnessWord(harness)}: {writesNote(harness)}</p>{/each}
            </section>
        </div>
    {/if}
</aside>
