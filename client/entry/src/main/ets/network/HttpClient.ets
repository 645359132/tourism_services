import { connection, http } from '@kit.NetworkKit';
import { AppConfig } from '../config/AppConfig';
import { AuthStore } from '../stores/AuthStore';
import { NetworkQuality, NetworkStore } from '../stores/NetworkStore';
import { ApiErrorInfo, mapApiError } from './ApiError';

export enum ApiMethod {
  GET = 'GET',
  POST = 'POST',
  PUT = 'PUT',
  DELETE = 'DELETE'
}

export class ApiRequest {
  path: string;
  method: ApiMethod;
  body: string;
  requiresAuth: boolean;
  retryCount: number;
  ifNoneMatch: string;

  constructor(path: string, method: ApiMethod, body: string = '', requiresAuth: boolean = true,
    retryCount: number = AppConfig.MAX_RETRY_COUNT, ifNoneMatch: string = '') {
    this.path = path;
    this.method = method;
    this.body = body;
    this.requiresAuth = requiresAuth;
    this.retryCount = retryCount;
    this.ifNoneMatch = ifNoneMatch;
  }
}

export class NetworkResult<T> {
  successful: boolean;
  data: T | null;
  error: ApiErrorInfo | null;
  statusCode: number;
  etag: string;
  notModified: boolean;

  constructor(successful: boolean, data: T | null, error: ApiErrorInfo | null,
    statusCode: number = 0, etag: string = '', notModified: boolean = false) {
    this.successful = successful;
    this.data = data;
    this.error = error;
    this.statusCode = statusCode;
    this.etag = etag;
    this.notModified = notModified;
  }
}

class ResponseHeaderView {
  etag: string = '';
  ETag: string = '';
}

export class HttpClient {
  private authStore: AuthStore = AuthStore.getInstance();
  private networkStore: NetworkStore = NetworkStore.getInstance();

  async request<T>(apiRequest: ApiRequest): Promise<NetworkResult<T>> {
    let hasNetwork: boolean = true;
    try {
      hasNetwork = await connection.hasDefaultNet();
    } catch (error) {
      hasNetwork = this.networkStore.getQuality() !== NetworkQuality.OFFLINE;
    }
    if (!hasNetwork) {
      this.networkStore.markOffline();
      return new NetworkResult<T>(false, null, mapApiError(0, '', true));
    }

    const allowedRetries: number = apiRequest.method === ApiMethod.GET ?
      Math.max(0, Math.min(apiRequest.retryCount, AppConfig.MAX_RETRY_COUNT)) : 0;
    let lastError: ApiErrorInfo = mapApiError(0, '', false);
    for (let attempt: number = 0; attempt <= allowedRetries; attempt++) {
      const result: NetworkResult<T> = await this.executeOnce<T>(apiRequest);
      if (result.successful) {
        return result;
      }
      if (result.error !== null) {
        lastError = result.error;
      }
      if (!lastError.retriable || attempt >= allowedRetries) {
        break;
      }
      await this.delay(250 * (attempt + 1));
    }
    return new NetworkResult<T>(false, null, lastError);
  }

  private async executeOnce<T>(apiRequest: ApiRequest): Promise<NetworkResult<T>> {
    const request: http.HttpRequest = http.createHttp();
    const authorization: string = apiRequest.requiresAuth && this.authStore.getAccessToken().length > 0 ?
      `Bearer ${this.authStore.getAccessToken()}` : '';
    const options: http.HttpRequestOptions = {
      method: this.toHttpMethod(apiRequest.method),
      header: {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': authorization,
        'If-None-Match': apiRequest.ifNoneMatch
      },
      extraData: apiRequest.body,
      expectDataType: http.HttpDataType.STRING,
      connectTimeout: AppConfig.CONNECT_TIMEOUT_MS,
      readTimeout: AppConfig.READ_TIMEOUT_MS
    };
    const startedAt: number = Date.now();
    try {
      const response: http.HttpResponse = await request.request(this.buildUrl(apiRequest.path), options);
      const elapsedMs: number = Date.now() - startedAt;
      if (elapsedMs >= AppConfig.WEAK_NETWORK_THRESHOLD_MS) {
        this.networkStore.markWeak(elapsedMs);
      } else {
        this.networkStore.markOnline(elapsedMs);
      }
      const etag: string = this.readEtag(response.header);
      if (response.responseCode === 304) {
        return new NetworkResult<T>(true, null, null, 304, etag, true);
      }
      if (response.responseCode < 200 || response.responseCode >= 300) {
        return new NetworkResult<T>(false, null,
          mapApiError(response.responseCode, this.resultToString(response.result), false), response.responseCode, etag);
      }
      const payload: string = this.resultToString(response.result);
      const parsed: T | null = payload.length === 0 ? null : JSON.parse(payload) as T;
      return new NetworkResult<T>(true, parsed, null, response.responseCode, etag);
    } catch (error) {
      const message: string = String(error);
      const offline: boolean = message.toLowerCase().includes('network is unavailable') ||
        message.toLowerCase().includes('network unavailable');
      if (offline) {
        this.networkStore.markOffline();
      }
      return new NetworkResult<T>(false, null, mapApiError(0, message, offline));
    } finally {
      request.destroy();
    }
  }

  private buildUrl(path: string): string {
    return path.startsWith('/') ? `${AppConfig.getApiBaseUrl()}${path}` : `${AppConfig.getApiBaseUrl()}/${path}`;
  }

  private toHttpMethod(method: ApiMethod): http.RequestMethod {
    if (method === ApiMethod.POST) {
      return http.RequestMethod.POST;
    }
    if (method === ApiMethod.PUT) {
      return http.RequestMethod.PUT;
    }
    if (method === ApiMethod.DELETE) {
      return http.RequestMethod.DELETE;
    }
    return http.RequestMethod.GET;
  }

  private resultToString(result: string | Object | ArrayBuffer): string {
    return typeof result === 'string' ? result : JSON.stringify(result);
  }

  private readEtag(header: Object): string {
    const value: ResponseHeaderView = header as ResponseHeaderView;
    return value.etag ?? value.ETag ?? '';
  }

  private delay(milliseconds: number): Promise<void> {
    return new Promise<void>((resolve: () => void) => {
      setTimeout(resolve, milliseconds);
    });
  }
}
