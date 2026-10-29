import { getContext, setContext } from 'svelte';

export interface OpenFocus {
  pending: boolean;
}

export const OPEN_FOCUS = Symbol('open-focus');

export function provideOpenFocus(): OpenFocus {
  const ask = $state<OpenFocus>({ pending: false });
  setContext(OPEN_FOCUS, ask);
  return ask;
}

export function useOpenFocus(): OpenFocus | undefined {
  return getContext<OpenFocus | undefined>(OPEN_FOCUS);
}
