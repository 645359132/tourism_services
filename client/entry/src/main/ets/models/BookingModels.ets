export enum ExperienceKind {
  RIDE = 'RIDE',
  SHOW = 'SHOW'
}

export enum SessionStatus {
  OPEN = 'OPEN',
  CLOSED = 'CLOSED',
  CANCELLED = 'CANCELLED'
}

export enum ReservationKind {
  EXPERIENCE = 'EXPERIENCE',
  STAY = 'STAY',
  DINING = 'DINING',
  BUNDLE = 'BUNDLE'
}

export enum ReservationStatus {
  HELD = 'HELD',
  CONFIRMED = 'CONFIRMED',
  COMPLETED = 'COMPLETED',
  CANCELLED = 'CANCELLED',
  EXPIRED = 'EXPIRED',
  NO_SHOW = 'NO_SHOW'
}

export enum QueueStatus {
  WAITING = 'WAITING',
  CALLED = 'CALLED',
  SERVING = 'SERVING',
  COMPLETED = 'COMPLETED',
  LEFT = 'LEFT',
  EXPIRED = 'EXPIRED'
}

export enum FastPassStatus {
  ACTIVE = 'ACTIVE',
  USED = 'USED',
  CANCELLED = 'CANCELLED',
  EXPIRED = 'EXPIRED'
}

export enum VenueKind {
  HOTEL = 'HOTEL',
  HOMESTAY = 'HOMESTAY',
  RESTAURANT = 'RESTAURANT'
}

export enum OfferKind {
  ROOM = 'ROOM',
  MEAL = 'MEAL',
  BUNDLE = 'BUNDLE'
}

export class Experience {
  id: string = '';
  code: string = '';
  kind: ExperienceKind = ExperienceKind.RIDE;
  name: string = '';
  description: string = '';
  node_id: string = '';
  duration_minutes: number = 0;
  min_height_cm: number = 0;
  fastpass_allowed: boolean = false;
  fastpass_price_cents: number = 0;
  accessibility: string[] = [];
  wait_minutes: number = 0;
}

export class ExperienceListResponse {
  items: Experience[] = [];
}

export class ExperienceSession {
  id: string = '';
  experience_id: string = '';
  experience_name: string = '';
  starts_at: string = '';
  ends_at: string = '';
  capacity: number = 0;
  remaining: number = 0;
  status: SessionStatus = SessionStatus.OPEN;
}

export class ExperienceSessionListResponse {
  items: ExperienceSession[] = [];
}

export class ReservationAllocation {
  bucket_id: string = '';
  business_date: string = '';
  starts_at: string = '';
  ends_at: string = '';
  quantity: number = 0;
}

export class Reservation {
  id: string = '';
  booking_no: string = '';
  kind: ReservationKind = ReservationKind.EXPERIENCE;
  resource_type: string = '';
  resource_id: string = '';
  resource_name: string = '';
  starts_at: string = '';
  ends_at: string = '';
  party_size: number = 0;
  quantity: number = 0;
  total_cents: number = 0;
  status: ReservationStatus = ReservationStatus.HELD;
  provider: string = 'demo';
  is_demo: boolean = true;
  allocations: ReservationAllocation[] = [];
}

export class ReservationListResponse {
  items: Reservation[] = [];
}

export class NearbyRecommendation {
  kind: string = '';
  ref_id: string = '';
  name: string = '';
  reason: string = '';
  walk_minutes: number = 0;
  crowd_level: string = '';
}

export class FastPass {
  id: string = '';
  code: string = '';
  experience_id: string = '';
  experience_name: string = '';
  price_cents: number = 0;
  status: FastPassStatus = FastPassStatus.ACTIVE;
  valid_from: string = '';
  valid_to: string = '';
  provider: string = 'demo';
  is_demo: boolean = true;
}

export class QueueEntry {
  id: string = '';
  queue_no: string = '';
  experience_id: string = '';
  experience_name: string = '';
  status: QueueStatus = QueueStatus.WAITING;
  party_size: number = 0;
  estimated_wait_minutes: number = 0;
  sequence: number = 0;
  joined_at: string = '';
  called_at: string | null = null;
  itinerary_id: string | null = null;
  itinerary_revision: number | null = null;
  nearby_recommendations: NearbyRecommendation[] = [];
  fast_pass: FastPass | null = null;
}

export class WsTicketResponse {
  ticket: string = '';
  expires_at: string = '';
}

export class QueueEventData {
  queue: QueueEntry = new QueueEntry();
  source: string = 'simulated';
  is_demo: boolean = true;
  recommendation: NearbyRecommendation | null = null;
  itinerary_id: string | null = null;
  itinerary_revision: number | null = null;
}

export class QueueEventEnvelope {
  id: string = '';
  type: string = '';
  occurred_at: string = '';
  data: QueueEventData = new QueueEventData();
}

export class Venue {
  id: string = '';
  code: string = '';
  kind: VenueKind = VenueKind.HOTEL;
  name: string = '';
  description: string = '';
  address: string = '';
  node_id: string = '';
  accessibility: string[] = [];
  amenities: string[] = [];
  rating: number = 0;
  is_demo: boolean = true;
}

export class VenueListResponse {
  items: Venue[] = [];
}

export class BundleComponent {
  kind: string = '';
  ref_id: string = '';
  name: string = '';
  quantity: number = 0;
  offset_minutes: number = 0;
}

export class HospitalityOffer {
  id: string = '';
  venue_id: string = '';
  code: string = '';
  kind: OfferKind = OfferKind.ROOM;
  name: string = '';
  description: string = '';
  capacity: number = 0;
  max_party_size: number = 0;
  base_price_cents: number = 0;
  provider: string = 'demo';
  bundle_components: BundleComponent[] = [];
  attributes: string[] = [];
  is_demo: boolean = true;
}

export class HospitalityOfferListResponse {
  items: HospitalityOffer[] = [];
}

export class AvailabilityBucket {
  bucket_id: string = '';
  resource_type: string = '';
  resource_id: string = '';
  business_date: string = '';
  start_at: string = '';
  end_at: string = '';
  remaining: number = 0;
  unit_price_cents: number = 0;
}

export class AvailabilityResponse {
  items: AvailabilityBucket[] = [];
}

export class ReviewResponse {
  id: string = '';
  reservation_id: string = '';
  target_type: string = '';
  target_id: string = '';
  rating: number = 0;
  content: string = '';
  status: string = '';
  created_at: string = '';
}
