import { isFragmentTarget } from './guide-parse';

export function followGuideTarget(target: string, win: Window = window): boolean {
    if (!isFragmentTarget(target)) return false;
    if (win.location.hash === target) win.dispatchEvent(new HashChangeEvent('hashchange'));
    else win.location.hash = target;
    return true;
}
