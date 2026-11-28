<!-- cannot be read -->
<script lang="ts">
    import { onMount } from 'svelte';
    import { t } from '../i18n/index.svelte';
    import { browserCatalogHost } from '../catalog/catalog';
    import { Button, Field, IconButton } from '../base';

    interface Props {
        skills: string[];
        onChange: (skills: string[]) => void;
        idPrefix: string;
    }

    let { skills, onChange, idPrefix }: Props = $props();

    let draft = $state('');
    let known = $state<string[]>([]);
    let catalogFailed = $state(false);

    onMount(async () => {
        try {
            const host = browserCatalogHost();
            const listing = await host.listItems();
            known = (listing.items ?? [])
                .filter((item) => item.kind === 'skill')
                .map((item) => (typeof item.id === 'string' && item.id ? item.id : `${item.publisher ?? ''}/${item.name ?? ''}`))
                .filter((id) => id && id !== '/');
        } catch {
            catalogFailed = true;
        }
    });

    function add(): void {
        const id = draft.trim();
        if (!id || skills.includes(id)) {
            draft = '';
            return;
        }
        onChange([...skills, id]);
        draft = '';
    }

    function remove(id: string): void {
        onChange(skills.filter((s) => s !== id));
    }

    function onKey(event: KeyboardEvent): void {
        if (event.key === 'Enter') {
            event.preventDefault();
            add();
        }
    }
</script>

<div class="bp-skills">
    <div class="bp-skills__chips">
        {#each skills as id (id)}
            <span class="bp-skills__chip">
                {id}
                <IconButton
                    variant="danger"
                    icon="close"
                    iconSize={10}
                    label={t('blueprint.session.skills.remove', { skill: id })}
                    onclick={() => remove(id)}
                />
            </span>
        {/each}
        {#if skills.length === 0}
            <span class="bp-skills__none">{t('blueprint.session.skills.none')}</span>
        {/if}
    </div>
    <div class="bp-skills__add">
        <Field
            id={`${idPrefix}-skill-input`}
            aria-label={t('blueprint.session.skills')}
            list={catalogFailed ? undefined : `${idPrefix}-skill-list`}
            placeholder={t('skills.picker.ref.placeholder')}
            spellcheck="false"
            autocomplete="off"
            bind:value={draft}
            onkeydown={onKey}
        />
        {#if !catalogFailed}
            <datalist id={`${idPrefix}-skill-list`}>
                {#each known as id (id)}
                    <option value={id}></option>
                {/each}
            </datalist>
        {/if}
        <Button onclick={add}>{t('blueprint.session.skills.add')}</Button>
    </div>
</div>

<style>
    .bp-skills__chips {
        display: flex;
        flex-wrap: wrap;
        gap: var(--oc-space-1-5);
        margin-bottom: var(--oc-space-1-5);
        min-height: 20px;
    }

    .bp-skills__chip {
        display: inline-flex;
        align-items: center;
        gap: var(--oc-space-1);
        padding: var(--oc-space-0-5) var(--oc-space-1-5);
        border: var(--oc-border) solid var(--oc-line-rule);
        border-radius: var(--oc-radius-control);
        background: var(--oc-ground-raised);
        color: var(--oc-text-primary);
        font-size: var(--oc-fs-label);
        font-family: var(--font-mono);
    }

    .bp-skills__none {
        color: var(--oc-text-muted);
        font-size: var(--oc-fs-label);
    }

    .bp-skills__add {
        display: flex;
        gap: var(--oc-space-1-5);
        align-items: center;
    }

    .bp-skills__add :global([data-field]) {
        flex: 1;
        min-width: 0;
    }
</style>
