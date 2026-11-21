
<script lang="ts">
    import type { Snippet } from 'svelte';
    import { IconButton, Segmented, Select, Button } from '../../base';
    import type { Translate } from '../../sessions/types';
    import { isRateLimited } from '../destinations/api';
    import { failureKey } from '../destinations/form-logic';
    import { ApiError } from '../../../opscenter/api/auth.svelte';
    import { playSound } from '../sound-player';
    import { sendTest, type Fetcher, type StylePatch, type TestTarget } from './api';
    import { playable } from './logic';

    interface Props {
        disabled: boolean; sound: string; urgency: string; sounds: readonly string[]; urgencies: readonly string[]; testType: string;
        onStyle: (patch: StylePatch) => void; fetcher?: Fetcher; children: Snippet; t: Translate;
    }
    const { disabled, sound, urgency, sounds, urgencies, testType, onStyle, fetcher, children, t }: Props = $props();

    const URGENCY_KEY: Record<string, string> = { passive: 'passive', active: 'active', 'time-sensitive': 'time_sensitive' };
    const soundLabel = (s: string): string => t(`notify.inspector.sound.${s}`);
    const TESTS: readonly { target: TestTarget; key: 'phone' | 'desk' | 'app' }[] = [
        { target: 'phone', key: 'phone' }, { target: 'desktop', key: 'desk' }, { target: 'app', key: 'app' },
    ];

    let results = $state<Record<string, string>>({});
    let sending = $state<Record<string, boolean>>({});
    $effect(() => { void testType; results = {}; });

    async function run(target: TestTarget, key: string): Promise<void> {
        sending = { ...sending, [target]: true };
        let line: string;
        try {
            const answer = await sendTest(testType, target, fetcher);
            line = answer.ok ? t(`notify.routing.test.sent.${key}`) : answer.failure ? t(failureKey(answer.failure)) : t('notify.routing.test.failed');
        } catch (error) {
            line = isRateLimited(error) ? t('notify.routing.test.wait')
                : error instanceof ApiError && error.status === 404 ? t('notify.routing.test.no_phone') : t('notify.routing.test.failed');
        }
        sending = { ...sending, [target]: false };
        results = { ...results, [target]: line };
    }
</script>

<div class="ins-secs" data-ins="sections" data-disabled={disabled ? '' : undefined}>
    <div class="ins-sec" data-sec="where">
        <div class="ins-sec__bar"><span class="ins-label">{t('notify.routing.sec.send')}</span></div>
        <div class="ins-sec__body ins-sec__body--flush">{@render children()}</div>
    </div>
    <div class="ins-sec" data-sec="sound">
        <div class="ins-sec__bar"><span class="ins-label">{t('notify.routing.sec.sound')}</span></div>
        <div class="ins-sec__body">
            <div class="ins-row">
                <Select size="sm" aria-label={t('notify.inspector.col.sound')} value={sound} data-ins="sound"
                    options={sounds.map((s) => ({ value: s, label: soundLabel(s) }))} onchange={(e) => onStyle({ sound: (e.currentTarget as HTMLSelectElement).value })} />
                <IconButton icon="play" label={t('notify.routing.sound.play', { sound: soundLabel(sound) })} data-ins="play" disabled={!playable(sound)} onclick={() => playSound(sound)} />
            </div>
            <div class="ins-row">
                <Segmented label={t('notify.inspector.col.urgency')} size="sm" value={urgency} data-ins="urgency"
                    options={urgencies.map((u) => ({ value: u, label: t(`notify.inspector.level.${URGENCY_KEY[u] ?? 'active'}`) }))} onchange={(v) => onStyle({ urgency: v })} />
                <span class="ins-dim" data-ins="urgency-hint">{t(`notify.settings.urgency.${URGENCY_KEY[urgency] ?? 'active'}`)}</span>
            </div>
        </div>
    </div>
    <div class="ins-sec" data-sec="test">
        <div class="ins-sec__bar"><span class="ins-label">{t('notify.routing.sec.test')}</span></div>
        <div class="ins-sec__body">
            {#each TESTS as x (x.target)}
                <div class="ins-row ins-test" data-test={x.target}>
                    <Button size="sm" data-ins="test" data-test-button={x.target} disabled={sending[x.target]} onclick={() => void run(x.target, x.key)}>{t(`notify.routing.test.${x.key}`)}</Button>
                    <span class="ins-dim" role="status" data-ins="test-result">{sending[x.target] ? t('notify.routing.test.sending') : (results[x.target] ?? '')}</span>
                </div>
            {/each}
        </div>
    </div>
</div>
