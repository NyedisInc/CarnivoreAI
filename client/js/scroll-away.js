
export const AWAY_THRESHOLD = 16;

export function initialAway() {
    return { away: false, anchor: 0 };
}

export function nextAway(state, reading) {
    const { top, max, rowsH, focusInside } = reading;
    const threshold = reading.threshold ?? AWAY_THRESHOLD;
    if (!(rowsH > 0)) return state.away || state.anchor !== 0 ? { away: false, anchor: 0 } : state;
    if (top < 0 || top > max) return state;
    if (top === 0) return state.away || state.anchor !== 0 ? { away: false, anchor: 0 } : state;
    if (focusInside) return state.away || state.anchor !== top ? { away: false, anchor: top } : state;
    if (state.away) {
        if (state.anchor - top >= threshold) return { away: false, anchor: top };
        return top > state.anchor ? { away: true, anchor: top } : state;
    }
    if (top - state.anchor >= threshold) {
        const roomy = max > rowsH && top >= rowsH;
        return roomy ? { away: true, anchor: top } : { away: false, anchor: state.anchor };
    }
    return top < state.anchor ? { away: false, anchor: top } : state;
}
