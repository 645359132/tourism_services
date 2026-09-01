import {
  Attraction,
  AttractionListResponse,
  CrowdResponse,
  GuideMapResponse,
  NarrationListResponse,
  RoutePlanResponse
} from '../../models/GuideModels';
import { ApiMethod, ApiRequest, HttpClient, NetworkResult } from '../HttpClient';

class RoutePlanPayload {
  from_node_id: string;
  to_node_id: string;
  wheelchair: boolean;
  stroller: boolean;

  constructor(fromNodeId: string, toNodeId: string, wheelchair: boolean, stroller: boolean) {
    this.from_node_id = fromNodeId;
    this.to_node_id = toNodeId;
    this.wheelchair = wheelchair;
    this.stroller = stroller;
  }
}

export class GuideService {
  private client: HttpClient = new HttpClient();

  listAttractions(): Promise<NetworkResult<AttractionListResponse>> {
    return this.client.request<AttractionListResponse>(
      new ApiRequest('/guide/attractions', ApiMethod.GET, '', false));
  }

  getAttraction(attractionId: string): Promise<NetworkResult<Attraction>> {
    return this.client.request<Attraction>(new ApiRequest(
      `/guide/attractions/${encodeURIComponent(attractionId)}`, ApiMethod.GET, '', false));
  }

  listNarrations(attractionId: string): Promise<NetworkResult<NarrationListResponse>> {
    return this.client.request<NarrationListResponse>(new ApiRequest(
      `/guide/attractions/${encodeURIComponent(attractionId)}/narrations`, ApiMethod.GET, '', false));
  }

  getMap(): Promise<NetworkResult<GuideMapResponse>> {
    return this.client.request<GuideMapResponse>(new ApiRequest('/guide/map', ApiMethod.GET, '', false));
  }

  getCrowd(): Promise<NetworkResult<CrowdResponse>> {
    return this.client.request<CrowdResponse>(new ApiRequest('/guide/crowd', ApiMethod.GET, '', false));
  }

  planRoute(fromNodeId: string, toNodeId: string, wheelchair: boolean,
    stroller: boolean): Promise<NetworkResult<RoutePlanResponse>> {
    const payload: RoutePlanPayload = new RoutePlanPayload(fromNodeId, toNodeId, wheelchair, stroller);
    return this.client.request<RoutePlanResponse>(new ApiRequest(
      '/guide/routes/plan', ApiMethod.POST, JSON.stringify(payload), false, 0));
  }
}
