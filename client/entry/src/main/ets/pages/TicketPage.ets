import { StatePanel } from '../components/StatePanel';
import { ContentState } from '../models/AppModels';
import {
  ElectronicTicket,
  ElectronicTicketStatus,
  TicketOrder,
  TicketOrderListResponse,
  TicketOrderStatus,
  TicketQrResponse,
  TicketQuote,
  TicketSlot,
  TicketSlotListResponse,
  TicketType,
  TicketTypeListResponse
} from '../models/TicketModels';
import { ApiErrorInfo } from '../network/ApiError';
import { NetworkResult } from '../network/HttpClient';
import { TicketService } from '../network/services/TicketService';
import {
  InventoryChangeResult,
  PendingIdempotentOperation,
  TicketOrderAction,
  TicketRuleResult,
  canApplyTicketAction,
  detectInventoryChange,
  formatMoney,
  validateTicketQuantity,
  validateVisitDate
} from '../utils/TicketRules';

enum TicketPageTab {
  BOOKING = 0,
  ORDERS = 1
}

@Component
export struct TicketPage {
  @Prop loggedIn: boolean = false;
  onBack: () => void = (): void => {};
  onLoginTap: () => void = (): void => {};
  @State tab: TicketPageTab = TicketPageTab.BOOKING;
  @State contentState: ContentState = ContentState.LOADING;
  @State errorMessage: string = '';
  @State ticketTypes: TicketType[] = [];
  @State selectedTypeId: string = '';
  @State visitDate: string = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString().substring(0, 10);
  @State slots: TicketSlot[] = [];
  @State selectedSlotId: string = '';
  @State quantity: number = 1;
  @State quote: TicketQuote | null = null;
  @State orders: TicketOrder[] = [];
  @State inventoryNotice: string = '';
  @State operationMessage: string = '';
  @State operationBusy: boolean = false;
  @State requireLogin: boolean = false;
  @State refundOrderId: string = '';
  @State refundReason: string = '游客行程调整';
  @State qrData: string = '';
  @State qrTicketCode: string = '';
  @State qrExpiresAt: string = '';
  private service: TicketService = new TicketService();
  private createPending: PendingIdempotentOperation = new PendingIdempotentOperation();
  private payPending: PendingIdempotentOperation = new PendingIdempotentOperation();
  private refundPending: PendingIdempotentOperation = new PendingIdempotentOperation();
  private reschedulePending: PendingIdempotentOperation = new PendingIdempotentOperation();

  aboutToAppear(): void {
    this.loadTypes();
  }

  private errorText(error: ApiErrorInfo | null): string {
    return error === null ? '服务请求失败，请稍后重试' : error.userMessage;
  }

  private resolvePendingFailure(pending: PendingIdempotentOperation, error: ApiErrorInfo | null): void {
    if (error !== null) {
      pending.resolveFailure(error.statusCode, error.retriable);
    }
  }

  private findSlot(items: TicketSlot[], slotId: string): TicketSlot | null {
    for (let index: number = 0; index < items.length; index++) {
      if (items[index].id === slotId) {
        return items[index];
      }
    }
    return null;
  }

  private selectedSlot(): TicketSlot | null {
    return this.findSlot(this.slots, this.selectedSlotId);
  }

  private async loadTypes(): Promise<void> {
    this.contentState = ContentState.LOADING;
    this.errorMessage = '';
    const result: NetworkResult<TicketTypeListResponse> = await this.service.listTypes();
    if (!result.successful || result.data === null) {
      this.contentState = ContentState.ERROR;
      this.errorMessage = this.errorText(result.error);
      return;
    }
    this.ticketTypes = result.data.items;
    if (this.ticketTypes.length === 0) {
      this.contentState = ContentState.EMPTY;
      return;
    }
    if (this.selectedTypeId.length === 0) {
      this.selectedTypeId = this.ticketTypes[0].id;
    }
    await this.loadSlots();
  }

  private async loadSlots(): Promise<void> {
    const dateResult: TicketRuleResult = validateVisitDate(this.visitDate);
    if (!dateResult.valid) {
      this.contentState = ContentState.ERROR;
      this.errorMessage = dateResult.message;
      return;
    }
    this.contentState = ContentState.LOADING;
    this.errorMessage = '';
    const priorSelected: TicketSlot | null = this.findSlot(this.slots, this.selectedSlotId);
    const result: NetworkResult<TicketSlotListResponse> =
      await this.service.listSlots(this.visitDate, this.selectedTypeId);
    if (!result.successful || result.data === null) {
      this.contentState = ContentState.ERROR;
      this.errorMessage = this.errorText(result.error);
      return;
    }
    const updatedSlots: TicketSlot[] = result.data.items;
    const currentSelected: TicketSlot | null = this.findSlot(updatedSlots, this.selectedSlotId);
    if (this.selectedSlotId.length > 0 && currentSelected === null) {
      this.inventoryNotice = '所选时段已不可预约，请重新选择';
      this.selectedSlotId = '';
      this.quote = null;
    } else if (currentSelected !== null) {
      const change: InventoryChangeResult = detectInventoryChange(priorSelected, currentSelected);
      if (change.changed) {
        this.inventoryNotice = change.message;
        this.quote = null;
      }
    }
    this.slots = updatedSlots;
    this.contentState = this.slots.length === 0 ? ContentState.EMPTY : ContentState.CONTENT;
  }

  private async requestQuote(): Promise<void> {
    const slot: TicketSlot | null = this.selectedSlot();
    if (slot === null) {
      this.operationMessage = '请先选择预约时段';
      return;
    }
    const validation: TicketRuleResult = validateTicketQuantity(this.quantity, slot.remaining);
    if (!validation.valid) {
      this.operationMessage = validation.message;
      return;
    }
    this.operationBusy = true;
    this.operationMessage = '';
    const result: NetworkResult<TicketQuote> = await this.service.createQuote(slot.id, this.quantity);
    this.operationBusy = false;
    if (!result.successful || result.data === null) {
      this.quote = null;
      this.operationMessage = this.errorText(result.error);
      await this.loadSlots();
      return;
    }
    this.quote = result.data;
  }

  private async createOrder(): Promise<void> {
    if (!this.loggedIn) {
      this.requireLogin = true;
      this.operationMessage = '下单需要登录，登录后将使用真实账户创建订单';
      return;
    }
    const slot: TicketSlot | null = this.selectedSlot();
    if (slot === null || this.quote === null) {
      this.operationMessage = '请先选择时段并获取实时价格';
      return;
    }
    this.operationBusy = true;
    this.operationMessage = '';
    const createOperationId: string = `${slot.id}:${this.quantity.toString()}`;
    const createKey: string = this.createPending.getOrCreate(createOperationId, 'ticket-order');
    const result: NetworkResult<TicketOrder> = await this.service.createOrder(slot.id, this.quantity, createKey);
    this.operationBusy = false;
    if (!result.successful || result.data === null) {
      this.resolvePendingFailure(this.createPending, result.error);
      this.operationMessage = this.errorText(result.error);
      this.quote = null;
      await this.loadSlots();
      return;
    }
    this.createPending.resolveSuccess();
    this.operationMessage = `订单 ${result.data.order_no} 已创建，请在有效期内支付`;
    this.tab = TicketPageTab.ORDERS;
    await this.loadOrders();
  }

  private async loadOrders(): Promise<void> {
    if (!this.loggedIn) {
      this.contentState = ContentState.NO_PERMISSION;
      return;
    }
    this.contentState = ContentState.LOADING;
    const result: NetworkResult<TicketOrderListResponse> = await this.service.listOrders();
    if (!result.successful || result.data === null) {
      this.contentState = ContentState.ERROR;
      this.errorMessage = this.errorText(result.error);
      return;
    }
    this.orders = result.data.items;
    this.contentState = this.orders.length === 0 ? ContentState.EMPTY : ContentState.CONTENT;
  }

  private replaceOrder(order: TicketOrder): void {
    const updated: TicketOrder[] = this.orders.slice();
    for (let index: number = 0; index < updated.length; index++) {
      if (updated[index].id === order.id) {
        updated[index] = order;
      }
    }
    this.orders = updated;
  }

  private async pay(order: TicketOrder): Promise<void> {
    this.operationBusy = true;
    const payKey: string = this.payPending.getOrCreate(order.id, 'ticket-pay');
    const result: NetworkResult<TicketOrder> = await this.service.payOrder(order.id, payKey);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.payPending.resolveSuccess();
      this.replaceOrder(result.data);
      this.operationMessage = `订单 ${result.data.order_no} 支付成功`;
    } else {
      this.resolvePendingFailure(this.payPending, result.error);
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async refund(order: TicketOrder): Promise<void> {
    if (this.refundReason.trim().length < 3) {
      this.operationMessage = '请填写至少 3 个字符的退款原因';
      return;
    }
    this.operationBusy = true;
    const reason: string = this.refundReason.trim();
    const refundOperationId: string = `${order.id}:${reason}`;
    const refundKey: string = this.refundPending.getOrCreate(refundOperationId, 'ticket-refund');
    const result: NetworkResult<TicketOrder> = await this.service.refundOrder(order.id, reason, refundKey);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.refundPending.resolveSuccess();
      this.replaceOrder(result.data);
      this.refundOrderId = '';
      this.operationMessage = `订单 ${result.data.order_no} 已退款`;
    } else {
      this.resolvePendingFailure(this.refundPending, result.error);
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async reschedule(order: TicketOrder): Promise<void> {
    const target: TicketSlot | null = this.selectedSlot();
    if (target === null || target.id === order.slot_id) {
      this.operationMessage = '请先在购票页选择另一个有库存的目标时段';
      return;
    }
    this.operationBusy = true;
    const rescheduleOperationId: string = `${order.id}:${target.id}`;
    const rescheduleKey: string = this.reschedulePending.getOrCreate(rescheduleOperationId, 'ticket-reschedule');
    const result: NetworkResult<TicketOrder> = await this.service.rescheduleOrder(order.id, target.id, rescheduleKey);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.reschedulePending.resolveSuccess();
      this.replaceOrder(result.data);
      this.operationMessage = `订单 ${result.data.order_no} 已改签到 ${result.data.start_time}`;
    } else {
      this.resolvePendingFailure(this.reschedulePending, result.error);
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async showQr(ticket: ElectronicTicket): Promise<void> {
    this.operationBusy = true;
    const result: NetworkResult<TicketQrResponse> = await this.service.getTicketQr(ticket.id);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.qrData = result.data.qr_data;
      this.qrTicketCode = result.data.ticket_code;
      this.qrExpiresAt = result.data.expires_at;
    } else {
      this.operationMessage = this.errorText(result.error);
    }
  }

  private orderStatusText(status: TicketOrderStatus): string {
    if (status === TicketOrderStatus.PENDING_PAYMENT) {
      return '待支付';
    }
    if (status === TicketOrderStatus.PAID) {
      return '已支付';
    }
    if (status === TicketOrderStatus.REFUNDED) {
      return '已退款';
    }
    if (status === TicketOrderStatus.EXPIRED) {
      return '已过期';
    }
    return '已取消';
  }

  @Builder
  private ticketTypeCard(item: TicketType) {
    Column({ space: 5 }) {
      Text(item.name)
        .fontSize(16)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.selectedTypeId === item.id ? Color.White : $r('app.color.text_primary'))
      Text(item.audience)
        .fontSize(11)
        .fontColor(this.selectedTypeId === item.id ? '#E8F2FF' : $r('app.color.text_secondary'))
      Text(`基础价 ${formatMoney(item.base_price_cents)}`)
        .fontSize(12)
        .fontColor(this.selectedTypeId === item.id ? Color.White : $r('app.color.primary'))
    }
    .width(136)
    .height(92)
    .padding(12)
    .alignItems(HorizontalAlign.Start)
    .justifyContent(FlexAlign.Center)
    .borderRadius(16)
    .backgroundColor(this.selectedTypeId === item.id ? $r('app.color.primary') : $r('app.color.surface'))
    .onClick(() => {
      this.selectedTypeId = item.id;
      this.selectedSlotId = '';
      this.quote = null;
      this.inventoryNotice = '';
      this.loadSlots();
    })
  }

  @Builder
  private slotCard(slot: TicketSlot) {
    Column({ space: 7 }) {
      Row() {
        Text(`${slot.start_time} - ${slot.end_time}`)
          .fontSize(16)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.text_primary'))
          .layoutWeight(1)
        Text(formatMoney(slot.unit_price_cents))
          .fontSize(17)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.error'))
      }
      .width('100%')
      Row() {
        Text(slot.remaining > 0 ? `余票 ${slot.remaining}/${slot.capacity}` : '已售罄')
          .fontSize(12)
          .fontColor(slot.remaining > 5 ? $r('app.color.success') : $r('app.color.warning'))
          .layoutWeight(1)
        Text(this.selectedSlotId === slot.id ? '已选择' : '选择')
          .fontSize(12)
          .fontColor($r('app.color.primary'))
      }
      .width('100%')
      Text(slot.pricing_explanation.length > 0 ? slot.pricing_explanation.join(' · ') : '当前为基础价格')
        .width('100%')
        .fontSize(11)
        .fontColor($r('app.color.text_secondary'))
        .maxLines(2)
    }
    .width('100%')
    .padding(15)
    .borderRadius(17)
    .border({ width: this.selectedSlotId === slot.id ? 2 : 1,
      color: this.selectedSlotId === slot.id ? $r('app.color.primary') : $r('app.color.divider') })
    .backgroundColor($r('app.color.surface'))
    .opacity(slot.remaining > 0 ? 1 : 0.55)
    .onClick(() => {
      if (slot.remaining > 0) {
        this.selectedSlotId = slot.id;
        this.quote = null;
        this.operationMessage = '';
      }
    })
  }

  @Builder
  private bookingContent() {
    Scroll() {
      Column({ space: 16 }) {
        Text('选择票种')
          .width('100%')
          .fontSize(18)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.text_primary'))
        Scroll() {
          Row({ space: 10 }) {
            ForEach(this.ticketTypes, (item: TicketType) => {
              this.ticketTypeCard(item)
            }, (item: TicketType) => item.id)
          }
        }
        .width('100%')
        .scrollable(ScrollDirection.Horizontal)
        .scrollBar(BarState.Off)

        Row({ space: 10 }) {
          TextInput({ text: this.visitDate, placeholder: 'YYYY-MM-DD' })
            .layoutWeight(1)
            .fontColor($r('app.color.text_primary'))
            .backgroundColor($r('app.color.surface'))
            .onChange((value: string) => {
              this.visitDate = value;
            })
          Button('查询时段')
            .fontColor(Color.White)
            .backgroundColor($r('app.color.primary'))
            .onClick(() => {
              this.quote = null;
              this.loadSlots();
            })
          Button('刷新库存')
            .fontColor($r('app.color.primary'))
            .backgroundColor($r('app.color.surface_tint'))
            .onClick(() => {
              this.loadSlots();
            })
        }
        .width('100%')

        if (this.inventoryNotice.length > 0) {
          Text(this.inventoryNotice)
            .width('100%')
            .padding(12)
            .fontSize(12)
            .fontColor($r('app.color.warning'))
            .borderRadius(12)
            .backgroundColor($r('app.color.surface_tint'))
        }

        if (this.contentState === ContentState.LOADING || this.contentState === ContentState.EMPTY ||
          this.contentState === ContentState.ERROR) {
          StatePanel({
            state: this.contentState,
            message: this.errorMessage,
            onRetry: (): void => {
              this.loadSlots();
            }
          })
        } else {
          Text('预约时段与动态价格')
            .width('100%')
            .fontSize(18)
            .fontWeight(FontWeight.Bold)
            .fontColor($r('app.color.text_primary'))
          ForEach(this.slots, (slot: TicketSlot) => {
            this.slotCard(slot)
          }, (slot: TicketSlot) => slot.id)

          Row({ space: 12 }) {
            Text('购票数量')
              .fontSize(15)
              .fontColor($r('app.color.text_primary'))
              .layoutWeight(1)
            Button('−').width(38).height(38).onClick(() => {
              if (this.quantity > 1) {
                this.quantity -= 1;
                this.quote = null;
              }
            })
            Text(this.quantity.toString())
              .width(30)
              .textAlign(TextAlign.Center)
              .fontColor($r('app.color.text_primary'))
            Button('+').width(38).height(38).onClick(() => {
              if (this.quantity < 8) {
                this.quantity += 1;
                this.quote = null;
              }
            })
          }
          .width('100%')
          .padding(15)
          .borderRadius(16)
          .backgroundColor($r('app.color.surface'))

          Button(this.operationBusy ? '处理中…' : '获取实时价格')
            .enabled(!this.operationBusy)
            .width('100%')
            .fontColor($r('app.color.primary'))
            .backgroundColor($r('app.color.surface_tint'))
            .onClick(() => {
              this.requestQuote();
            })

          if (this.quote !== null) {
            Column({ space: 8 }) {
              Row() {
                Text('服务端实时报价')
                  .fontSize(16)
                  .fontWeight(FontWeight.Bold)
                  .fontColor($r('app.color.text_primary'))
                  .layoutWeight(1)
                Text(formatMoney(this.quote.total_cents))
                  .fontSize(22)
                  .fontWeight(FontWeight.Bold)
                  .fontColor($r('app.color.error'))
              }
              .width('100%')
              Text(`${this.quote.quantity} 张 × ${formatMoney(this.quote.unit_price_cents)}`)
                .width('100%')
                .fontSize(12)
                .fontColor($r('app.color.text_secondary'))
              Text(this.quote.pricing_explanation.join(' · '))
                .width('100%')
                .fontSize(12)
                .fontColor($r('app.color.warning'))
              Text(`报价有效至 ${this.quote.expires_at}`)
                .width('100%')
                .fontSize(11)
                .fontColor($r('app.color.text_secondary'))
            }
            .width('100%')
            .padding(17)
            .borderRadius(18)
            .backgroundColor($r('app.color.surface'))
          }

          if (this.requireLogin && !this.loggedIn) {
            StatePanel({ state: ContentState.NO_PERMISSION, message: this.operationMessage })
            Button('登录后继续下单')
              .width('100%')
              .fontColor(Color.White)
              .backgroundColor($r('app.color.primary'))
              .onClick(() => {
                this.onLoginTap();
              })
          }
          Button(this.operationBusy ? '提交中…' : '确认下单')
            .enabled(!this.operationBusy && this.quote !== null)
            .width('100%')
            .height(48)
            .fontColor(Color.White)
            .backgroundColor($r('app.color.primary'))
            .onClick(() => {
              this.createOrder();
            })
        }

        if (this.operationMessage.length > 0 && !this.requireLogin) {
          Text(this.operationMessage)
            .width('100%')
            .fontSize(12)
            .fontColor($r('app.color.warning'))
        }
      }
      .width('100%')
      .constraintSize({ maxWidth: 760 })
      .padding({ left: 18, right: 18, top: 16, bottom: 30 })
    }
    .width('100%')
    .height('100%')
    .scrollBar(BarState.Off)
  }

  @Builder
  private orderCard(order: TicketOrder) {
    Column({ space: 10 }) {
      Row() {
        Text(order.ticket_type_name)
          .fontSize(17)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.text_primary'))
          .layoutWeight(1)
        Text(this.orderStatusText(order.status))
          .fontSize(12)
          .fontColor(order.status === TicketOrderStatus.PAID ? $r('app.color.success') :
            order.status === TicketOrderStatus.PENDING_PAYMENT ? $r('app.color.warning') : $r('app.color.text_secondary'))
      }
      .width('100%')
      Text(`${order.visit_date}  ${order.start_time}-${order.end_time}  ·  ${order.quantity} 张`)
        .width('100%')
        .fontSize(13)
        .fontColor($r('app.color.text_secondary'))
      Row() {
        Text(`订单号 ${order.order_no}`)
          .fontSize(11)
          .fontColor($r('app.color.text_secondary'))
          .layoutWeight(1)
        Text(formatMoney(order.total_cents))
          .fontSize(18)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.error'))
      }
      .width('100%')

      if (order.status === TicketOrderStatus.PAID) {
        ForEach(order.tickets, (ticket: ElectronicTicket) => {
          Row() {
            Text(`电子票 ${ticket.ticket_code}`)
              .fontSize(12)
              .fontColor($r('app.color.text_primary'))
              .layoutWeight(1)
            if (ticket.status === ElectronicTicketStatus.ISSUED) {
              Button('查看 QRCode')
                .fontSize(11)
                .fontColor($r('app.color.primary'))
                .backgroundColor($r('app.color.surface_tint'))
                .onClick(() => {
                  this.showQr(ticket);
                })
            } else {
              Text(ticket.status === ElectronicTicketStatus.USED ? '已核验' : '已失效')
                .fontSize(11)
                .fontColor($r('app.color.text_secondary'))
            }
          }
          .width('100%')
        }, (ticket: ElectronicTicket) => ticket.id)
      }

      Row({ space: 8 }) {
        if (canApplyTicketAction(order.status, TicketOrderAction.PAY)) {
          Button('立即支付').fontSize(12).fontColor(Color.White).backgroundColor($r('app.color.primary')).onClick(() => {
            this.pay(order);
          })
        }
        if (canApplyTicketAction(order.status, TicketOrderAction.REFUND)) {
          Button('申请退款').fontSize(12).fontColor($r('app.color.error')).backgroundColor($r('app.color.surface_tint'))
            .onClick(() => {
              this.refundOrderId = order.id;
            })
          Button('改签到已选时段').fontSize(12).fontColor($r('app.color.primary'))
            .backgroundColor($r('app.color.surface_tint')).onClick(() => {
              this.reschedule(order);
            })
        }
      }
      .width('100%')

      if (this.refundOrderId === order.id) {
        Row({ space: 8 }) {
          TextInput({ text: this.refundReason, placeholder: '请输入退款原因' })
            .layoutWeight(1)
            .fontColor($r('app.color.text_primary'))
            .backgroundColor($r('app.color.page_background'))
            .onChange((value: string) => {
              this.refundReason = value;
            })
          Button('确认退款')
            .fontSize(12)
            .fontColor(Color.White)
            .backgroundColor($r('app.color.error'))
            .onClick(() => {
              this.refund(order);
            })
        }
        .width('100%')
      }
    }
    .width('100%')
    .padding(17)
    .borderRadius(18)
    .backgroundColor($r('app.color.surface'))
  }

  @Builder
  private ordersContent() {
    Scroll() {
      Column({ space: 14 }) {
        if (!this.loggedIn) {
          StatePanel({ state: ContentState.NO_PERMISSION, message: '登录后可查看、支付、退款和改签订单' })
          Button('立即登录').fontColor(Color.White).backgroundColor($r('app.color.primary')).onClick(() => {
            this.onLoginTap();
          })
        } else if (this.contentState !== ContentState.CONTENT) {
          StatePanel({
            state: this.contentState,
            message: this.errorMessage,
            onRetry: (): void => {
              this.loadOrders();
            }
          })
        } else {
          Row() {
            Text('我的门票订单')
              .fontSize(19)
              .fontWeight(FontWeight.Bold)
              .fontColor($r('app.color.text_primary'))
              .layoutWeight(1)
            Button('刷新')
              .fontSize(12)
              .fontColor($r('app.color.primary'))
              .backgroundColor($r('app.color.surface_tint'))
              .onClick(() => {
                this.loadOrders();
              })
          }
          .width('100%')
          ForEach(this.orders, (order: TicketOrder) => {
            this.orderCard(order)
          }, (order: TicketOrder) => order.id)
        }
        if (this.operationMessage.length > 0) {
          Text(this.operationMessage)
            .width('100%')
            .padding(12)
            .borderRadius(12)
            .fontSize(12)
            .fontColor($r('app.color.warning'))
            .backgroundColor($r('app.color.surface_tint'))
        }
      }
      .width('100%')
      .constraintSize({ maxWidth: 760 })
      .padding({ left: 18, right: 18, top: 16, bottom: 30 })
    }
    .width('100%')
    .height('100%')
    .scrollBar(BarState.Off)
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        Row({ space: 8 }) {
          Button('‹ 返回')
            .fontSize(13)
            .fontColor($r('app.color.text_secondary'))
            .backgroundColor(Color.Transparent)
            .onClick(() => {
              this.onBack();
            })
          Button('预约购票')
            .layoutWeight(1)
            .fontColor(this.tab === TicketPageTab.BOOKING ? Color.White : $r('app.color.primary'))
            .backgroundColor(this.tab === TicketPageTab.BOOKING ? $r('app.color.primary') : $r('app.color.surface_tint'))
            .onClick(() => {
              this.tab = TicketPageTab.BOOKING;
              if (this.slots.length === 0) {
                this.loadTypes();
              } else {
                this.contentState = ContentState.CONTENT;
              }
            })
          Button('我的订单')
            .layoutWeight(1)
            .fontColor(this.tab === TicketPageTab.ORDERS ? Color.White : $r('app.color.primary'))
            .backgroundColor(this.tab === TicketPageTab.ORDERS ? $r('app.color.primary') : $r('app.color.surface_tint'))
            .onClick(() => {
              this.tab = TicketPageTab.ORDERS;
              this.loadOrders();
            })
        }
        .width('100%')
        .padding({ left: 12, right: 12, top: 8, bottom: 8 })
        .backgroundColor($r('app.color.surface'))
        if (this.tab === TicketPageTab.BOOKING) {
          this.bookingContent()
        } else {
          this.ordersContent()
        }
      }
      .width('100%')
      .height('100%')
      .backgroundColor($r('app.color.page_background'))

      if (this.qrData.length > 0) {
        Column({ space: 14 }) {
          Text('电子票 QRCode')
            .fontSize(22)
            .fontWeight(FontWeight.Bold)
            .fontColor($r('app.color.text_primary'))
          QRCode(this.qrData)
            .width(220)
            .height(220)
            .color(Color.Black)
            .backgroundColor(Color.White)
          Text(this.qrTicketCode)
            .fontSize(15)
            .fontColor($r('app.color.text_primary'))
          Text(`有效至 ${this.qrExpiresAt} · 演示票码`)
            .fontSize(11)
            .fontColor($r('app.color.text_secondary'))
          Button('关闭')
            .width('100%')
            .fontColor(Color.White)
            .backgroundColor($r('app.color.primary'))
            .onClick(() => {
              this.qrData = '';
            })
        }
        .width('88%')
        .constraintSize({ maxWidth: 420 })
        .padding(24)
        .borderRadius(22)
        .backgroundColor($r('app.color.surface'))
      }
    }
    .width('100%')
    .height('100%')
  }
}
