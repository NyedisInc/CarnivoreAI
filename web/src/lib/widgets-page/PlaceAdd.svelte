<!-- could not be read -->
<script lang="ts">
    import Icon from '../../opscenter/ui/Icon.svelte';
    import type { Translate } from '../sessions/types';

    interface Props {
        here: boolean;
        blocked: boolean;
        disabled?: boolean;
        name: string;
        t: Translate;
        onMain: (anchor: HTMLElement) => void;
        onCaret: (anchor: HTMLElement) => void;
    }

    const { here, blocked, disabled = false, name, t, onMain, onCaret }: Props = $props();
</script>

<span class="wp-add" data-dis={here && blocked ? '' : undefined}>
    <button
        type="button"
        class="wp-add__main"
        disabled={disabled || (here && blocked)}
        aria-haspopup={here ? undefined : 'menu'}
        aria-label={here ? t('widgets.places.card.add_here_label', { name }) : t('widgets.places.card.add_label', { name })}
        onclick={(event) => {
            event.stopPropagation();
            onMain(event.currentTarget as HTMLElement);
        }}
    >{here ? t('widgets.places.card.add_here') : t('widgets.places.card.add')}</button>
    <button
        type="button"
        class="wp-add__caret"
        {disabled}
        aria-haspopup="menu"
        aria-label={t('widgets.places.card.add_to', { name })}
        onclick={(event) => {
            event.stopPropagation();
            onCaret(event.currentTarget as HTMLElement);
        }}
    ><Icon name="chevron-down" size={10} /></button>
</span>
