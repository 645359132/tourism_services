import { BusinessError } from '@kit.BasicServicesKit';
import { webSocket } from '@kit.NetworkKit';
import { AppConfig } from '../config/AppConfig';
import { CrowdResponse } from '../models/GuideModels';
import { CrowdEnvelopeParseResult, parseCrowdEnvelope } from '../utils/GuideRules';

export enum CrowdSocketState {
  CONNECTING = 'CONNECTING',
  CONNECTED = 'CONNECTED',
  RECONNECTING = 'RECONNECTING',
  DEGRADED = 'DEGRADED',
  STOPPED = 'STOPPED'
}

class CrowdSocketPing {
  type: string = 'ping';
}

export class CrowdSocket {
  private socket: webSocket.WebSocket | null = null;
  private connected: boolean = false;
  private manuallyStopped: boolean = false;
  private reconnectAttempts: number = 0;
  private reconnectTimer: number = -1;
  private readonly maxReconnectAttempts: number = 4;
  private readonly maxReconnectDelayMs: number = 8000;
  private onSnapshot: (snapshot: CrowdResponse) => void;
  private onState: (state: CrowdSocketState, message: string) => void;

  constructor(onSnapshot: (snapshot: CrowdResponse) => void,
    onState: (state: CrowdSocketState, message: string) => void) {
    this.onSnapshot = onSnapshot;
    this.onState = onState;
  }

  start(): void {
    if (this.connected || this.socket !== null) {
      return;
    }
    this.manuallyStopped = false;
    this.reconnectAttempts = 0;
    this.connect();
  }

  stop(): void {
    this.manuallyStopped = true;
    this.connected = false;
    if (this.reconnectTimer >= 0) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = -1;
    }
    const activeSocket: webSocket.WebSocket | null = this.socket;
    this.socket = null;
    if (activeSocket !== null) {
      activeSocket.close().catch((_error: Error): void => {});
    }
    this.onState(CrowdSocketState.STOPPED, '实时人流连接已停止');
  }

  async sendPing(): Promise<boolean> {
    if (!this.connected || this.socket === null) {
      return false;
    }
    try {
      return await this.socket.send(JSON.stringify(new CrowdSocketPing()));
    } catch (error) {
      this.handleDisconnect('实时人流心跳失败');
      return false;
    }
  }

  private connect(): void {
    if (this.manuallyStopped) {
      return;
    }
    this.onState(this.reconnectAttempts === 0 ? CrowdSocketState.CONNECTING : CrowdSocketState.RECONNECTING,
      this.reconnectAttempts === 0 ? '正在连接模拟人流服务' : `正在第 ${this.reconnectAttempts} 次重连`);
    const nextSocket: webSocket.WebSocket = webSocket.createWebSocket();
    this.socket = nextSocket;
    nextSocket.on('open', (error: BusinessError, _value: Object) => {
      if (error) {
        this.handleDisconnect('实时人流连接失败');
        return;
      }
      this.connected = true;
      this.reconnectAttempts = 0;
      if (this.reconnectTimer >= 0) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = -1;
      }
      this.onState(CrowdSocketState.CONNECTED, '已连接模拟人流推送');
    });
    nextSocket.on('message', (error: BusinessError, value: string | ArrayBuffer) => {
      if (error || typeof value !== 'string') {
        return;
      }
      const parsed: CrowdEnvelopeParseResult = parseCrowdEnvelope(value);
      if (parsed.valid && parsed.envelope !== null) {
        this.onSnapshot(parsed.envelope.data);
      }
    });
    nextSocket.on('close', (_error: BusinessError, _value: webSocket.CloseResult) => {
      this.handleDisconnect('实时人流连接已断开');
    });
    nextSocket.on('error', (_error: BusinessError) => {
      this.handleDisconnect('实时人流连接异常');
    });
    nextSocket.connect(AppConfig.getCrowdWebSocketUrl()).then((created: boolean) => {
      if (!created) {
        this.handleDisconnect('无法创建实时人流连接');
      }
    }).catch((_error: Error): void => {
      this.handleDisconnect('无法创建实时人流连接');
    });
  }

  private handleDisconnect(message: string): void {
    this.connected = false;
    this.socket = null;
    if (this.manuallyStopped || this.reconnectTimer >= 0) {
      return;
    }
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      this.onState(CrowdSocketState.DEGRADED, `${message}，已停止自动重连，可手动刷新 REST 快照`);
      return;
    }
    this.reconnectAttempts += 1;
    const delayMs: number = Math.min(this.maxReconnectDelayMs,
      1000 * Math.pow(2, this.reconnectAttempts - 1));
    this.onState(CrowdSocketState.RECONNECTING,
      `${message}，${(delayMs / 1000).toString()} 秒后重连（最多 ${this.maxReconnectAttempts} 次）`);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = -1;
      this.connect();
    }, delayMs);
  }
}
