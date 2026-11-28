
<script lang="ts">
    import { PUBLISH_KEYS } from '../../../../client/js/labels/skill-publish.js';
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import Select from '../base/Select.svelte';
    import type { Translate } from '../sessions/types';
    import type { CardView } from './card';
    import { checkScreenshotImage, MAX_IMAGE_BYTES, readBytes } from './card-image';
    import type { CatalogHost } from './catalog';
    import { errorText, fileToBase64 } from './publish';

    interface Props {
        card: CardView;
        host: CatalogHost;
        t: Translate;
    }

    const { card, host, t }: Props = $props();

    let slot = $state('1');
    let caption = $state('');
    let picked = $state<{ file: File; name: string; w: number; h: number } | null>(null);
    let note = $state<{ text: string; bad: boolean } | null>(null);
    let sending = $state(false);
    let fileInput = $state<HTMLInputElement | null>(null);

    const slotOptions = [
        { value: '1', label: '1' },
        { value: '2', label: '2' },
        { value: '3', label: '3' },
        { value: '4', label: '4' },
    ];

    async function take(event: Event): Promise<void> {
        const input = event.currentTarget as HTMLInputElement;
        const file = input.files?.[0];
        input.value = '';
        if (!file) return;
        const bytes = file.size > MAX_IMAGE_BYTES ? new Uint8Array(0) : await readBytes(file).catch(() => new Uint8Array(0));
        const checked = checkScreenshotImage(bytes, file.size);
        if (!checked.ok) {
            note = { text: t(checked.key, checked.params), bad: true };
            picked = null;
            return;
        }
        picked = { file, name: file.name, w: checked.w, h: checked.h };
        note = null;
    }

    async function send(): Promise<void> {
        if (!picked || sending || !host.sendHero || !card.id) return;
        sending = true;
        note = { text: t(PUBLISH_KEYS.heroSending), bad: false };
        try {
            const image = await fileToBase64(picked.file);
            await host.sendHero({
                kind: card.indexKind ?? 'cplug',
                name: card.id.split('/').pop() ?? '',
                role: 'screenshot',
                action: 'set',
                slot: Number(slot),
                caption: caption.trim() || undefined,
                image_base64: image,
            });
            picked = null;
            caption = '';
            note = { text: t(PUBLISH_KEYS.screenshotSent), bad: false };
        } catch (error) {
            note = { text: errorText(error, t), bad: true };
        } finally {
            sending = false;
        }
    }
</script>

<section class="card-shots" aria-label={t(PUBLISH_KEYS.screenshotsLabel)} data-card-screenshots>
    <p class="card-shots__heading">{t(PUBLISH_KEYS.screenshotsLabel)}</p>
    <p class="card-shots__hint">{t(PUBLISH_KEYS.screenshotsHint)}</p>
    <div class="card-shots__controls">
        <div class="card-shots__slot">
            <Select
                label={t(PUBLISH_KEYS.screenshotSlotLabel)}
                bind:value={slot}
                options={slotOptions}
                disabled={sending}
                data-screenshot-slot
            />
        </div>
        <div class="card-shots__caption">
            <Field
                label={t(PUBLISH_KEYS.screenshotCaptionLabel)}
                bind:value={caption}
                maxlength={80}
                disabled={sending}
                data-screenshot-caption
            />
        </div>
    </div>
    <div class="card-shots__acts">
        <input
            bind:this={fileInput}
            hidden
            type="file"
            accept="image/png,image/jpeg,image/webp"
            aria-label={t(PUBLISH_KEYS.screenshotChoose)}
            onchange={take}
        />
        <Button variant="secondary" disabled={sending} data-screenshot-choose onclick={() => fileInput?.click()}>
            {t(PUBLISH_KEYS.screenshotChoose)}
        </Button>
        {#if picked}
            <Button variant="confirm" disabled={sending} data-screenshot-send onclick={send}>
                {t(PUBLISH_KEYS.send)}
            </Button>
            <Button variant="quiet" disabled={sending} onclick={() => { picked = null; note = null; }}>
                {t(PUBLISH_KEYS.cardImageDiscard)}
            </Button>
        {/if}
    </div>
    {#if picked}
        <p class="card-shots__meta">{picked.name} ({picked.w}&times;{picked.h})</p>
    {/if}
    {#if note}
        <p class="card-shots__note" class:card-shots__note--bad={note.bad} role="status">{note.text}</p>
    {/if}
</section>

<style>
  @layer components {
    .card-shots {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-2);
        padding-top: var(--oc-space-2);
        border-top: var(--oc-border) solid var(--oc-line-faint);
    }

    .card-shots__heading {
        margin: 0;
        color: var(--oc-text-muted);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-micro);
        letter-spacing: var(--oc-tracking-label);
        text-transform: uppercase;
    }

    .card-shots__hint,
    .card-shots__meta,
    .card-shots__note {
        margin: 0;
        color: var(--oc-text-secondary);
        font-size: var(--oc-fs-label);
        line-height: var(--oc-lh-body);
    }

    .card-shots__note--bad {
        color: var(--oc-coral);
    }

    .card-shots__controls {
        display: flex;
        flex-wrap: wrap;
        gap: var(--oc-space-2);
        align-items: flex-end;
    }

    .card-shots__slot {
        width: 84px;
        flex: 0 0 auto;
    }

    .card-shots__caption {
        flex: 1 1 180px;
        min-width: 0;
    }

    .card-shots__acts {
        display: flex;
        flex-wrap: wrap;
        gap: var(--oc-space-2);
    }
  }
</style>
