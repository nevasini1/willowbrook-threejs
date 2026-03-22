/**
 * Fallback agent data for when the backend is offline.
 * Sprite keys match CHARACTER_NAMES loaded in BootScene.
 * Positions from generative_agents canonical spawn data (environment/0.json).
 */
import { AgentState } from './ApiClient';

export const FALLBACK_AGENTS: AgentState[] = [
  {
    id: 'agent_sam',
    name: 'Sam Johnson',
    location_id: 'house_01_kitchen',
    current_action: 'Making morning coffee',
    x: 30, y: 60,
    sprite_key: 'character_1',
    description: 'Sam Johnson is a 28-year-old aspiring chef who lives in a cozy house on the west side of Willowbrook.',
    daily_plan: null,
    current_plan_step: 0,
    day_number: 1,
    mood: 'neutral',
  },
  {
    id: 'agent_maya',
    name: 'Maya Chen',
    location_id: 'town_square',
    current_action: 'Sitting on the bench reading a book',
    x: 67, y: 33,
    sprite_key: 'character_2',
    description: 'Maya Chen is a 32-year-old librarian who has lived in Willowbrook her entire life.',
    daily_plan: null,
    current_plan_step: 0,
    day_number: 1,
    mood: 'neutral',
  },
];
