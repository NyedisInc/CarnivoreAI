import { getContext, setContext } from 'svelte';

const INSET_KEY = Symbol('oc-page-inset');

export function provideInset(): void {
    setContext(INSET_KEY, true);
}

export function isInset(): boolean {
    return getContext(INSET_KEY) === true;
}
