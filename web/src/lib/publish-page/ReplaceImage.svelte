
<script lang="ts">
    import { PUBLISH_KEYS } from '../../../../client/js/labels/skill-publish.js';
    import Button from '../base/Button.svelte';
    import { fileToBase64 } from '../catalog/publish';
    import { checkHeroFile, opensAsImage } from './hero-check';
    import type { PageProps } from './props';

    interface Props extends PageProps {
        location: string;
        kind: string;
        name: string;
        label: string;
    }
    const { actions, t, location, kind, name, label }: Props = $props();

    let picker = $state<HTMLInputElement | null>(null);
    let busy = $state(false);
    let err = $state<string | null>(null);

    async function take(event: Event): Promise<void> {
        const input = event.currentTarget as HTMLInputElement;
        const file = input.files?.[0];
        input.value = '';
        if (!file) return;
        err = null;
        const checked = await checkHeroFile(file);
        if (!checked.ok) {
            err = t(checked.key, checked.params);
            return;
        }
        const url = URL.createObjectURL(file);
        const readable = await opensAsImage(url);
        URL.revokeObjectURL(url);
        if (!readable) {
            err = t(PUBLISH_KEYS.cardImageUnreadable);
            return;
        }
        busy = true;
        const result = await actions.media(location, { kind, name, image_base64: await fileToBase64(file), source: 'yours' });
        busy = false;
        if (!result.ok) err = result.text;
    }
</script>

<div class="pp-foot" data-pp="ReplaceImage">
    <Button disabled={busy} onclick={() => picker?.click()}>{t(label)}</Button>
    <input bind:this={picker} class="d-hero__file" type="file" accept="image/png,image/jpeg,image/webp" aria-label={t('skill.publish.card_image.choose_aria')} onchange={(e) => void take(e)} />
</div>
{#if err}<p class="d-hero__err" role="alert">{err}</p>{/if}
