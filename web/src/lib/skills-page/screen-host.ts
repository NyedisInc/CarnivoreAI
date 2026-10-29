import { openCatalogScreen } from '../catalog/screen-host';
import { closeWarezScreen } from '../catalog/warez-host';

export const openSkillsManagerScreen = (): boolean => openCatalogScreen({ tab: 'installed' });

export const closeSkillsManagerScreen = (): boolean => closeWarezScreen();
