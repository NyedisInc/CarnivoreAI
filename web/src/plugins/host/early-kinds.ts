import { registerPluginKind } from '../../opscenter/engine/plugin-kinds';
import type { PluginKind, SlotId } from '../../opscenter/engine/types';
import { EARLY_KINDS } from '../early';

for (const { kind, meta } of EARLY_KINDS) registerPluginKind(kind as PluginKind, { ...meta, id: kind as SlotId });
