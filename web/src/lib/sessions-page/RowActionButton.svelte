
<script lang="ts">
    import type { HTMLButtonAttributes } from 'svelte/elements';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import Button from '../base/Button.svelte';
    import type { Translate } from '../sessions/types';
    import type { RowAction } from './row-action';

    interface Props extends Omit<HTMLButtonAttributes, 'class' | 'children'> {
        action: RowAction;
        name: string;
        t: Translate;
        size?: 'md' | 'sm';
    }

    const { action, name, t, size = 'sm', ...rest }: Props = $props();
</script>

<Button {size} data-go={action} aria-label={t(`sessions.page.act.${action}.label`, { name })} {...rest}>
    {#if action === 'open'}<Icon name="prompt-open" size={14} />{:else if action === 'wake'}<Icon name="bolt" size={14} />{/if}
    <span>{t(`sessions.page.act.${action}`)}</span>
</Button>
