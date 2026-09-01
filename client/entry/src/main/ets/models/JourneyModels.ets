export enum OfflineTravelState {
  NO_PACK = 'NO_PACK',
  DOWNLOADING = 'DOWNLOADING',
  READY = 'READY',
  OFFLINE_CACHE = 'OFFLINE_CACHE',
  PENDING_SYNC = 'PENDING_SYNC',
  SYNCING = 'SYNCING',
  FAILED = 'FAILED',
  AUTH_REQUIRED = 'AUTH_REQUIRED'
}

export enum OfflineMutationStatus {
  PENDING = 'PENDING',
  RETRYABLE = 'RETRYABLE',
  TERMINAL = 'TERMINAL'
}

export class JourneyJsonPayload {
}

export class OfflinePack {
  id: string = '';
  version: number = 0;
  name: string = '';
  description: string = '';
  etag: string = '';
  published_at: string = '';
  expires_at: string | null = null;
  asset_count: number = 0;
  total_size_bytes: number = 0;
  manifest_url: string = '';
  provider: string = 'local_offline_pack';
  is_demo: boolean = true;
}

export class OfflineAssetManifest {
  id: string = '';
  asset_key: string = '';
  kind: string = '';
  title: string = '';
  content_hash: string = '';
  encoding: string = 'json';
  size_bytes: number = 0;
  required: boolean = false;
  download_url: string = '';
}

export class OfflineManifest {
  pack_id: string = '';
  version: number = 0;
  etag: string = '';
  assets: OfflineAssetManifest[] = [];
  provider: string = 'local_offline_pack';
  is_demo: boolean = true;
}

export class OfflineAssetContent {
  id: string = '';
  pack_id: string = '';
  asset_key: string = '';
  kind: string = '';
  content_hash: string = '';
  encoding: string = 'json';
  size_bytes: number = 0;
  payload: JourneyJsonPayload = new JourneyJsonPayload();
}

export class CachedOfflineAsset {
  id: string = '';
  asset_key: string = '';
  kind: string = '';
  title: string = '';
  content_hash: string = '';
  size_bytes: number = 0;
  payload_json: string = '';
  payload_fingerprint: string = '';
  cached_at: string = '';
}

export class CachedGuidance {
  emergency_steps: string[] = [];
  guide_sections: string[] = [];
  map_nodes: string[] = [];
  narration_transcripts: string[] = [];
}

export class EmergencyGuidePayload {
  steps: string[] = [];
}

export class TravelGuidePayload {
  sections: string[] = [];
}

export class OfflineMapNodePayload {
  code: string = '';
  name: string = '';
}

export class OfflineMapPayload {
  version: number = 0;
  nodes: OfflineMapNodePayload[] = [];
}

export class OfflineNarrationPayload {
  transcripts: string[] = [];
}

export class AppliedSyncRecord {
  client_mutation_id: string = '';
  entity_type: string = '';
  entity_id: string = '';
  operation: string = '';
  server_cursor: string = '';
  applied_at: string = '';
}

export class LocalSosDraft {
  kind: string = 'OTHER';
  message: string = '';
  node_id: string | null = null;
  latitude: number | null = null;
  longitude: number | null = null;
  idempotency_key: string = '';
  local_status: string = 'LOCAL_ONLY';
  created_at: string = '';
}

export class OfflinePackCache {
  schema_version: number = 2;
  owner_user_id: string = '';
  device_id: string = '';
  pack: OfflinePack = new OfflinePack();
  manifest: OfflineManifest = new OfflineManifest();
  manifest_checksum: string = '';
  assets: CachedOfflineAsset[] = [];
  cached_at: string = '';
}

export class NoteMutationPayload extends JourneyJsonPayload {
  title: string;
  text: string;
  constructor(title: string, text: string) { super(); this.title = title; this.text = text; }
}

export class ItineraryAckPayload extends JourneyJsonPayload {
  revision: number;
  viewed_at: string;
  constructor(revision: number, viewedAt: string) { super(); this.revision = revision; this.viewed_at = viewedAt; }
}

export class EmergencyAckPayload extends JourneyJsonPayload {
  acknowledged: boolean = true;
  bulletin_id: string;
  constructor(bulletinId: string) { super(); this.bulletin_id = bulletinId; }
}

export class OfflineMutation {
  client_mutation_id: string = '';
  client_version: number = 0;
  entity_type: string = 'NOTE';
  entity_id: string = '';
  operation: string = 'UPSERT';
  payload: JourneyJsonPayload = new JourneyJsonPayload();
}

export class OfflineOutboxItem {
  mutation: OfflineMutation = new OfflineMutation();
  status: OfflineMutationStatus = OfflineMutationStatus.PENDING;
  error_message: string = '';
  created_at: string = '';
  last_attempt_at: string = '';
}

export class OfflineOutbox {
  schema_version: number = 1;
  owner_user_id: string = '';
  device_id: string = '';
  items: OfflineOutboxItem[] = [];
  sync_cursor: string | null = null;
  last_client_version: number = 0;
  applied_sync: AppliedSyncRecord[] = [];
  local_sos: LocalSosDraft | null = null;
  updated_at: string = '';
}

export class SyncPushResult {
  client_mutation_id: string = '';
  client_version: number = 0;
  server_cursor: string = '';
  status: string = '';
}

export class SyncPushResponse {
  device_id: string = '';
  accepted: number = 0;
  replayed: number = 0;
  server_cursor: string = '';
  results: SyncPushResult[] = [];
}

export class SyncMutation {
  server_cursor: string = '';
  device_id: string = '';
  client_mutation_id: string = '';
  client_version: number = 0;
  entity_type: string = '';
  entity_id: string = '';
  operation: string = '';
  payload: JourneyJsonPayload = new JourneyJsonPayload();
  created_at: string = '';
}

export class SyncPullResponse {
  device_id: string = '';
  cursor: string = '';
  next_cursor: string = '';
  has_more: boolean = false;
  items: SyncMutation[] = [];
}

export class SyncStatusResponse {
  device_id: string = '';
  cursor: string = '';
  last_client_version: number = 0;
  server_cursor: string = '';
  updated_at: string = '';
}

export class EmergencyResource {
  id: string = '';
  code: string = '';
  kind: string = '';
  title: string = '';
  description: string = '';
  phone: string | null = null;
  node_id: string | null = null;
  instructions: string[] = [];
  priority: number = 0;
  provider: string = 'curated_demo';
  is_demo: boolean = true;
}

export class EmergencyResourceListResponse {
  items: EmergencyResource[] = [];
}

export class EmergencyBulletin {
  id: string = '';
  code: string = '';
  title: string = '';
  content: string = '';
  severity: string = 'INFO';
  starts_at: string = '';
  ends_at: string = '';
  provider: string = 'curated_demo';
  is_demo: boolean = true;
}

export class EmergencyBulletinListResponse {
  items: EmergencyBulletin[] = [];
}

export class SosRecord {
  id: string = '';
  sos_no: string = '';
  kind: string = 'OTHER';
  message: string = '';
  status: string = 'DEMO_RECEIVED';
  node_id: string | null = null;
  latitude: number | null = null;
  longitude: number | null = null;
  provider: string = 'demo_sos';
  is_demo: boolean = true;
  real_dispatch: boolean = false;
  disclaimer: string = '';
  created_at: string = '';
  updated_at: string = '';
}

export class SosListResponse {
  items: SosRecord[] = [];
}

export class PassportStamp {
  id: string = '';
  code: string = '';
  title: string = '';
  description: string = '';
  node_id: string = '';
  points_award: number = 0;
  collected: boolean = false;
  collected_at: string | null = null;
  provider: string = 'demo_checkin';
  is_demo: boolean = true;
}

export class PassportSummary {
  collected_count: number = 0;
  total_count: number = 0;
  points_earned: number = 0;
  point_balance: number = 0;
  stamps: PassportStamp[] = [];
  provider: string = 'demo_checkin';
  is_demo: boolean = true;
}

export class PassportCheckInResponse {
  stamp: PassportStamp = new PassportStamp();
  points_awarded: number = 0;
  point_balance: number = 0;
  provider: string = 'demo_checkin';
  is_demo: boolean = true;
}

export class GreenTask {
  id: string = '';
  code: string = '';
  kind: string = '';
  title: string = '';
  description: string = '';
  points_award: number = 0;
  evidence_hint: string = '';
  completed: boolean = false;
  completed_at: string | null = null;
  provider: string = 'demo_green_verifier';
  is_demo: boolean = true;
}

export class GreenTaskListResponse {
  items: GreenTask[] = [];
  point_balance: number = 0;
}

export class GreenTaskCompletionResponse {
  id: string = '';
  task_id: string = '';
  task_code: string = '';
  points_awarded: number = 0;
  evidence: string = '';
  point_balance: number = 0;
  completed_at: string = '';
  provider: string = 'demo_green_verifier';
  is_demo: boolean = true;
}
