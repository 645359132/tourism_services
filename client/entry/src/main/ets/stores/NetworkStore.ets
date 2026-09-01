export enum NetworkQuality {
  ONLINE = 'ONLINE',
  WEAK = 'WEAK',
  OFFLINE = 'OFFLINE'
}

export class NetworkStore {
  private static instance: NetworkStore = new NetworkStore();
  private quality: NetworkQuality = NetworkQuality.ONLINE;
  private latencyMs: number = 0;

  static getInstance(): NetworkStore {
    return NetworkStore.instance;
  }

  markOnline(latencyMs: number): void {
    this.quality = NetworkQuality.ONLINE;
    this.latencyMs = latencyMs;
  }

  markWeak(latencyMs: number): void {
    this.quality = NetworkQuality.WEAK;
    this.latencyMs = latencyMs;
  }

  markOffline(): void {
    this.quality = NetworkQuality.OFFLINE;
    this.latencyMs = 0;
  }

  getQuality(): NetworkQuality {
    return this.quality;
  }

  getLatencyMs(): number {
    return this.latencyMs;
  }

  isOffline(): boolean {
    return this.quality === NetworkQuality.OFFLINE;
  }
}
