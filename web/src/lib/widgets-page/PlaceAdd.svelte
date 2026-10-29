<!-- could not be read -->
<script lang="ts">
    import { Button, IconButton } from '../base';
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
    <Button
        variant="quiet"
        size="sm"
        data-add="main"
        disabled={disabled || (here && blocked)}
        aria-haspopup={here ? undefined : 'menu'}
        aria-label={here ? t('widgets.places.card.add_here_label', { name }) : t('widgets.places.card.add_label', { name })}
        onclick={(event) => {
            event.stopPropagation();
            onMain(event.currentTarget as HTMLElement);
        }}
    >{here ? t('widgets.places.card.add_here') : t('widgets.places.card.add')}</Button>
    <IconButton
        variant="quiet"
        icon="chevron-down"
        iconSize={10}
        data-add="caret"
        {disabled}
        aria-haspopup="menu"
        label={t('widgets.places.card.add_to', { name })}
        onclick={(event) => {
            event.stopPropagation();
            onCaret(event.currentTarget as HTMLElement);
        }}
    />
</span>
