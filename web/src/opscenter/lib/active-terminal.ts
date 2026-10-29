import { inputFocus } from './input-focus.svelte';
import { PRIMARY_SLOT } from '../engine/model';
import { sessionForSlot } from '../engine/slot-identity';
import { primarySessionId } from '../api/host';
import { sessions } from '../api';

/* the page terminal */
export function activeTerminalSlot(): string {
    return inputFocus.selected ?? PRIMARY_SLOT;
}

export function activeTerminalSessionId(slot: string = activeTerminalSlot()): string {
    return slot === PRIMARY_SLOT ? primarySessionId() : sessionForSlot(slot, sessions.data);
}
