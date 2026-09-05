import {
  FaceDemoSample,
  FaceDemoVerifyRequest,
  FaceDemoVerifyResponse,
  TicketOrder,
  TicketOrderListResponse,
  TicketQrResponse,
  TicketQuote,
  TicketSlotListResponse,
  TicketTypeListResponse
} from '../../models/TicketModels';
import { ApiMethod, ApiRequest, HttpClient, NetworkResult } from '../HttpClient';

class QuotePayload {
  slot_id: string;
  quantity: number;

  constructor(slotId: string, quantity: number) {
    this.slot_id = slotId;
    this.quantity = quantity;
  }
}

class CreateOrderPayload {
  slot_id: string;
  quantity: number;
  idempotency_key: string;

  constructor(slotId: string, quantity: number, idempotencyKey: string) {
    this.slot_id = slotId;
    this.quantity = quantity;
    this.idempotency_key = idempotencyKey;
  }
}

class IdempotencyPayload {
  idempotency_key: string;

  constructor(idempotencyKey: string) {
    this.idempotency_key = idempotencyKey;
  }
}

class RefundPayload {
  reason: string;
  idempotency_key: string;

  constructor(reason: string, idempotencyKey: string) {
    this.reason = reason;
    this.idempotency_key = idempotencyKey;
  }
}

class ReschedulePayload {
  target_slot_id: string;
  idempotency_key: string;

  constructor(targetSlotId: string, idempotencyKey: string) {
    this.target_slot_id = targetSlotId;
    this.idempotency_key = idempotencyKey;
  }
}

export class TicketService {
  private client: HttpClient = new HttpClient();

  listTypes(): Promise<NetworkResult<TicketTypeListResponse>> {
    return this.client.request<TicketTypeListResponse>(
      new ApiRequest('/ticketing/types', ApiMethod.GET, '', false));
  }

  listSlots(visitDate: string, ticketTypeId: string): Promise<NetworkResult<TicketSlotListResponse>> {
    let path: string = `/ticketing/slots?visit_date=${encodeURIComponent(visitDate)}`;
    if (ticketTypeId.length > 0) {
      path += `&ticket_type_id=${encodeURIComponent(ticketTypeId)}`;
    }
    return this.client.request<TicketSlotListResponse>(new ApiRequest(path, ApiMethod.GET, '', false));
  }

  createQuote(slotId: string, quantity: number): Promise<NetworkResult<TicketQuote>> {
    const payload: QuotePayload = new QuotePayload(slotId, quantity);
    return this.client.request<TicketQuote>(
      new ApiRequest('/ticketing/quotes', ApiMethod.POST, JSON.stringify(payload), false, 0));
  }

  createOrder(slotId: string, quantity: number, idempotencyKey: string): Promise<NetworkResult<TicketOrder>> {
    const payload: CreateOrderPayload = new CreateOrderPayload(slotId, quantity, idempotencyKey);
    return this.client.request<TicketOrder>(
      new ApiRequest('/ticketing/orders', ApiMethod.POST, JSON.stringify(payload), true, 0));
  }

  listOrders(): Promise<NetworkResult<TicketOrderListResponse>> {
    return this.client.request<TicketOrderListResponse>(new ApiRequest('/ticketing/orders', ApiMethod.GET));
  }

  getOrder(orderId: string): Promise<NetworkResult<TicketOrder>> {
    return this.client.request<TicketOrder>(
      new ApiRequest(`/ticketing/orders/${encodeURIComponent(orderId)}`, ApiMethod.GET));
  }

  payOrder(orderId: string, idempotencyKey: string): Promise<NetworkResult<TicketOrder>> {
    const payload: IdempotencyPayload = new IdempotencyPayload(idempotencyKey);
    return this.client.request<TicketOrder>(new ApiRequest(
      `/ticketing/orders/${encodeURIComponent(orderId)}/pay`, ApiMethod.POST, JSON.stringify(payload), true, 0));
  }

  cancelOrder(orderId: string, idempotencyKey: string): Promise<NetworkResult<TicketOrder>> {
    const payload: IdempotencyPayload = new IdempotencyPayload(idempotencyKey);
    return this.client.request<TicketOrder>(new ApiRequest(
      `/ticketing/orders/${encodeURIComponent(orderId)}/cancel`, ApiMethod.POST, JSON.stringify(payload), true, 0));
  }

  refundOrder(orderId: string, reason: string, idempotencyKey: string): Promise<NetworkResult<TicketOrder>> {
    const payload: RefundPayload = new RefundPayload(reason, idempotencyKey);
    return this.client.request<TicketOrder>(new ApiRequest(
      `/ticketing/orders/${encodeURIComponent(orderId)}/refund`, ApiMethod.POST, JSON.stringify(payload), true, 0));
  }

  rescheduleOrder(orderId: string, targetSlotId: string,
    idempotencyKey: string): Promise<NetworkResult<TicketOrder>> {
    const payload: ReschedulePayload = new ReschedulePayload(targetSlotId, idempotencyKey);
    return this.client.request<TicketOrder>(new ApiRequest(
      `/ticketing/orders/${encodeURIComponent(orderId)}/reschedule`, ApiMethod.POST, JSON.stringify(payload), true, 0));
  }

  getTicketQr(ticketId: string): Promise<NetworkResult<TicketQrResponse>> {
    return this.client.request<TicketQrResponse>(new ApiRequest(
      `/ticketing/tickets/${encodeURIComponent(ticketId)}/qr`, ApiMethod.GET));
  }

  verifyFaceDemo(ticketId: string, sample: FaceDemoSample,
    consent: boolean): Promise<NetworkResult<FaceDemoVerifyResponse>> {
    // 该调用只进入“无生物信息”的演示 Provider。即使返回匹配，也不会放行或核销电子票。
    const payload: FaceDemoVerifyRequest = new FaceDemoVerifyRequest(sample, consent);
    return this.client.request<FaceDemoVerifyResponse>(new ApiRequest(
      `/ticketing/tickets/${encodeURIComponent(ticketId)}/face-demo/verify`,
      ApiMethod.POST, JSON.stringify(payload), true, 0));
  }
}
