import { KINDS, type NotifyKind } from '../../notify-card/contract.gen';
import type { Sample } from './logic';

interface Fixture { kind: NotifyKind; payload: { acts: [string, string][]; body: string; title?: string; sub?: string; lv?: string }; card: Sample['card'] }

const files = import.meta.glob<Fixture>(
    '../../../../../tests/fixtures/notify_cards/{yesno,choice,permission,file,link,image,video,finished,died,update,appupdate,swarm,crosstalk,signin,notice}.json',
    { eager: true, import: 'default' },
);

export const SAMPLES: Readonly<Record<string, Sample>> = Object.fromEntries(
    KINDS.flatMap((kind) => {
        const f = Object.entries(files).find(([path]) => path.endsWith(`/${kind}.json`))?.[1];
        return f ? [[kind, { kind, card: f.card, acts: f.payload.acts, body: f.payload.body, title: f.payload.title ?? '', sub: f.payload.sub ?? '', lv: f.payload.lv ?? '' } satisfies Sample]] : [];
    }),
);
