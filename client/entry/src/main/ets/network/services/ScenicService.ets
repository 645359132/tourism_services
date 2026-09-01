import { ScenicSpot } from '../../models/AppModels';
import { ApiMethod, ApiRequest, HttpClient, NetworkResult } from '../HttpClient';

export class ScenicService {
  private client: HttpClient = new HttpClient();

  listSpots(): Promise<NetworkResult<ScenicSpot[]>> {
    return this.client.request<ScenicSpot[]>(new ApiRequest('/scenic-spots', ApiMethod.GET, '', false));
  }
}
