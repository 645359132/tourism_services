import {
  AppliedSyncRecord,
  CachedOfflineAsset,
  CachedGuidance,
  EmergencyGuidePayload,
  OfflineMapNodePayload,
  OfflineMapPayload,
  OfflineNarrationPayload,
  OfflineAssetContent,
  OfflineAssetManifest,
  OfflineMutation,
  OfflineMutationStatus,
  OfflineOutbox,
  OfflineOutboxItem,
  OfflinePackCache,
  OfflineTravelState,
  SyncPushResult,
  TravelGuidePayload
} from '../models/JourneyModels';
import { deterministicPayloadFingerprint } from '../models/PersistenceModels';

export enum SyncFailureDisposition {
  RETRYABLE = 'RETRYABLE',
  AUTH_REQUIRED = 'AUTH_REQUIRED',
  TERMINAL = 'TERMINAL'
}

export class JourneyRuleResult {
  valid: boolean;
  message: string;
  constructor(valid: boolean, message: string) { this.valid = valid; this.message = message; }
}

export function offlineStateLabel(state: OfflineTravelState): string {
  if (state === OfflineTravelState.NO_PACK) { return '尚未下载'; }
  if (state === OfflineTravelState.DOWNLOADING) { return '下载中'; }
  if (state === OfflineTravelState.READY) { return '离线包就绪'; }
  if (state === OfflineTravelState.OFFLINE_CACHE) { return '正在使用离线缓存'; }
  if (state === OfflineTravelState.PENDING_SYNC) { return '有待同步操作'; }
  if (state === OfflineTravelState.SYNCING) { return '同步中'; }
  if (state === OfflineTravelState.AUTH_REQUIRED) { return '需要重新登录'; }
  return '操作失败';
}

export function manifestFingerprint(packId: string, version: number, etag: string,
  assets: OfflineAssetManifest[]): string {
  let value: string = `${packId}:${version}:${etag}`;
  for (let index: number = 0; index < assets.length; index++) {
    value += `|${assets[index].id}:${assets[index].asset_key}:${assets[index].content_hash}:` +
      `${assets[index].size_bytes}`;
  }
  return value;
}

export function isOfflineCacheValid(cache: OfflinePackCache | null, userId: string): boolean {
  if (cache === null || cache.schema_version !== 2 || cache.owner_user_id !== userId ||
    cache.pack.id.length === 0 || cache.manifest.pack_id !== cache.pack.id ||
    cache.manifest.version !== cache.pack.version || cache.pack.asset_count !== cache.manifest.assets.length ||
    cache.assets.length !== cache.manifest.assets.length) {
    return false;
  }
  if (cache.pack.expires_at !== null && Date.parse(cache.pack.expires_at) <= Date.now()) { return false; }
  const fingerprint: string = manifestFingerprint(
    cache.manifest.pack_id, cache.manifest.version, cache.manifest.etag, cache.manifest.assets);
  if (fingerprint !== cache.manifest_checksum) {
    return false;
  }
  for (let manifestIndex: number = 0; manifestIndex < cache.manifest.assets.length; manifestIndex++) {
    const expected: OfflineAssetManifest = cache.manifest.assets[manifestIndex];
    let found: boolean = false;
    for (let cacheIndex: number = 0; cacheIndex < cache.assets.length; cacheIndex++) {
      const value: CachedOfflineAsset = cache.assets[cacheIndex];
      if (value.id === expected.id && value.content_hash === expected.content_hash &&
        value.size_bytes === expected.size_bytes && value.payload_json.length > 0 &&
        value.payload_fingerprint === deterministicPayloadFingerprint(value.payload_json)) {
        found = true;
      }
    }
    if (!found) {
      return false;
    }
  }
  return true;
}

export function shouldUseCachedManifest(notModified: boolean, cacheValid: boolean): boolean {
  return notModified && cacheValid;
}

export function assetMatchesManifest(expected: OfflineAssetManifest, actual: OfflineAssetContent): boolean {
  return expected.id === actual.id && expected.asset_key === actual.asset_key &&
    expected.content_hash.length === 64 && expected.content_hash === actual.content_hash &&
    expected.size_bytes === actual.size_bytes && actual.encoding === 'json';
}

export function isSafeOfflineMutation(value: OfflineMutation): boolean {
  const knownType: boolean = value.entity_type === 'NOTE' || value.entity_type === 'ITINERARY_ACK' ||
    value.entity_type === 'EMERGENCY_ACK';
  const knownOperation: boolean = value.operation === 'UPSERT' || value.operation === 'DELETE';
  return value.client_mutation_id.length >= 8 && value.client_version >= 1 && knownType &&
    value.entity_id.length > 0 && knownOperation;
}

export function classifySyncFailure(statusCode: number): SyncFailureDisposition {
  if (statusCode === 0 || statusCode >= 500) {
    return SyncFailureDisposition.RETRYABLE;
  }
  if (statusCode === 401) {
    return SyncFailureDisposition.AUTH_REQUIRED;
  }
  return SyncFailureDisposition.TERMINAL;
}

export function markOutboxFailure(outbox: OfflineOutbox, statusCode: number, message: string): OfflineOutbox {
  const disposition: SyncFailureDisposition = classifySyncFailure(statusCode);
  const updated: OfflineOutbox = outbox;
  for (let index: number = 0; index < updated.items.length; index++) {
    if (updated.items[index].status === OfflineMutationStatus.TERMINAL) {
      continue;
    }
    updated.items[index].status = disposition === SyncFailureDisposition.RETRYABLE ?
      OfflineMutationStatus.RETRYABLE : OfflineMutationStatus.TERMINAL;
    updated.items[index].error_message = message;
    updated.items[index].last_attempt_at = new Date().toISOString();
  }
  updated.updated_at = new Date().toISOString();
  return updated;
}

export function removeAppliedOutboxItems(outbox: OfflineOutbox, results: SyncPushResult[]): OfflineOutbox {
  const kept: OfflineOutboxItem[] = [];
  for (let itemIndex: number = 0; itemIndex < outbox.items.length; itemIndex++) {
    let applied: boolean = false;
    for (let resultIndex: number = 0; resultIndex < results.length; resultIndex++) {
      if (outbox.items[itemIndex].mutation.client_mutation_id === results[resultIndex].client_mutation_id &&
        (results[resultIndex].status === 'APPLIED' || results[resultIndex].status === 'REPLAYED')) {
        applied = true;
      }
    }
    if (!applied) {
      kept.push(outbox.items[itemIndex]);
    }
  }
  outbox.items = kept;
  outbox.updated_at = new Date().toISOString();
  return outbox;
}

export function mergeAppliedSyncRecords(existing: AppliedSyncRecord[], incoming: AppliedSyncRecord[]): AppliedSyncRecord[] {
  const merged: AppliedSyncRecord[] = existing.slice();
  for (let incomingIndex: number = 0; incomingIndex < incoming.length; incomingIndex++) {
    let found: boolean = false;
    for (let existingIndex: number = 0; existingIndex < merged.length; existingIndex++) {
      if (merged[existingIndex].server_cursor === incoming[incomingIndex].server_cursor ||
        (merged[existingIndex].client_mutation_id === incoming[incomingIndex].client_mutation_id &&
          merged[existingIndex].server_cursor === incoming[incomingIndex].server_cursor)) {
        found = true;
      }
    }
    if (!found) { merged.push(incoming[incomingIndex]); }
  }
  return merged;
}

export function extractCachedGuidance(assets: CachedOfflineAsset[]): CachedGuidance {
  const guidance: CachedGuidance = new CachedGuidance();
  for (let index: number = 0; index < assets.length; index++) {
    try {
      if (assets[index].kind === 'EMERGENCY') {
        const payload: EmergencyGuidePayload = JSON.parse(assets[index].payload_json) as EmergencyGuidePayload;
        guidance.emergency_steps = (payload.steps ?? []).slice();
      } else if (assets[index].kind === 'GUIDE') {
        const payload: TravelGuidePayload = JSON.parse(assets[index].payload_json) as TravelGuidePayload;
        guidance.guide_sections = (payload.sections ?? []).slice();
      } else if (assets[index].kind === 'MAP') {
        const payload: OfflineMapPayload = JSON.parse(assets[index].payload_json) as OfflineMapPayload;
        const nodes: string[] = [];
        const source: OfflineMapNodePayload[] = payload.nodes ?? [];
        for (let nodeIndex: number = 0; nodeIndex < source.length; nodeIndex++) {
          nodes.push(`${source[nodeIndex].code} · ${source[nodeIndex].name}`);
        }
        guidance.map_nodes = nodes;
      } else if (assets[index].kind === 'NARRATION') {
        const payload: OfflineNarrationPayload = JSON.parse(assets[index].payload_json) as OfflineNarrationPayload;
        guidance.narration_transcripts = (payload.transcripts ?? []).slice();
      }
    } catch (error) {
    }
  }
  return guidance;
}

export function validateSos(kind: string, message: string, latitude: number | null,
  longitude: number | null): JourneyRuleResult {
  const knownKind: boolean = kind === 'MEDICAL' || kind === 'LOST' || kind === 'SAFETY' || kind === 'OTHER';
  if (!knownKind || message.trim().length < 2 || message.trim().length > 1000) {
    return new JourneyRuleResult(false, '请选择求助类型并填写 2 至 1000 字说明');
  }
  if ((latitude === null) !== (longitude === null)) {
    return new JourneyRuleResult(false, '纬度与经度必须同时提供');
  }
  if (latitude !== null && (latitude < -90 || latitude > 90 || longitude === null ||
    longitude < -180 || longitude > 180)) {
    return new JourneyRuleResult(false, '请输入有效经纬度');
  }
  return new JourneyRuleResult(true, '');
}

export function validateGreenEvidence(value: string): JourneyRuleResult {
  if (value.trim().length < 2 || value.trim().length > 500) {
    return new JourneyRuleResult(false, '任务凭证说明应为 2 至 500 个字符');
  }
  return new JourneyRuleResult(true, '');
}
