
export const HEADER_ACTION_KEYS = {
    components: 'header.components',
    componentsHint: 'header.components_hint',
    pause: 'header.pause',
    pauseHint: 'header.pause_hint',
};

export function headerActionLabels(t) {
    return {
        components: {
            label: t(HEADER_ACTION_KEYS.components),
            hint: t(HEADER_ACTION_KEYS.componentsHint),
        },
        pause: {
            label: t(HEADER_ACTION_KEYS.pause),
            hint: t(HEADER_ACTION_KEYS.pauseHint),
        },
    };
}
