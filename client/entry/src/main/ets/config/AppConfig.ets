export class AppConfig {
  private static apiBaseUrl: string = 'http://10.0.2.2:8000/api/v1';

  static readonly CONNECT_TIMEOUT_MS: number = 6000;
  static readonly READ_TIMEOUT_MS: number = 10000;
  static readonly MAX_RETRY_COUNT: number = 2;
  static readonly WEAK_NETWORK_THRESHOLD_MS: number = 1800;

  static getApiBaseUrl(): string {
    return AppConfig.apiBaseUrl;
  }

  static getCrowdWebSocketUrl(): string {
    const baseUrl: string = AppConfig.apiBaseUrl;
    if (baseUrl.startsWith('https://')) {
      return `wss://${baseUrl.substring(8)}/guide/ws/crowd`;
    }
    return `ws://${baseUrl.substring(7)}/guide/ws/crowd`;
  }

  static getQueueWebSocketUrl(queueId: string, ticket: string): string {
    const baseUrl: string = AppConfig.apiBaseUrl;
    const socketBase: string = baseUrl.startsWith('https://') ? `wss://${baseUrl.substring(8)}` :
      `ws://${baseUrl.substring(7)}`;
    return `${socketBase}/ws/queues/${encodeURIComponent(queueId)}?ticket=${encodeURIComponent(ticket)}`;
  }

  static getSupportWebSocketUrl(conversationId: string, ticket: string): string {
    const baseUrl: string = AppConfig.apiBaseUrl;
    const socketBase: string = baseUrl.startsWith('https://') ? `wss://${baseUrl.substring(8)}` :
      `ws://${baseUrl.substring(7)}`;
    return `${socketBase}/ws/support/${encodeURIComponent(conversationId)}?ticket=${encodeURIComponent(ticket)}`;
  }

  static setApiBaseUrl(value: string): boolean {
    let normalized: string = value.trim();
    if (!normalized.startsWith('http://') && !normalized.startsWith('https://')) {
      return false;
    }
    while (normalized.endsWith('/')) {
      normalized = normalized.substring(0, normalized.length - 1);
    }
    if (normalized.length < 10) {
      return false;
    }
    AppConfig.apiBaseUrl = normalized;
    return true;
  }
}
