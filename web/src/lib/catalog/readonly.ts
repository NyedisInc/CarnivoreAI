/*  hidden  */
import { getContext, setContext } from 'svelte';

const KEY = Symbol('catalog-readonly');

export function provideReadonly(on: boolean): void {
    setContext(KEY, on);
}

export function isReadonly(): boolean {
    return getContext<boolean | undefined>(KEY) === true;
}
