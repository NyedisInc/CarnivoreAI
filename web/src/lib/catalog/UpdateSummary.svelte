
<script lang="ts">
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import Tag from '../base/Tag.svelte';
    import type { Translate } from '../sessions/types';
    import type { CardScreenshotView } from './card';
    import CardMediaImg from './CardMediaImg.svelte';
    import type { UpdateNoteItem } from './update-notes';

    interface Props {
        fromVersion?: string | null;
        toVersion?: string | null;
        notes: readonly UpdateNoteItem[];
        screenshots?: readonly CardScreenshotView[];
        noPermissions?: boolean;
        noTools?: boolean;
        permissionsUnchanged?: boolean;
        t: Translate;
    }

    const {
        fromVersion = null,
        toVersion = null,
        notes,
        screenshots = [],
        noPermissions = false,
        noTools = false,
        permissionsUnchanged = false,
        t,
    }: Props = $props();
</script>

<section class="usum" data-update-summary>
    <div class="usum__top">
        {#if fromVersion || toVersion}
            <div class="usum__ver" data-update-versions>
                {#if fromVersion}
                    <span class="usum__v-old">v{fromVersion}</span>
                    <span class="usum__arrow" aria-hidden="true">&rarr;</span>
                {/if}
                {#if toVersion}
                    <span class="usum__v-new">v{toVersion}</span>
                {/if}
            </div>
        {/if}
        <div class="usum__pills" data-update-status-pills>
            {#if noPermissions}
                <Tag tone="ok">{t(SKILL_KEYS.updateNoPermissions)}</Tag>
            {:else if permissionsUnchanged}
                <Tag tone="ok">{t(SKILL_KEYS.updatePermissionsUnchanged)}</Tag>
            {/if}
            {#if noTools && noPermissions}
                <Tag tone="ok">{t(SKILL_KEYS.updateNoTools)}</Tag>
            {/if}
        </div>
    </div>

    {#if notes.length > 0}
        <div class="usum__notes" data-update-notes>
            <p class="usum__label">{t(SKILL_KEYS.updateWhatsNew)}</p>
            <ul class="usum__list">
                {#each notes as item}
                    <li class="usum__item">
                        <span class="usum__ico usum__ico--{item.tone}" aria-hidden="true">
                            <Icon name={item.icon} size={13} />
                        </span>
                        <span class="usum__text">{item.text}</span>
                    </li>
                {/each}
            </ul>
        </div>
    {/if}

    {#if screenshots.length > 0}
        <div class="usum__shots" data-update-screenshots>
            <p class="usum__label">{t(SKILL_KEYS.updateScreenshotsHeading)}</p>
            <div class="usum__strip">
                {#each screenshots.slice(0, 3) as shot}
                    <figure class="usum__shot" data-update-shot={shot.sha}>
                        <div class="usum__frame">
                            <CardMediaImg sha={shot.sha} />
                        </div>
                        {#if shot.caption}
                            <figcaption class="usum__cap">{shot.caption}</figcaption>
                        {/if}
                    </figure>
                {/each}
            </div>
        </div>
    {/if}
</section>

<style>
  @layer components {
    .usum {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-2);
    }

    .usum__top {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: var(--oc-space-2);
    }

    .usum__ver {
        display: inline-flex;
        align-items: center;
        gap: var(--oc-space-1-5);
        padding: var(--oc-space-0-5) var(--oc-space-2);
        border: var(--oc-border) solid var(--oc-line-rule);
        border-radius: var(--oc-radius-control);
        background: var(--oc-ground-raised);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-label);
        letter-spacing: var(--oc-tracking-label);
    }

    .usum__v-old {
        color: var(--oc-text-muted);
    }

    .usum__arrow {
        color: var(--oc-green);
    }

    .usum__v-new {
        color: var(--oc-text-bright);
    }

    .usum__pills {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: var(--oc-space-1-5);
    }

    .usum__notes {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-2);
        padding: var(--oc-space-3);
        border: var(--oc-border) solid var(--oc-line-rule);
        border-radius: var(--oc-radius-panel);
        background: var(--oc-ground-raised);
    }

    .usum__label {
        margin: 0;
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-micro);
        letter-spacing: var(--oc-tracking-label);
        text-transform: uppercase;
    }

    .usum__list {
        margin: 0;
        padding: 0;
        list-style: none;
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-2);
    }

    .usum__item {
        display: flex;
        align-items: flex-start;
        gap: var(--oc-space-2);
    }

    .usum__ico {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        flex: none;
        width: var(--oc-space-5);
        height: var(--oc-space-5);
        margin-top: var(--oc-space-0-5);
        border-radius: var(--oc-radius-control);
        border: var(--oc-border) solid var(--oc-line-faint);
    }

    .usum__ico--ok {
        color: var(--oc-green);
        border-color: color-mix(in srgb, var(--oc-green) 45%, var(--oc-line-faint));
        background: color-mix(in srgb, var(--oc-green) 12%, var(--oc-ground-field));
    }

    .usum__ico--info {
        color: var(--oc-cyan);
        border-color: color-mix(in srgb, var(--oc-cyan) 45%, var(--oc-line-faint));
        background: color-mix(in srgb, var(--oc-cyan) 12%, var(--oc-ground-field));
    }

    .usum__ico--accent {
        color: var(--oc-orange);
        border-color: color-mix(in srgb, var(--oc-orange) 45%, var(--oc-line-faint));
        background: color-mix(in srgb, var(--oc-orange) 12%, var(--oc-ground-field));
    }

    .usum__ico--warn {
        color: var(--oc-yellow);
        border-color: color-mix(in srgb, var(--oc-yellow) 45%, var(--oc-line-faint));
        background: color-mix(in srgb, var(--oc-yellow) 12%, var(--oc-ground-field));
    }

    .usum__text {
        flex: 1 1 auto;
        min-width: 0;
        color: var(--oc-text-bright);
        font-size: var(--oc-fs-body);
        line-height: var(--oc-lh-body);
        overflow-wrap: anywhere;
    }

    .usum__shots {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-1-5);
    }

    .usum__strip {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
        gap: var(--oc-space-2);
    }

    .usum__shot {
        margin: 0;
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-1);
        padding: var(--oc-space-1);
        border: var(--oc-border) solid var(--oc-line-rule);
        border-radius: var(--oc-radius-control);
        background: var(--oc-ground-field);
    }

    .usum__frame {
        position: relative;
        width: 100%;
        aspect-ratio: 16 / 10;
        overflow: hidden;
        border-radius: var(--oc-radius-control);
        background: var(--oc-ground-raised);
    }

    .usum__cap {
        color: var(--oc-text-secondary);
        font-size: var(--oc-fs-micro);
        line-height: var(--oc-lh-body);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
  }
</style>
