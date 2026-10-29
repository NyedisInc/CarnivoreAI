<!-- on the card and -->
<script lang="ts">
    import { PUBLISH_KEYS } from '../../../../client/js/labels/skill-publish.js';
    import type { Translate } from '../sessions/types';
    import type { CardView } from './card';
    import type { CatalogHost } from './catalog';
    import type { PublishAccount } from './publish';
    import { errorText, fileToBase64 } from './publish';
    import { clipChars } from './bounds';
    import { checkHeroImage, MAX_IMAGE_BYTES, ownsItem, readBytes } from './card-image';
    import { clearPreview, markSent, previewFor, setPreview } from './card-image-store.svelte';

    interface Props {
        card: CardView;
        host: CatalogHost;
        signedIn?: boolean;
        t: Translate;
        owns?: boolean;
    }

    let { card, host, signedIn = false, t, owns = $bindable(false) }: Props = $props();

    let handle = $state<string | null>(null);
    let note = $state<{ text: string; bad: boolean } | null>(null);
    let sending = $state(false);

    $effect(() => {
        let live = true;
        handle = null;
        if (!signedIn) {
            forgetAccount(host);
            return;
        }
        if (!host.publishAccount) return;
        void accountOf(host).then((account) => {
            if (live) handle = account?.handle || null;
        });
        return () => {
            live = false;
        };
    });

    const mine = $derived(signedIn && ownsItem(handle, card));
    $effect(() => {
        owns = mine;
    });

    const itemId = $derived(card.id ?? '');
    const preview = $derived(previewFor(itemId));
    const intro = $derived(
        card.kind === 'theme' && !card.mediaSha
            ? PUBLISH_KEYS.cardImageIntroTheme
            : card.mediaSha
              ? PUBLISH_KEYS.cardImageIntroReplace
              : PUBLISH_KEYS.cardImageIntroNew,
    );
    const shown = $derived(
        note ??
            (preview
                ? { text: t(preview.sent ? PUBLISH_KEYS.heroSent : PUBLISH_KEYS.cardImageLocalOnly), bad: false }
                : null),
    );

    async function opens(url: string): Promise<boolean> {
        const probe = new Image();
        if (typeof probe.decode !== 'function') return true;
        probe.src = url;
        try {
            await probe.decode();
            return true;
        } catch {
            return false;
        }
    }

    async function take(event: Event): Promise<void> {
        const input = event.currentTarget as HTMLInputElement;
        const file = input.files?.[0];
        input.value = '';
        if (!file) return;
        const bytes = file.size > MAX_IMAGE_BYTES ? new Uint8Array(0) : await readBytes(file).catch(() => new Uint8Array(0));
        const checked = checkHeroImage(bytes, file.size);
        if (!checked.ok) {
            note = { text: t(checked.key, checked.params), bad: true };
            return;
        }
        const url = URL.createObjectURL(file);
        if (!(await opens(url))) {
            URL.revokeObjectURL(url);
            note = { text: t(PUBLISH_KEYS.cardImageUnreadable), bad: true };
            return;
        }
        setPreview(itemId, {
            url,
            file,
            name: file.name,
            w: checked.w,
            h: checked.h,
            kb: Math.max(1, Math.round(file.size / 1024)),
            sent: false,
        });
        note = null;
    }

    async function send(): Promise<void> {
        const held = preview;
        if (!held || held.sent || sending || !host.sendHero) return;
        sending = true;
        note = { text: t(PUBLISH_KEYS.heroSending), bad: false };
        try {
            const image = await fileToBase64(held.file);
            await host.sendHero({ kind: card.indexKind ?? 'skill', name: itemId.split('/').pop() ?? '', image_base64: image });
            markSent(itemId);
            note = null;
        } catch (error) {
            note = { text: errorText(error, t), bad: true };
        } finally {
            sending = false;
        }
    }

    function discard(): void {
        clearPreview(itemId);
        note = null;
    }
</script>

<script module lang="ts">
    const accounts = new WeakMap<object, Promise<PublishAccount | null>>();

    function accountOf(host: CatalogHost): Promise<PublishAccount | null> {
        let held = accounts.get(host);
        if (!held) {
            const read: Promise<PublishAccount | null> = (host.publishAccount?.() ?? Promise.resolve(null))
                .then((account) => {
                    if (!account) forgetIf(host, read);
                    return account;
                })
                .catch(() => {
                    forgetIf(host, read);
                    return null;
                });
            held = read;
            accounts.set(host, held);
        }
        return held;
    }

    function forgetAccount(host: CatalogHost): void {
        accounts.delete(host);
    }

    function forgetIf(host: CatalogHost, read: Promise<unknown>): void {
        if (accounts.get(host) === read) accounts.delete(host);
    }
</script>

{#if mine}
    <section class="card-image" aria-label={t(PUBLISH_KEYS.cardImageLabel)} data-card-image>
        <p class="card-image__heading">{t(PUBLISH_KEYS.cardImageLabel)}</p>
        <p class="card-image__intro">{t(intro)}</p>
        <p class="card-image__hint">{t(PUBLISH_KEYS.heroHint)}</p>
        <div class="card-image__acts">
            <label class="modal-btn modal-btn-secondary card-image__file">
                {t(PUBLISH_KEYS.cardImageChoose)}
                <input
                    class="card-image__file-input"
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    aria-label={t(PUBLISH_KEYS.cardImageChooseAria)}
                    onchange={take}
                />
            </label>
            {#if preview && !preview.sent}
                <button type="button" class="modal-btn modal-btn-confirm" disabled={sending} onclick={send}>
                    {t(PUBLISH_KEYS.send)}
                </button>
            {/if}
            {#if preview}
                <button type="button" class="modal-btn modal-btn-secondary" onclick={discard}>
                    {t(preview.sent ? PUBLISH_KEYS.cardImageClear : PUBLISH_KEYS.cardImageDiscard)}
                </button>
            {/if}
        </div>
        {#if preview}
            <p class="card-image__meta">
                {t(PUBLISH_KEYS.cardImageFileMeta, {
                    name: clipChars(preview.name, 80) ?? '',
                    w: String(preview.w),
                    h: String(preview.h),
                    kb: String(preview.kb),
                })}
            </p>
        {/if}
        {#if shown}
            <p class="card-image__note" class:card-image__note--bad={shown.bad} role="status">{shown.text}</p>
        {/if}
    </section>
{/if}

<style>
    @layer components {
        .card-image {
            display: flex;
            flex-direction: column;
            gap: 8px;
            min-width: 0;
        }

        .card-image__intro {
            margin: 0;
            color: var(--oc-text-secondary);
            font-size: 12px;
            line-height: 1.5;
        }

        .card-image__hint,
        .card-image__meta {
            margin: 0;
            color: var(--oc-text-muted);
            font-size: 11px;
            line-height: 1.45;
            overflow-wrap: anywhere;
        }

        .card-image__acts {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }

        .card-image__file {
            position: relative;
            cursor: pointer;
        }

        .card-image__file-input {
            position: absolute;
            inset: 0;
            width: 100%;
            opacity: 0;
            cursor: pointer;
        }

        .card-image__note {
            margin: 0;
            color: var(--oc-text-secondary);
            font-size: 11px;
            line-height: 1.45;
        }

        .card-image__note--bad {
            color: var(--oc-coral);
        }

        .card-image__acts :global(.modal-btn) {
            padding: 3px 10px !important;
            font-size: 11px !important;
            border-radius: 2px !important;
            line-height: 1.4 !important;
        }
        .card-image__acts :global(.card-image__file) {
            display: flex !important;
            align-items: center !important;
        }
    }
</style>
