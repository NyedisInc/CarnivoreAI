import { isMobile } from './pin';

export const phoneFlag = $state({ value: isMobile() });

function look(): void {
    const now = isMobile();
    if (phoneFlag.value !== now) phoneFlag.value = now;
}

if (typeof window !== 'undefined') window.addEventListener('resize', look);
