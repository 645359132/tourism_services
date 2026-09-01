import { TripPlanItem } from '../../models/AppModels';
import { ApiMethod, ApiRequest, HttpClient, NetworkResult } from '../HttpClient';

export class TripService {
  private client: HttpClient = new HttpClient();

  listTrips(): Promise<NetworkResult<TripPlanItem[]>> {
    return this.client.request<TripPlanItem[]>(new ApiRequest('/trips', ApiMethod.GET));
  }

  createTrip(item: TripPlanItem): Promise<NetworkResult<TripPlanItem>> {
    return this.client.request<TripPlanItem>(new ApiRequest('/trips', ApiMethod.POST, JSON.stringify(item)));
  }
}
