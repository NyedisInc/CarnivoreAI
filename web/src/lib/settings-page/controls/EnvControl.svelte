
<script lang="ts">
    import Button from '../../base/Button.svelte';
    import Field from '../../base/Field.svelte';
    import type { Translate } from '../../sessions/types';
    import { settingsDoc, type EnvRow } from '../settings-doc.svelte';

    interface Props {
        t: Translate;
        inputId: string;
    }

    const { t, inputId }: Props = $props();

    const rows = $derived((settingsDoc.value('environment') as EnvRow[] | undefined) ?? [{ name: '', value: '' }]);

    function write(next: EnvRow[]): void {
        settingsDoc.setDraft('environment', next.length ? next : [{ name: '', value: '' }]);
    }

    function edit(index: number, part: 'name' | 'value', text: string): void {
        write(rows.map((row, i) => (i === index ? { ...row, [part]: text } : row)));
    }
</script>

<div class="st-env">
    <div class="st-env__row oc-colhead" data-env-head>
        <span class="oc-label">{t('settings.env.col.name')}</span>
        <span class="oc-label">{t('settings.env.col.value')}</span>
        <span class="oc-colhead__ghost" aria-hidden="true"><Button size="sm" tabindex={-1}>{t('settings.env.remove_short')}</Button></span>
    </div>
    {#each rows as row, index (index)}
        <div class="st-env__row" data-env-row>
            <Field
                id={index === 0 ? inputId : undefined}
                block
                placeholder={t('settings.env.name_placeholder')}
                spellcheck={false}
                aria-label={t('settings.env.name')}
                value={row.name}
                oninput={(event) => edit(index, 'name', (event.currentTarget as HTMLInputElement).value)}
            />
            <div class="st-env__value">
                <Field
                    block
                    placeholder={t('settings.env.value_placeholder')}
                    spellcheck={false}
                    aria-label={t('settings.env.value')}
                    value={row.value}
                    oninput={(event) => edit(index, 'value', (event.currentTarget as HTMLInputElement).value)}
                />
            </div>
            <Button
                size="sm"
                aria-label={t('settings.env.remove', { name: row.name || t('settings.env.unnamed') })}
                onclick={() => write(rows.filter((_, i) => i !== index))}
            >{t('settings.env.remove_short')}</Button>
        </div>
    {/each}
    {#each settingsDoc.warnings as warning (warning)}
        <p class="sf__error" data-env-warning>{warning}</p>
    {/each}
    <div>
        <Button onclick={() => write([...rows, { name: '', value: '' }])}>
            {t('settings.env.add')}
        </Button>
    </div>
</div>
