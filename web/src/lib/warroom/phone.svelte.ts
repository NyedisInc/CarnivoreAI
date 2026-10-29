import { MOBILE_MAX_PX } from '../drawer/pin';

const state = $state({ phone: false });
let watching = false;

function watch(): void {
    if (watching || typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    watching = true;
    const query = window.matchMedia(`(max-width: ${MOBILE_MAX_PX}px)`);
    state.phone = query.matches;
    query.addEventListener('change', (event) => {
        state.phone = event.matches;
    });
}

watch();

export function warroomAvailable(): boolean {
    watch();
    return !state.phone;
}
