export enum FeedbackKind {
  FEEDBACK = 'FEEDBACK',
  COMPLAINT = 'COMPLAINT',
  SUGGESTION = 'SUGGESTION'
}

export enum FeedbackStatus {
  SUBMITTED = 'SUBMITTED',
  IN_PROGRESS = 'IN_PROGRESS',
  RESOLVED = 'RESOLVED',
  CLOSED = 'CLOSED'
}

export class FeedbackFollowUp {
  id: string = '';
  author_name: string = '';
  comment: string = '';
  rating: number = 0;
  created_at: string = '';
}

export class FeedbackRecord {
  id: string = '';
  ticket_no: string = '';
  kind: FeedbackKind = FeedbackKind.FEEDBACK;
  title: string = '';
  content: string = '';
  status: FeedbackStatus = FeedbackStatus.SUBMITTED;
  priority: string = '';
  latest_response: string | null = null;
  rating: number | null = null;
  follow_ups: FeedbackFollowUp[] = [];
  created_at: string = '';
  updated_at: string = '';
}

export class FeedbackListResponse {
  items: FeedbackRecord[] = [];
}

export class FaqItem {
  id: string = '';
  category: string = '';
  question: string = '';
  answer: string = '';
  sort_order: number = 0;
}

export class FaqListResponse {
  items: FaqItem[] = [];
}

export enum SupportConversationStatus {
  OPEN = 'OPEN',
  CLOSED = 'CLOSED'
}

export class SupportConversation {
  id: string = '';
  subject: string = '';
  status: SupportConversationStatus = SupportConversationStatus.OPEN;
  provider: string = 'demo_support_bot';
  is_demo: boolean = true;
  last_message_at: string = '';
  created_at: string = '';
}

export class SupportConversationListResponse {
  items: SupportConversation[] = [];
}

export class SupportMessage {
  id: string = '';
  conversation_id: string = '';
  sender_type: string = '';
  sender_name: string = '';
  content: string = '';
  sequence: number = 0;
  provider: string = 'demo_support_bot';
  is_demo: boolean = true;
  created_at: string = '';
}

export class SupportMessageListResponse {
  items: SupportMessage[] = [];
}

export class ServiceWsTicketResponse {
  ticket: string = '';
  expires_at: string = '';
}

export class SupportEventData {
  conversation: SupportConversation = new SupportConversation();
  message: SupportMessage | null = null;
  source: string = 'demo_support_bot';
  is_demo: boolean = true;
}

export class SupportEventEnvelope {
  id: string = '';
  type: string = '';
  occurred_at: string = '';
  data: SupportEventData = new SupportEventData();
}

export class GroupMember {
  user_id: string = '';
  display_name: string = '';
  role: string = '';
  status: string = '';
  note: string = '';
  share_location: boolean = false;
  share_status: boolean = true;
  latitude: number | null = null;
  longitude: number | null = null;
  updated_at: string = '';
}

export class MeetingPoint {
  id: string = '';
  name: string = '';
  node_id: string | null = null;
  note: string = '';
  created_at: string = '';
}

export class TravelGroup {
  id: string = '';
  name: string = '';
  invite_code: string = '';
  revision: number = 0;
  itinerary_id: string | null = null;
  itinerary_revision: number | null = null;
  share_itinerary: boolean = true;
  share_location: boolean = false;
  share_member_status: boolean = true;
  members: GroupMember[] = [];
  meeting_point: MeetingPoint | null = null;
  provider: string = 'demo_group';
  is_demo: boolean = true;
  updated_at: string = '';
}

export class FacilityItem {
  id: string = '';
  kind: string = '';
  name: string = '';
  description: string = '';
  node_id: string | null = null;
  accessible: boolean = false;
  wheelchair_ok: boolean = false;
  stroller_ok: boolean = false;
  open_status: string = '';
  source: string = 'seeded';
  is_demo: boolean = true;
}

export class FacilityListResponse {
  items: FacilityItem[] = [];
}

export class LostAlertResponse {
  id: string = '';
  group_id: string = '';
  status: string = '';
  message: string = '';
  last_seen_node_id: string | null = null;
  provider: string = 'demo_alert';
  is_demo: boolean = true;
  created_at: string = '';
}
