import { BusinessError } from '@kit.BasicServicesKit';
import { webSocket } from '@kit.NetworkKit';
import { AppConfig } from '../config/AppConfig';
import { ServiceWsTicketResponse, SupportEventEnvelope } from '../models/ServiceModels';
import { SupportEventParseResult, parseSupportEvent } from '../utils/ServiceRules';
import { NetworkResult } from './HttpClient';
import { ServiceService } from './services/ServiceService';

export enum SupportSocketState {
  AUTHORIZING = 'AUTHORIZING',
  CONNECTING = 'CONNECTING',
  CONNECTED = 'CONNECTED',
  RECONNECTING = 'RECONNECTING',
  DEGRADED = 'DEGRADED',
  STOPPED = 'STOPPED'
}

export class SupportSocket {
  private conversationId: string;
  private socket: webSocket.WebSocket | null = null;
  private service: ServiceService = new ServiceService();
  private connected: boolean = false;
  private authorizing: boolean = false;
  private manuallyStopped: boolean = false;
  private reconnectAttempts: number = 0;
  private reconnectTimer: number = -1;
  private generation: number = 0;
  private readonly maxReconnectAttempts: number = 4;
  private readonly maxDelayMs: number = 8000;
  private onEvent: (event: SupportEventEnvelope) => void;
  private onState: (state: SupportSocketState, message: string) => void;

  constructor(conversationId: string, onEvent: (event: SupportEventEnvelope) => void,
    onState: (state: SupportSocketState, message: string) => void) {
    this.conversationId = conversationId;
    this.onEvent = onEvent;
    this.onState = onState;
  }

  start(): void {
    if (this.connected || this.authorizing || this.socket !== null || this.conversationId.length === 0) {
      return;
    }
    this.manuallyStopped = false;
    this.reconnectAttempts = 0;
    this.generation += 1;
    this.authorizeAndConnect(this.generation);
  }

  stop(): void {
    this.manuallyStopped = true;
    this.connected = false;
    this.authorizing = false;
    this.generation += 1;
    if (this.reconnectTimer >= 0) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = -1;
    }
    const activeSocket: webSocket.WebSocket | null = this.socket;
    this.socket = null;
    if (activeSocket !== null) {
      activeSocket.close().catch((_error: Error): void => {});
    }
    this.onState(SupportSocketState.STOPPED, '客服实时连接已停止');
  }

  private async authorizeAndConnect(generation: number): Promise<void> {
    if (this.manuallyStopped || generation !== this.generation) {
      return;
    }
    this.authorizing = true;
    this.onState(SupportSocketState.AUTHORIZING, '正在申请客服会话一次性票据');
    const result: NetworkResult<ServiceWsTicketResponse> =
      await this.service.createSupportWsTicket(this.conversationId);
    if (this.manuallyStopped || generation !== this.generation) {
      return;
    }
    this.authorizing = false;
    if (!result.successful || result.data === null) {
      this.scheduleReconnect('客服会话票据获取失败', generation);
      return;
    }
    this.connectWithTicket(result.data.ticket, generation);
  }

  private connectWithTicket(ticket: string, generation: number): void {
    if (this.manuallyStopped || generation !== this.generation) {
      return;
    }
    this.onState(this.reconnectAttempts === 0 ? SupportSocketState.CONNECTING : SupportSocketState.RECONNECTING,
      this.reconnectAttempts === 0 ? '正在连接客服实时会话' : `正在第 ${this.reconnectAttempts} 次重连`);
    const nextSocket: webSocket.WebSocket = webSocket.createWebSocket();
    this.socket = nextSocket;
    nextSocket.on('open', (error: BusinessError, _value: Object) => {
      if (this.socket !== nextSocket || this.manuallyStopped || generation !== this.generation) {
        return;
      }
      if (error) {
        this.handleDisconnect(nextSocket, '客服实时连接失败', generation, true);
        return;
      }
      this.connected = true;
      this.reconnectAttempts = 0;
      if (this.reconnectTimer >= 0) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = -1;
      }
      this.onState(SupportSocketState.CONNECTED, '已连接客服实时会话');
    });
    nextSocket.on('message', (error: BusinessError, value: string | ArrayBuffer) => {
      if (this.socket !== nextSocket || this.manuallyStopped || generation !== this.generation ||
        error || typeof value !== 'string') {
        return;
      }
      const parsed: SupportEventParseResult = parseSupportEvent(value);
      if (parsed.valid && parsed.envelope !== null) {
        this.onEvent(parsed.envelope);
      }
    });
    nextSocket.on('close', (_error: BusinessError, _value: webSocket.CloseResult) => {
      this.handleDisconnect(nextSocket, '客服实时连接已断开', generation, false);
    });
    nextSocket.on('error', (_error: BusinessError) => {
      this.handleDisconnect(nextSocket, '客服实时连接异常', generation, true);
    });
    nextSocket.connect(AppConfig.getSupportWebSocketUrl(this.conversationId, ticket)).then((created: boolean) => {
      if (this.socket !== nextSocket || this.manuallyStopped || generation !== this.generation) {
        nextSocket.close().catch((_error: Error): void => {});
        return;
      }
      if (!created) {
        this.handleDisconnect(nextSocket, '无法创建客服实时连接', generation, true);
      }
    }).catch((_error: Error): void => {
      this.handleDisconnect(nextSocket, '无法创建客服实时连接', generation, true);
    });
  }

  private handleDisconnect(origin: webSocket.WebSocket, message: string, generation: number,
    closeOrigin: boolean): void {
    if (this.socket !== origin || generation !== this.generation) {
      return;
    }
    this.connected = false;
    this.socket = null;
    if (closeOrigin) {
      origin.close().catch((_error: Error): void => {});
    }
    if (this.manuallyStopped || this.reconnectTimer >= 0) {
      return;
    }
    this.scheduleReconnect(message, generation);
  }

  private scheduleReconnect(message: string, generation: number): void {
    if (this.manuallyStopped || generation !== this.generation || this.reconnectTimer >= 0) {
      return;
    }
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      this.onState(SupportSocketState.DEGRADED, `${message}，已停止自动重连，可手动刷新持久化消息`);
      return;
    }
    this.reconnectAttempts += 1;
    const delayMs: number = Math.min(this.maxDelayMs, 1000 * Math.pow(2, this.reconnectAttempts - 1));
    this.onState(SupportSocketState.RECONNECTING,
      `${message}，${delayMs / 1000} 秒后使用新的一次性票据重连`);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = -1;
      this.authorizeAndConnect(generation);
    }, delayMs);
  }
}
