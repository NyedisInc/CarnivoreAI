
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { fileToBase64 } from '../catalog/publish';
    import { heldKey, tabKey } from './keys';
    import { dateText } from './format';
    import { heroColors, heroSeed, heroSvg } from './hero-art';
    import { canvasEncoder, rasterLadder } from './hero-raster';
    import ImageStep from './ImageStep.svelte';
    import { buildRecords } from './list-model';
    import { sentRows } from './item-model';
    import { leadText } from './next-step-model';
    import type { Step } from './next-step-model';
    import { kindWord, tabOf } from './kinds';
    import type { PageProps } from './props';
    import RegisterBlock from './RegisterBlock.svelte';
    import Stepper from './Stepper.svelte';
    import {
        defaultVersion, heldCall, heldParams, heldReason, heldReasons, needsRecheck, refusalKey, runSend, VERSION_RE, type HeldContext,
    } from './wizard-model';
    import { draftsOf } from './wizard-state.svelte';
    import './wizard.css';

    interface Props extends PageProps { step?: Step | null }
    const { store, actions, t, step = null }: Props = $props();
    const drafts = $derived(draftsOf(store));

    const location = $derived(store.sel ?? '');
    const record = $derived(
        buildRecords({
            mine: store.mine,
            folders: store.folders,
            sendsOf: (loc) => store.facts[loc]?.sends.map((s) => s.submission_id) ?? [],
            checkOf: (loc) => {
                const c = store.checkOf(loc);
                return c ? { ok: c.ok, at: c.at } : null;
            },
        }).find((r) => r.location === location) ?? null,
    );
    const draft = $derived(drafts.of(location));
    const entry = $derived(store.checks[location] ?? null);
    const preview = $derived(entry?.preview ?? null);
    const checkedOk = $derived(entry !== null && preview !== null && entry.ok);
    const sentVersions = $derived((record?.subs ?? []).map((s) => s.version));
    const version = $derived(draft.version ?? defaultVersion(store.facts[location]?.declared_version ?? '', record ? sentRows(store, record).map((r) => r.version) : sentVersions));
    const page = $derived((checkedOk ? Math.min(2, Math.max(0, store.wiz)) : 0) as 0 | 1 | 2);
    const kind = $derived(record?.kind ?? 'skill');
    const ownImage = $derived(draft.hero.mode === 'own' && draft.hero.file !== null);

    const held = $derived.by((): HeldContext => ({
        signedIn: store.signedIn,
        registered: store.account ? store.account.registered : null,
        kind,
        rules: store.rules,
        limits: store.limits,
        checked: entry && preview ? { version: entry.version, canSend: entry.ok } : null,
        version,
        sentVersions,
        wantsImage: true,
        now: Date.now(),
    }));
    const reason = $derived(heldReason(held));
    const notes = $derived(heldReasons(held).filter((h) => !h.blocks));
    const params = $derived(heldParams(store.limits, t(kindWord(kind)), dateText(store.limits?.cooldown_until, t), t(tabKey(tabOf(kind) ?? 'skills'))));
    const say = (key: string): string => t(...heldCall(key, params));
    const heldLine = $derived(reason ? say(heldKey(reason)) : '');
    const failLine = $derived.by(() => {
        if (!draft.err && !draft.refusal) return '';
        const key = refusalKey(draft.refusal);
        return key ? say(key) : (draft.err ?? '');
    });
    const full = $derived(store.limits !== null && store.limits.open_max !== null && store.limits.open_now !== null && store.limits.open_now >= store.limits.open_max);

    const lead = $derived.by(() => {
        if (!store.signedIn) return t('skill.publish.signed_out');
        if (checkedOk) return t('publish.page.next.checked.lead', { version: entry?.version ?? version });
        return step ? leadText(step, '', t) : '';
    });

    async function check(): Promise<void> {
        if (!location) return;
        if (!VERSION_RE.test(version)) {
            drafts.patch(location, { err: t('publish.page.next.version_format'), refusal: '' });
            return;
        }
        drafts.patch(location, { phase: 'checking', err: null, refusal: '' });
        const result = await actions.check(location, version);
        if (result.ok) {
            drafts.patch(location, { phase: 'idle', err: null });
            store.setWizard(result.value.can_send ? 1 : 0);
        } else {
            drafts.patch(location, { phase: 'idle', err: result.text });
        }
    }

    async function madeImage(): Promise<string | null> {
        const colors = heroColors(kind);
        const made = await rasterLadder(canvasEncoder(heroSvg(heroSeed(record?.name ?? '', kind), kind, colors)));
        return made ? fileToBase64(made.blob) : null;
    }

    async function send(): Promise<void> {
        if (!location || reason || !preview || !record) return;
        const imagePlan = ownImage ? 'own' : notes.some((n) => n.reason === 'image_limit') ? 'none' : 'made';
        const file = draft.hero.file;
        drafts.patch(location, { phase: 'sending', err: null, refusal: '', heroOutcome: 'none' });
        const outcome = await runSend({
            image: imagePlan,
            send: () => actions.send({ location, version, digest: preview.digest }),
            imageBase64: () => (imagePlan === 'own' && file ? fileToBase64(file) : madeImage()),
            media: (image) => actions.media(location, { kind: record.kind, name: record.name, image_base64: image, source: imagePlan === 'own' ? 'yours' : 'made' }),
            onHero: (state) => drafts.patch(location, { heroOutcome: state }),
        });
        if (outcome.sent.ok) {
            drafts.afterSend(location, outcome.hero);
            delete store.checks[location];
            store.setWizard(0);
            return;
        }
        drafts.patch(location, { phase: 'idle', err: outcome.sent.text, refusal: outcome.sent.code, heroOutcome: 'none' });
        if (needsRecheck(outcome.sent.code)) {
            delete store.checks[location];
            store.setWizard(0);
        } else if (refusalKey(outcome.sent.code)) {
            void store.loadLimits();
        }
    }

    function typed(event: Event): void {
        drafts.patch(location, { version: (event.currentTarget as HTMLInputElement).value });
    }
</script>

{#if record}
    <div data-pp="SendWizard">
        {#if draft.phase !== 'idle'}
            <Stepper current={draft.phase === 'checking' ? 0 : 2} {t} />
            <p class="d-slot__state" role="status"><span class="d-spin" aria-hidden="true"><Icon name="refresh" size={13} /></span> {draft.phase === 'checking' ? t('skill.publish.checking') : t('skill.publish.sending')}</p>
            {#if draft.heroOutcome === 'making'}<p class="d-slot__why" role="status">{t('publish.page.image_view.generating')}</p>{/if}
        {:else}
            <Stepper current={page} {t} />
            <div class="d-wiz" data-w={page}>
                {#if page === 0}
                    <h3 class="d-wiz__t">{t('publish.page.next.check.title')}</h3>
                    <p class="d-wiz__p">{t('publish.page.next.check.what')}</p>
                    <p class="d-wiz__p"><b>{t('publish.page.next.what_to_do')}</b> {t('publish.page.next.check.todo')}</p>
                    {#if tabOf(kind) === 'plugins'}<p class="d-wiz__p">{t('publish.page.next.check.plugin')}</p>{/if}
                    {#if lead}<p class="d-slot__why" data-lead>{lead}</p>{/if}
                    <div class="d-act">
                        <Field label={t('skill.publish.version')} value={version} oninput={typed} autocomplete="off" spellcheck={false} />
                    </div>
                    <div class="pp-foot">
                        {#if checkedOk}
                            <Button variant="confirm" onclick={() => store.setWizard(1)}>{t('publish.page.next.button.next_image')}</Button>
                            <Button onclick={() => void check()}>{t('publish.page.next.button.check_again')}</Button>
                        {:else}
                            <Button variant="confirm" onclick={() => void check()}>{t('skill.publish.check')}</Button>
                        {/if}
                        {#if failLine}<span class="d-reason" data-tone="yellow" role="alert">{failLine}</span>{/if}
                    </div>
                    {#if !checkedOk}<RegisterBlock {store} {actions} {t} />{/if}
                {:else if page === 1}
                    <h3 class="d-wiz__t">{t('publish.page.next.image.title')}</h3>
                    <p class="d-wiz__p">{t('publish.page.next.image.what')}</p>
                    <ImageStep {store} {actions} {t} />
                    {#each notes as note (note.reason)}<p class="d-reason" role="status">{say(heldKey(note.reason))}</p>{/each}
                    <div class="pp-foot">
                        <Button onclick={() => store.setWizard(0)}>{t('publish.page.next.button.back')}</Button>
                        <Button variant="confirm" onclick={() => store.setWizard(2)}>{t('publish.page.next.button.next_send')}</Button>
                    </div>
                {:else}
                    <h3 class="d-wiz__t">{t('publish.page.next.send.title')}</h3>
                    <p class="d-wiz__p">{full ? t('publish.page.next.send.lead_full', { open: store.limits?.open_now ?? 0, open_max: store.limits?.open_max ?? 0 }) : t('publish.page.next.send.lead_ok', { version: entry?.version ?? version })}</p>
                    <dl class="d-sum">
                        <div><dt>{t('publish.page.next.send.sum_what')}</dt><dd class="pp-ident">{store.account?.handle || t('publish.page.card.owner_fallback')}/{record.name}</dd></div>
                        <div><dt>{t('publish.page.next.send.sum_kind')}</dt><dd>{t(kindWord(kind))}</dd></div>
                        <div><dt>{t('publish.page.next.send.sum_files')}</dt><dd>{preview?.file_count ?? 0}</dd></div>
                        <div><dt>{t('publish.page.next.send.sum_image')}</dt><dd>{ownImage ? t('publish.page.next.send.image_yours') : t('publish.new.hero_made')}</dd></div>
                    </dl>
                    <div class="d-fields">
                        <Field label={t('skill.publish.version')} value={version} oninput={typed} autocomplete="off" spellcheck={false} />
                    </div>
                    <p class="d-wiz__p"><b>{t('publish.page.next.send.after_label')}</b> {t('publish.page.next.send.after')}</p>
                    <div class="pp-foot">
                        <Button onclick={() => store.setWizard(1)}>{t('publish.page.next.button.back')}</Button>
                        <Button variant="confirm" disabled={reason !== null} onclick={() => void send()}>{t('skill.publish.send')}</Button>
                        {#if reason === 'version_changed'}<Button onclick={() => void check()}>{t('skill.publish.check')}</Button>{/if}
                        <span class="d-reason" role="status">{heldLine}</span>
                        {#if store.failure.limits}<span class="d-reason" data-tone="yellow" role="status">{store.failure.limits}</span>{/if}
                        {#if failLine}<span class="d-reason" data-tone="yellow" role="alert">{failLine}</span>{/if}
                    </div>
                    {#each notes as note (note.reason)}<p class="d-reason" role="status">{say(heldKey(note.reason))}</p>{/each}
                    <RegisterBlock {store} {actions} {t} />
                {/if}
            </div>
        {/if}
    </div>
{/if}
