import { mountPanel, unmountPanel } from '../mount';
import IconPicker from './IconPicker.svelte';

export interface IconPickerHostProps {
    value: string | null;
    onChange: (id: string | null) => void;
    onCancel?: () => void;
    autofocus?: boolean;
}

export function mountIconPicker(containerId: string, props: IconPickerHostProps): boolean {
    return mountPanel(containerId, IconPicker, { ...props }) !== null;
}

export function unmountIconPicker(containerId: string): boolean {
    return unmountPanel(containerId);
}
