import './public.css';
import { startPage } from './start';

const target = document.getElementById('board');
if (target) startPage(window, target);
