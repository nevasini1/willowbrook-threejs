import { Game3D } from './world3d/Game3D';

const appEl = document.getElementById('app')!;
const game = new Game3D(appEl);
void game.start();
