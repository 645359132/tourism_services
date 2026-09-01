import {
  Itinerary,
  ItineraryConflictResponse,
  ItineraryGenerateRequest
} from '../../models/GuideModels';
import { ApiMethod, ApiRequest, HttpClient, NetworkResult } from '../HttpClient';

class ConflictCheckPayload {
  walking_buffer_minutes: number;

  constructor(walkingBufferMinutes: number) {
    this.walking_buffer_minutes = walkingBufferMinutes;
  }
}

class ReplanPayload {
  crowd_avoidance: boolean;
  preserve_locked: boolean;
  expected_revision: number;

  constructor(crowdAvoidance: boolean, preserveLocked: boolean, expectedRevision: number) {
    this.crowd_avoidance = crowdAvoidance;
    this.preserve_locked = preserveLocked;
    this.expected_revision = expectedRevision;
  }
}

export class ItineraryService {
  private client: HttpClient = new HttpClient();

  generate(input: ItineraryGenerateRequest): Promise<NetworkResult<Itinerary>> {
    return this.client.request<Itinerary>(new ApiRequest(
      '/itineraries/generate', ApiMethod.POST, JSON.stringify(input), true, 0));
  }

  getItinerary(itineraryId: string): Promise<NetworkResult<Itinerary>> {
    return this.client.request<Itinerary>(new ApiRequest(
      `/itineraries/${encodeURIComponent(itineraryId)}`, ApiMethod.GET));
  }

  checkConflicts(itineraryId: string, walkingBufferMinutes: number): Promise<NetworkResult<ItineraryConflictResponse>> {
    const payload: ConflictCheckPayload = new ConflictCheckPayload(walkingBufferMinutes);
    return this.client.request<ItineraryConflictResponse>(new ApiRequest(
      `/itineraries/${encodeURIComponent(itineraryId)}/conflicts/check`, ApiMethod.POST,
      JSON.stringify(payload), true, 0));
  }

  replan(itineraryId: string, expectedRevision: number): Promise<NetworkResult<Itinerary>> {
    const payload: ReplanPayload = new ReplanPayload(true, true, expectedRevision);
    return this.client.request<Itinerary>(new ApiRequest(
      `/itineraries/${encodeURIComponent(itineraryId)}/replan`, ApiMethod.POST,
      JSON.stringify(payload), true, 0));
  }
}
