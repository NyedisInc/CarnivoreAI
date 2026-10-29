
<script lang="ts">
    import Checkbox from '../../base/Checkbox.svelte';
    import type { Translate } from '../../sessions/types';
    import { visibleCommand, type CommandRow } from './api';
    import '../../plugins-page/plugin-pane.css';

    interface Props {
        rows: readonly CommandRow[];
        busy?: boolean;
        ready?: boolean;
        t: Translate;
    }

    let { rows, busy = false, ready = $bindable(false), t }: Props = $props();

    let ticked = $state<Record<string, boolean>>({});
    ready = false;

    function setTick(key: string, on: boolean): void {
        ticked[key] = on;
        ready = rows.length > 0 && rows.every((row) => ticked[row.key] === true);
    }
</script>

<section class="plp-region" data-cb-commands aria-label={t('settings.configbundle.commands.title')}>
    <div class="pl-label">{t('settings.configbundle.commands.title')}</div>
    <p class="plp-warn">{t('settings.configbundle.commands.note')}</p>
    <ul class="plp-rows">
        {#each rows as row (row.key)}
            <li class="plp-row" class:plp-row--missing={ticked[row.key] !== true} data-cb-command={row.key}>
                <Checkbox
                    data-cb-tick={row.key}
                    aria-label={t('settings.configbundle.commands.tick', { name: row.name })}
                    checked={ticked[row.key] === true}
                    disabled={busy}
                    onchange={(e) => setTick(row.key, e.currentTarget.checked)}
                />
                <span class="plp-row__main"
                    ><span class="cmds__name" data-cb-name>{visibleCommand(row.name)}</span><span class="plp-row__sub"
                        >{t(`settings.configbundle.commands.kind.${row.kind}`)} <code class="cmds__id" data-cb-id>{visibleCommand(row.id)}</code></span
                    >
                    {#each row.parts as part, index (index)}
                        <span class="plp-row__sub">{part.kind}</span><code class="cmds__part">{visibleCommand(part.text)}</code>
                    {/each}
                </span>
                <span class="plp-tag" data-tone={ticked[row.key] === true ? 'ok' : 'warn'}>
                    {t(ticked[row.key] === true ? 'settings.configbundle.commands.allowed' : 'settings.configbundle.commands.not_allowed')}
                </span>
            </li>
        {/each}
    </ul>
</section>

<style>
    .cmds__name {
        unicode-bidi: isolate;
    }

    .cmds__id {
        font-family: var(--font-mono);
    }

    .cmds__part {
        display: block;
        margin: var(--oc-space-0-5) 0 var(--oc-space-1);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-label);
        color: var(--oc-text-primary);
        white-space: pre-wrap;
        overflow-wrap: anywhere;
    }
</style>
