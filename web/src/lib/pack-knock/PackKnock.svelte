
<script lang="ts">
    import { auth } from '../../opscenter/api/auth.svelte';
    import { t } from '../i18n/index.svelte';
    import AnchoredPopup from '../dialog-frame/AnchoredPopup.svelte';
    import Button from '../base/Button.svelte';
    import { countdownText } from './countdown';
    import { hide, notMe, reread, shown, startKnocks } from './knock-store.svelte';

    const knock = $derived(shown());
    let now = $state(Date.now());
    const left = $derived(knock ? Math.max(Math.round((Date.parse(knock.expires_at) - now) / 1000), 0) : 0);

    $effect(() => {
        if (auth.state === 'signed-in') startKnocks();
    });

    const expiryKey = $derived(knock ? `${knock.id}|${knock.expires_at}` : '');
    $effect(() => {
        if (!expiryKey) return;
        const wait = Math.max(Date.parse(expiryKey.split('|')[1]) - Date.now(), 0) + 500;
        const timer = setTimeout(() => {
            now = Date.now();
            void reread();
        }, wait);
        return () => clearTimeout(timer);
    });

    $effect(() => {
        if (knock) now = Date.now();
    });

    const cellsOf = (code: string | null): string[] => Array.from({ length: 6 }, (_, i) => code?.[i] ?? '');
</script>

{#if knock}
    <div class="pk-scrim" data-pack-knock="scrim"></div>
    <AnchoredPopup class="pk" role="alertdialog" label={t('pack_knock.title')} placement="manual" style="top:50%;left:50%;transform:translate(-50%,-50%)"
        outside="none" initialFocus="[data-pack-knock='hide']" onClose={() => hide(knock.id)} data-pack-knock="popup">
        <div class="pk__strip"><span class="pk__label">{t('pack_knock.label')}</span></div>
        <div class="pk__body">
            <p class="pk__title">{t('pack_knock.title')}</p>
            <p class="pk__line" data-pack-knock="who">{t('pack_knock.body', { name: knock.label, fid: knock.fid_short, addr: knock.addr })}</p>
            {#if knock.code}
                <div class="pk__cells" role="group" aria-label={t('pack_knock.code_label')} data-pack-knock="code">
                    {#each cellsOf(knock.code) as digit, i (i)}<span class="pk__cell">{digit}</span>{/each}
                </div>
                <p class="pk__line pk__line--dim" data-pack-knock="expires">{t('pack_knock.expires', { time: countdownText(left, t) })}</p>
            {:else}
                <p class="pk__line" data-pack-knock="replaced">{t('pack_knock.replaced')}</p>
            {/if}
            <div class="pk__foot">
                <Button variant="danger" size="sm" data-pack-knock="not-me" onclick={() => void notMe(knock.id)}>{t('pack_knock.not_me')}</Button>
                <Button size="sm" data-pack-knock="hide" onclick={() => hide(knock.id)}>{t('pack_knock.hide')}</Button>
            </div>
        </div>
    </AnchoredPopup>
{/if}

<style>
    @layer components {
        .pk-scrim {
            position: fixed;
            inset: 0;
            z-index: calc(var(--oc-z-popover) - 1);
            background: var(--oc-backdrop);
        }

        :global(.pk) {
            box-sizing: border-box;
            width: calc(24 * var(--oc-space-4));
            max-width: calc(100vw - 2 * var(--oc-space-4));
            font-family: var(--font-mono);
        }

        .pk__strip {
            display: flex;
            align-items: center;
            min-height: var(--oc-titlerow-h, 37px);
            padding: 0 var(--oc-space-3);
            background: var(--oc-ground-titlerow);
            box-shadow: 0 1px 0 var(--oc-line-hairline);
        }

        .pk__label {
            color: var(--oc-orange);
            font-size: var(--oc-fs-label);
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }

        .pk__body {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-3);
            padding: var(--oc-space-3);
        }

        .pk__title {
            margin: 0;
            color: var(--oc-text-bright);
            font-size: var(--oc-fs-body);
        }

        .pk__line {
            margin: 0;
            color: var(--oc-text-primary);
            font-size: var(--oc-fs-body);
            overflow-wrap: anywhere;
        }

        .pk__line--dim {
            color: var(--oc-text-muted);
        }

        .pk__cells {
            display: flex;
            gap: var(--oc-space-2);
        }

        .pk__cell {
            display: flex;
            flex: 1;
            align-items: center;
            justify-content: center;
            height: calc(3 * var(--oc-space-4));
            min-width: 0;
            color: var(--oc-text-bright);
            background: var(--oc-ground-titlerow);
            box-shadow: inset 0 0 0 1px var(--oc-line-hairline);
            font-size: calc(1.5 * var(--oc-fs-body));
        }

        .pk__foot {
            display: flex;
            justify-content: flex-end;
            gap: var(--oc-space-2);
        }
    }
</style>
