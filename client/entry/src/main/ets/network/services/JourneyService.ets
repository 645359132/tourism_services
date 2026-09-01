import {
  EmergencyBulletinListResponse,
  EmergencyResourceListResponse,
  GreenTaskCompletionResponse,
  GreenTaskListResponse,
  OfflineAssetContent,
  OfflineManifest,
  OfflineMutation,
  OfflinePack,
  PassportCheckInResponse,
  PassportSummary,
  SosListResponse,
  SosRecord,
  SyncPullResponse,
  SyncPushResponse,
  SyncStatusResponse
} from '../../models/JourneyModels';
import { ApiMethod, ApiRequest, HttpClient, NetworkResult } from '../HttpClient';

export class JourneyRoutePolicy {
  static requiresAuth(path: string): boolean {
    return path.startsWith('/offline/') || path.startsWith('/emergency/') || path.startsWith('/passport') ||
      path.startsWith('/green/');
  }
}

class SyncPushPayload {
  device_id: string;
  base_cursor: string | null;
  mutations: OfflineMutation[];
  constructor(deviceId: string, cursor: string | null, mutations: OfflineMutation[]) {
    this.device_id = deviceId; this.base_cursor = cursor; this.mutations = mutations;
  }
}

class SosPayload {
  kind: string; message: string; node_id: string | null; latitude: number | null; longitude: number | null;
  idempotency_key: string;
  constructor(kind: string, message: string, nodeId: string | null, latitude: number | null,
    longitude: number | null, key: string) {
    this.kind = kind; this.message = message; this.node_id = nodeId; this.latitude = latitude;
    this.longitude = longitude; this.idempotency_key = key;
  }
}

class PassportCheckInPayload {
  stamp_code: string; idempotency_key: string;
  constructor(code: string, key: string) { this.stamp_code = code; this.idempotency_key = key; }
}

class GreenTaskPayload {
  evidence: string; idempotency_key: string;
  constructor(evidence: string, key: string) { this.evidence = evidence; this.idempotency_key = key; }
}

export class JourneyService {
  private client: HttpClient = new HttpClient();

  latestPack(): Promise<NetworkResult<OfflinePack>> {
    const path: string = '/offline/packs/latest';
    return this.client.request<OfflinePack>(new ApiRequest(
      path, ApiMethod.GET, '', JourneyRoutePolicy.requiresAuth(path)));
  }

  getManifest(packId: string, etag: string = ''): Promise<NetworkResult<OfflineManifest>> {
    return this.client.request<OfflineManifest>(new ApiRequest(
      `/offline/packs/${encodeURIComponent(packId)}/manifest`, ApiMethod.GET, '', true, 2, etag));
  }

  getAsset(packId: string, assetId: string): Promise<NetworkResult<OfflineAssetContent>> {
    return this.client.request<OfflineAssetContent>(new ApiRequest(
      `/offline/packs/${encodeURIComponent(packId)}/assets/${encodeURIComponent(assetId)}`,
      ApiMethod.GET, '', true));
  }

  getSyncStatus(deviceId: string): Promise<NetworkResult<SyncStatusResponse>> {
    return this.client.request<SyncStatusResponse>(new ApiRequest(
      `/offline/sync/status?device_id=${encodeURIComponent(deviceId)}`, ApiMethod.GET));
  }

  pushSync(deviceId: string, cursor: string | null,
    mutations: OfflineMutation[]): Promise<NetworkResult<SyncPushResponse>> {
    return this.client.request<SyncPushResponse>(new ApiRequest('/offline/sync/push', ApiMethod.POST,
      JSON.stringify(new SyncPushPayload(deviceId, cursor, mutations)), true, 0));
  }

  pullSync(deviceId: string, cursor: string | null, limit: number = 20): Promise<NetworkResult<SyncPullResponse>> {
    const cursorQuery: string = cursor === null || cursor.length === 0 ? '' :
      `&cursor=${encodeURIComponent(cursor)}`;
    return this.client.request<SyncPullResponse>(new ApiRequest(
      `/offline/sync/pull?device_id=${encodeURIComponent(deviceId)}${cursorQuery}&limit=${limit}`,
      ApiMethod.GET));
  }

  listEmergencyResources(): Promise<NetworkResult<EmergencyResourceListResponse>> {
    return this.client.request<EmergencyResourceListResponse>(new ApiRequest(
      '/emergency/resources', ApiMethod.GET, '', true));
  }

  listEmergencyBulletins(): Promise<NetworkResult<EmergencyBulletinListResponse>> {
    return this.client.request<EmergencyBulletinListResponse>(new ApiRequest(
      '/emergency/bulletins', ApiMethod.GET, '', true));
  }

  listSos(): Promise<NetworkResult<SosListResponse>> {
    return this.client.request<SosListResponse>(new ApiRequest('/emergency/sos', ApiMethod.GET));
  }

  createSos(kind: string, message: string, nodeId: string | null, latitude: number | null,
    longitude: number | null, key: string): Promise<NetworkResult<SosRecord>> {
    return this.client.request<SosRecord>(new ApiRequest('/emergency/sos', ApiMethod.POST,
      JSON.stringify(new SosPayload(kind, message, nodeId, latitude, longitude, key)), true, 0));
  }

  getSos(id: string): Promise<NetworkResult<SosRecord>> {
    return this.client.request<SosRecord>(new ApiRequest(`/emergency/sos/${encodeURIComponent(id)}`, ApiMethod.GET));
  }

  getPassport(): Promise<NetworkResult<PassportSummary>> {
    return this.client.request<PassportSummary>(new ApiRequest('/passport', ApiMethod.GET));
  }

  checkIn(stampCode: string, key: string): Promise<NetworkResult<PassportCheckInResponse>> {
    return this.client.request<PassportCheckInResponse>(new ApiRequest('/passport/check-ins', ApiMethod.POST,
      JSON.stringify(new PassportCheckInPayload(stampCode, key)), true, 0));
  }

  listGreenTasks(): Promise<NetworkResult<GreenTaskListResponse>> {
    return this.client.request<GreenTaskListResponse>(new ApiRequest('/green/tasks', ApiMethod.GET));
  }

  completeGreenTask(taskId: string, evidence: string,
    key: string): Promise<NetworkResult<GreenTaskCompletionResponse>> {
    return this.client.request<GreenTaskCompletionResponse>(new ApiRequest(
      `/green/tasks/${encodeURIComponent(taskId)}/complete`, ApiMethod.POST,
      JSON.stringify(new GreenTaskPayload(evidence, key)), true, 0));
  }
}
