export enum TicketOrderStatus {
  PENDING_PAYMENT = 'PENDING_PAYMENT',
  PAID = 'PAID',
  EXPIRED = 'EXPIRED',
  CANCELLED = 'CANCELLED',
  REFUNDED = 'REFUNDED'
}

export enum ElectronicTicketStatus {
  ISSUED = 'ISSUED',
  USED = 'USED',
  VOID = 'VOID'
}

export enum FaceDemoSample {
  OWNER = 'OWNER',
  OTHER = 'OTHER'
}

export enum FaceDemoResult {
  MATCHED = 'DEMO_MATCHED',
  NOT_MATCHED = 'DEMO_NOT_MATCHED'
}

export class TicketType {
  id: string = '';
  code: string = '';
  name: string = '';
  audience: string = '';
  description: string = '';
  base_price_cents: number = 0;
}

export class TicketTypeListResponse {
  items: TicketType[] = [];
}

export class TicketSlot {
  id: string = '';
  ticket_type_id: string = '';
  visit_date: string = '';
  start_time: string = '';
  end_time: string = '';
  capacity: number = 0;
  remaining: number = 0;
  unit_price_cents: number = 0;
  pricing_explanation: string[] = [];
}

export class TicketSlotListResponse {
  items: TicketSlot[] = [];
}

export class TicketQuote {
  id: string = '';
  slot_id: string = '';
  quantity: number = 0;
  unit_price_cents: number = 0;
  total_cents: number = 0;
  expires_at: string = '';
  pricing_explanation: string[] = [];
}

export class ElectronicTicket {
  id: string = '';
  ticket_code: string = '';
  status: ElectronicTicketStatus = ElectronicTicketStatus.ISSUED;
}

export class TicketOrder {
  id: string = '';
  order_no: string = '';
  status: TicketOrderStatus = TicketOrderStatus.PENDING_PAYMENT;
  ticket_type_name: string = '';
  slot_id: string = '';
  visit_date: string = '';
  start_time: string = '';
  end_time: string = '';
  quantity: number = 0;
  unit_price_cents: number = 0;
  total_cents: number = 0;
  expires_at: string = '';
  refund_cutoff_hours: number = 0;
  refund_deadline_at: string | null = null;
  refundable: boolean = false;
  tickets: ElectronicTicket[] = [];
}

export class TicketOrderListResponse {
  items: TicketOrder[] = [];
}

export class TicketQrResponse {
  ticket_id: string = '';
  ticket_code: string = '';
  qr_data: string = '';
  expires_at: string = '';
  is_demo: boolean = true;
}

export class FaceDemoVerifyRequest {
  sample: FaceDemoSample;
  consent: boolean;

  constructor(sample: FaceDemoSample, consent: boolean) {
    this.sample = sample;
    this.consent = consent;
  }
}

export class FaceDemoVerifyResponse {
  ticket_id: string = '';
  ticket_code: string = '';
  result: FaceDemoResult = FaceDemoResult.NOT_MATCHED;
  provider: string = 'demo_face_gate';
  is_demo: boolean = true;
  biometric_processed: boolean = false;
  admission_granted: boolean = false;
  disclaimer: string = '';
}
