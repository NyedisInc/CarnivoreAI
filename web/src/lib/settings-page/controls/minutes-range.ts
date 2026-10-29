import { autoSleep } from '../../auto-sleep/auto-sleep-store.svelte';

const DEFAULT_MIN_IDLE_MINUTES = 5;
const DEFAULT_MAX_IDLE_MINUTES = 10080;

export function minutesRange(): { min: number; max: number } {
    const data = autoSleep.data;
    return {
        min: typeof data?.min_idle_minutes === 'number' ? data.min_idle_minutes : DEFAULT_MIN_IDLE_MINUTES,
        max: typeof data?.max_idle_minutes === 'number' ? data.max_idle_minutes : DEFAULT_MAX_IDLE_MINUTES,
    };
}
