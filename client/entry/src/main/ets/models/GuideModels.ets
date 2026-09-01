export enum CrowdLevel {
  LOW = 'LOW',
  MEDIUM = 'MEDIUM',
  HIGH = 'HIGH'
}

export enum ItineraryStatus {
  DRAFT = 'DRAFT',
  ACTIVE = 'ACTIVE'
}

export class Attraction {
  id: string = '';
  code: string = '';
  name: string = '';
  category: string = '';
  description: string = '';
  visit_minutes: number = 0;
  crowd_level: CrowdLevel = CrowdLevel.LOW;
  occupancy_bps: number = 0;
  wait_minutes: number = 0;
  tags: string[] = [];
  accessibility: string[] = [];
  node_id: string = '';
  x: number = 0;
  y: number = 0;
  narration_available: boolean = false;
}

export class AttractionListResponse {
  items: Attraction[] = [];
}

export class Narration {
  id: string = '';
  attraction_id: string = '';
  language: string = '';
  title: string = '';
  transcript: string = '';
  audio_url: string = '';
  duration_seconds: number = 0;
  provider_mode: string = 'text_demo';
  is_demo: boolean = true;
}

export class NarrationListResponse {
  items: Narration[] = [];
}

export class GuideMapProvider {
  mode: string = 'schematic';
  is_demo: boolean = true;
  description: string = '';
}

export class GuideMapNode {
  id: string = '';
  code: string = '';
  name: string = '';
  kind: string = '';
  x: number = 0;
  y: number = 0;
  accessibility: string[] = [];
}

export class GuideMapEdge {
  id: string = '';
  from_node_id: string = '';
  to_node_id: string = '';
  distance_m: number = 0;
  walk_minutes: number = 0;
  wheelchair_ok: boolean = false;
  stroller_ok: boolean = false;
  bidirectional: boolean = true;
}

export class GuideMapResponse {
  nodes: GuideMapNode[] = [];
  edges: GuideMapEdge[] = [];
  provider: GuideMapProvider = new GuideMapProvider();
}

export class CrowdItem {
  attraction_id: string = '';
  captured_at: string = '';
  people_count: number = 0;
  occupancy_bps: number = 0;
  level: CrowdLevel = CrowdLevel.LOW;
  wait_minutes: number = 0;
  source: string = 'simulated';
}

export class CrowdResponse {
  items: CrowdItem[] = [];
  sequence: number = 0;
  captured_at: string = '';
  source: string = 'simulated';
  is_demo: boolean = true;
}

export class RoutePlanResponse {
  node_ids: string[] = [];
  distance_m: number = 0;
  walk_minutes: number = 0;
  accessible: boolean = false;
  explanation: string[] = [];
  provider: GuideMapProvider = new GuideMapProvider();
}

export class ItineraryGenerateRequest {
  visit_date: string = '';
  start_time: string = '09:00';
  duration_minutes: number = 360;
  interests: string[] = [];
  companion_type: string = 'family';
  fitness_level: string = 'medium';
  accessible: boolean = false;
}

export class ItineraryItem {
  id: string = '';
  ordinal: number = 0;
  kind: string = '';
  ref_id: string = '';
  title: string = '';
  start_at: string = '';
  end_at: string = '';
  locked: boolean = false;
  crowd_level: CrowdLevel = CrowdLevel.LOW;
  walk_minutes: number = 0;
  explanation: string[] = [];
}

export class Itinerary {
  id: string = '';
  name: string = '';
  visit_date: string = '';
  status: ItineraryStatus = ItineraryStatus.DRAFT;
  source: string = 'rules';
  revision: number = 0;
  total_score: number = 0;
  explanation: string[] = [];
  items: ItineraryItem[] = [];
  is_complete: boolean = true;
  unscheduled_reasons: string[] = [];
}

export class ItineraryConflict {
  code: string = '';
  severity: string = '';
  message: string = '';
  item_ids: string[] = [];
}

export class ItinerarySuggestion {
  action: string = '';
  message: string = '';
  item_id: string = '';
  new_start_at: string = '';
  new_end_at: string = '';
}

export class ItineraryConflictResponse {
  itinerary_id: string = '';
  revision: number = 0;
  feasible: boolean = true;
  conflicts: ItineraryConflict[] = [];
  suggestions: ItinerarySuggestion[] = [];
}

export class CrowdEnvelope {
  id: string = '';
  type: string = '';
  occurred_at: string = '';
  data: CrowdResponse = new CrowdResponse();
}
