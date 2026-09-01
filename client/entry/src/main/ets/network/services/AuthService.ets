import { AuthTokenResponse } from '../../models/AppModels';
import { ApiMethod, ApiRequest, HttpClient, NetworkResult } from '../HttpClient';

class LoginPayload {
  username: string;
  password: string;

  constructor(username: string, password: string) {
    this.username = username;
    this.password = password;
  }
}

class RefreshPayload {
  refresh_token: string;

  constructor(refreshToken: string) {
    this.refresh_token = refreshToken;
  }
}

export class AuthService {
  private client: HttpClient = new HttpClient();

  login(username: string, password: string): Promise<NetworkResult<AuthTokenResponse>> {
    const payload: LoginPayload = new LoginPayload(username, password);
    const request: ApiRequest = new ApiRequest('/auth/login', ApiMethod.POST, JSON.stringify(payload), false, 0);
    return this.client.request<AuthTokenResponse>(request);
  }

  refresh(refreshToken: string): Promise<NetworkResult<AuthTokenResponse>> {
    const payload: RefreshPayload = new RefreshPayload(refreshToken);
    const request: ApiRequest = new ApiRequest('/auth/refresh', ApiMethod.POST, JSON.stringify(payload), false, 0);
    return this.client.request<AuthTokenResponse>(request);
  }
}
