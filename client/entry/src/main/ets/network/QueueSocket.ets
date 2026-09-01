import { BusinessError } from '@kit.BasicServicesKit';
import { webSocket } from '@kit.NetworkKit';
import { AppConfig } from '../config/AppConfig';
import { QueueEventEnvelope, WsTicketResponse } from '../models/BookingModels';
import { QueueEventParseResult, parseQueueEvent } from '../utils/BookingRules';
import { NetworkResult } from './HttpClient';
import { BookingService } from './services/BookingService';

export enum QueueSocketState {
  AUTHORIZING = 'AUTHORIZING',
  CONNECTING = 'CONNECTING',
  CONNECTED = 'CONNECTED',
  RECONNECTING = 'RECONNECTING',
  DEGRADED = 'DEGRADED',
  STOPPED = 'STOPPED'
}

export class QueueSocket {
  private queueId: string;
  private socket: webSocket.WebSocket | null = null;
  private service: BookingService = new BookingService();
  private connected: boolean = false;
  private authorizing: boolean = false;
  private manuallyStopped: boolean = false;
  private reconnectAttempts: number = 0;
  private reconnectTimer: number = -1;
  private generation: number = 0;
  private readonly maxReconnectAttempts: number = 4;
  private readonly maxDelayMs: number = 8000;
  private onEvent: (event: QueueEventEnvelope) => void;
  private onState: (state: QueueSocketState, message: string) => void;

  constructor(queueId: string, onEvent: (event: QueueEventEnvelope) => void,
    onState: (state: QueueSocketState, message: string) => void) {
    this.queueId = queueId;
    this.onEvent = onEvent;
    this.onState = onState;
  }

  start(): void {
    if (this.connected || this.authorizing || this.socket !== null || this.queueId.length === 0) {
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
    this.onState(QueueSocketState.STOPPED, '队列实时连接已停止');
  }

  private async authorizeAndConnect(generation: number): Promise<void> {
    if (this.manuallyStopped || generation !== this.generation) {
      return;
    }
    this.authorizing = true;
    this.onState(QueueSocketState.AUTHORIZING, '正在申请一次性队列连接票据');
    const ticketResult: NetworkResult<WsTicketResponse> = await this.service.createWsTicket(this.queueId);
    if (this.manuallyStopped || generation !== this.generation) {
      return;
    }
    this.authorizing = false;
    if (!ticketResult.successful || ticketResult.data === null) {
      this.scheduleReconnect('一次性队列连接票据获取失败', generation);
      return;
    }
    this.connectWithTicket(ticketResult.data.ticket, generation);
  }

  private connectWithTicket(ticket: string, generation: number): void {
    if (this.manuallyStopped || generation !== this.generation) {
      return;
    }
    this.onState(this.reconnectAttempts === 0 ? QueueSocketState.CONNECTING : QueueSocketState.RECONNECTING,
      this.reconnectAttempts === 0 ? '正在连接模拟队列推送' : `正在第 ${this.reconnectAttempts} 次重连`);
    const nextSocket: webSocket.WebSocket = webSocket.createWebSocket();
    this.socket = nextSocket;
    nextSocket.on('open', (error: BusinessError, _value: Object) => {
      if (this.socket !== nextSocket || this.manuallyStopped || generation !== this.generation) {
        return;
      }
      if (error) {
        this.handleDisconnect(nextSocket, '队列连接失败', generation);
        return;
      }
      this.connected = true;
      this.reconnectAttempts = 0;
      if (this.reconnectTimer >= 0) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = -1;
      }
      this.onState(QueueSocketState.CONNECTED, '已连接模拟队列实时推送');
    });
    nextSocket.on('message', (error: BusinessError, value: string | ArrayBuffer) => {
      if (this.socket !== nextSocket || this.manuallyStopped || generation !== this.generation ||
        error || typeof value !== 'string') {
        return;
      }
      const parsed: QueueEventParseResult = parseQueueEvent(value);
      if (parsed.valid && parsed.envelope !== null) {
        this.onEvent(parsed.envelope);
      }
    });
    nextSocket.on('close', (_error: BusinessError, _value: webSocket.CloseResult) => {
      this.handleDisconnect(nextSocket, '队列实时连接已断开', generation);
    });
    nextSocket.on('error', (_error: BusinessError) => {
      this.handleDisconnect(nextSocket, '队列实时连接异常', generation);
    });
    nextSocket.connect(AppConfig.getQueueWebSocketUrl(this.queueId, ticket)).then((created: boolean) => {
      if (this.socket !== nextSocket || this.manuallyStopped || generation !== this.generation) {
        nextSocket.close().catch((_error: Error): void => {});
        return;
      }
      if (!created && this.socket === nextSocket) {
        this.handleDisconnect(nextSocket, '无法创建队列实时连接', generation);
      }
    }).catch((_error: Error): void => {
      this.handleDisconnect(nextSocket, '无法创建队列实时连接', generation);
    });
  }

  private handleDisconnect(origin: webSocket.WebSocket, message: string, generation: number): void {
    if (this.socket !== origin || generation !== this.generation) {
      return;
    }
    this.connected = false;
    this.socket = null;
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
      this.onState(QueueSocketState.DEGRADED, `${message}，已停止自动重连，可手动刷新队列`);
      return;
    }
    this.reconnectAttempts += 1;
    const delayMs: number = Math.min(this.maxDelayMs, 1000 * Math.pow(2, this.reconnectAttempts - 1));
    this.onState(QueueSocketState.RECONNECTING,
      `${message}，${delayMs / 1000} 秒后使用新的一次性票据重连`);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = -1;
      this.authorizeAndConnect(generation);
    }, delayMs);
  }
}
