
export const KEYBOARD_FAMILIES = Object.freeze(['mac', 'other']);

export const GESTURES = Object.freeze([
    'middle', 'right', 'double', 'shift+click', 'alt+click', 'cmd+click', 'wheel', 'tap',
]);

export const REBINDABLE_GESTURES = Object.freeze(['middle']);

export function isGestureRebindable(gesture) {
    return REBINDABLE_GESTURES.includes(gesture);
}

export function keyboardFamily(platform) {
    return /mac|iphone|ipad/i.test(String(platform ?? '')) ? 'mac' : 'other';
}
