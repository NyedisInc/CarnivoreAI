export type PluginSlice = Record<string, string | Record<string, string>>;

export interface SliceFailure {
    pluginId: string;
    reason: string;
}

export function pluginSlices(): Array<[string, PluginSlice]> {
    return [];
}

export function registerSlices(
    _slices: Array<[string, PluginSlice]>,
    _also?: (pluginId: string, slice: PluginSlice) => unknown,
): SliceFailure[] {
    return [];
}

export function registerPluginSlices(_also?: (pluginId: string, slice: PluginSlice) => unknown): SliceFailure[] {
    return [];
}
