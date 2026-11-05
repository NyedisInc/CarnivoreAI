import { phoneView } from '../drawer/phone-view.svelte';

export function warroomAvailable(): boolean {
    return !phoneView();
}
