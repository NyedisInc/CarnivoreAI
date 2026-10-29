import { getContext, setContext } from 'svelte';

export interface RadioGroupState {
    readonly name: string;
    readonly value: string;
    readonly disabled: boolean;
    select(value: string): void;
}

const KEY = Symbol('oc-radio-group');

export function provideRadioGroup(state: RadioGroupState): void {
    setContext(KEY, state);
}

export function useRadioGroup(): RadioGroupState | undefined {
    return getContext<RadioGroupState | undefined>(KEY);
}
