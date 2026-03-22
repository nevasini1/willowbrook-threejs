import Phaser from 'phaser';

/**
 * BootScene — loads the Tiled tilemap, tileset images, character sprite
 * atlases, and the speech bubble, then starts MainScene.
 */

// All character sprite names (matching PNG filenames in assets/characters/)
const CHARACTER_NAMES = [
  'Abigail_Chen', 'Adam_Smith', 'Arthur_Burton', 'Ayesha_Khan',
  'Carlos_Gomez', 'Carmen_Ortiz', 'Eddy_Lin', 'Francisco_Lopez',
  'Giorgio_Rossi', 'Hailey_Johnson', 'Isabella_Rodriguez', 'Jane_Moreno',
  'Jennifer_Moore', 'John_Lin', 'Klaus_Mueller', 'Latoya_Williams',
  'Maria_Lopez', 'Mei_Lin', 'Rajiv_Patel', 'Ryan_Park',
  'Sam_Moore', 'Tamara_Taylor', 'Tom_Moreno', 'Wolfgang_Schulz',
  'Yuriko_Yamamoto',
];

// Tileset images used by the_ville_jan7.json — key must match the "name" in the JSON
const TILESET_IMAGES: Record<string, string> = {
  'CuteRPG_Field_B': 'assets/the_ville/visuals/map_assets/cute_rpg_word_VXAce/tilesets/CuteRPG_Field_B.png',
  'CuteRPG_Field_C': 'assets/the_ville/visuals/map_assets/cute_rpg_word_VXAce/tilesets/CuteRPG_Field_C.png',
  'CuteRPG_Harbor_C': 'assets/the_ville/visuals/map_assets/cute_rpg_word_VXAce/tilesets/CuteRPG_Harbor_C.png',
  'Room_Builder_32x32': 'assets/the_ville/visuals/map_assets/v1/Room_Builder_32x32.png',
  'CuteRPG_Village_B': 'assets/the_ville/visuals/map_assets/cute_rpg_word_VXAce/tilesets/CuteRPG_Village_B.png',
  'CuteRPG_Forest_B': 'assets/the_ville/visuals/map_assets/cute_rpg_word_VXAce/tilesets/CuteRPG_Forest_B.png',
  'CuteRPG_Desert_C': 'assets/the_ville/visuals/map_assets/cute_rpg_word_VXAce/tilesets/CuteRPG_Desert_C.png',
  'CuteRPG_Mountains_B': 'assets/the_ville/visuals/map_assets/cute_rpg_word_VXAce/tilesets/CuteRPG_Mountains_B.png',
  'CuteRPG_Desert_B': 'assets/the_ville/visuals/map_assets/cute_rpg_word_VXAce/tilesets/CuteRPG_Desert_B.png',
  'CuteRPG_Forest_C': 'assets/the_ville/visuals/map_assets/cute_rpg_word_VXAce/tilesets/CuteRPG_Forest_C.png',
  'interiors_pt1': 'assets/the_ville/visuals/map_assets/v1/interiors_pt1.png',
  'interiors_pt2': 'assets/the_ville/visuals/map_assets/v1/interiors_pt2.png',
  'interiors_pt3': 'assets/the_ville/visuals/map_assets/v1/interiors_pt3.png',
  'interiors_pt4': 'assets/the_ville/visuals/map_assets/v1/interiors_pt4.png',
  'interiors_pt5': 'assets/the_ville/visuals/map_assets/v1/interiors_pt5.png',
  'blocks': 'assets/the_ville/visuals/map_assets/blocks/blocks_1.png',
  'blocks_2': 'assets/the_ville/visuals/map_assets/blocks/blocks_2.png',
  'blocks_3': 'assets/the_ville/visuals/map_assets/blocks/blocks_3.png',
};

export { CHARACTER_NAMES };

export class BootScene extends Phaser.Scene {
  constructor() {
    super({ key: 'BootScene' });
  }

  preload(): void {
    const { width, height } = this.scale;

    // Loading UI
    const title = this.add.text(width / 2, height / 2 - 40, 'Loading assets...', {
      fontSize: '20px', color: '#ffffff',
    }).setOrigin(0.5);

    this.add.rectangle(width / 2, height / 2, 320, 20, 0x333333);
    const barFill = this.add.rectangle(width / 2 - 158, height / 2, 0, 16, 0x4caf50)
      .setOrigin(0, 0.5);

    const statusText = this.add.text(width / 2, height / 2 + 30, '', {
      fontSize: '12px', color: '#aaaaaa',
    }).setOrigin(0.5);

    // Progress callback
    this.load.on('progress', (value: number) => {
      barFill.width = 316 * value;
      statusText.setText(`${Math.floor(value * 100)}%`);
    });

    this.load.on('complete', () => {
      title.setText('Assets loaded!');
      statusText.setText('Starting...');
    });

    // Load the tilemap JSON
    this.load.tilemapTiledJSON('the_ville', 'assets/the_ville/visuals/the_ville_jan7.json');

    // Load all tileset images
    for (const [key, path] of Object.entries(TILESET_IMAGES)) {
      this.load.image(key, path);
    }

    // Load character sprite atlases
    for (const name of CHARACTER_NAMES) {
      this.load.atlas(
        name,
        `assets/characters/${name}.png`,
        'assets/characters/atlas.json'
      );
    }

    // Load speech bubble
    this.load.image('speech_bubble', 'assets/speech_bubble/v3.png');
  }

  create(): void {
    this.scene.start('MainScene');
  }
}
