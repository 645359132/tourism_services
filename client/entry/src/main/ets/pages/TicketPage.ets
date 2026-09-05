import { StatePanel } from '../components/StatePanel';
import { ContentState } from '../models/AppModels';
import {
  ElectronicTicket,
  ElectronicTicketStatus,
  FaceDemoResult,
  FaceDemoSample,
  FaceDemoVerifyResponse,
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
import { ApiErrorCode, ApiErrorInfo } from '../network/ApiError';
import { NetworkResult } from '../network/HttpClient';
import { TicketService } from '../network/services/TicketService';
import { AuthStore } from '../stores/AuthStore';
import { TravelPersistenceStore } from '../stores/TravelPersistenceStore';
import { CachedTicketIdentity } from '../models/PersistenceModels';
import {
  InventoryChangeResult,
  PendingIdempotentOperation,
  TicketOrderAction,
  TicketRuleResult,
  canApplyTicketAction,
  canRefundTicketOrder,
  detectInventoryChange,
  formatMoney,
  hasRequiredIssuedTickets,
  ticketOrderRenderKey,
  ticketSlotRenderKey,
  validateTicketQuantity,
  validateVisitDate
} from '../utils/TicketRules';
import { formatScenicClock, formatShanghaiDateTime } from '../utils/DateTimeRules';
import { shanghaiDateAfterDays } from '../utils/BookingRules';

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
  @State bookingState: ContentState = ContentState.LOADING;
  @State bookingErrorMessage: string = '';
  @State ordersState: ContentState = ContentState.LOADING;
  @State ordersErrorMessage: string = '';
  @State ticketTypes: TicketType[] = [];
  @State selectedTypeId: string = '';
  @State visitDate: string = shanghaiDateAfterDays(1);
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
  @State faceTicketId: string = '';
  @State faceSample: FaceDemoSample = FaceDemoSample.OWNER;
  @State faceMessage: string = '';
  private service: TicketService = new TicketService();
  private createPending: PendingIdempotentOperation = new PendingIdempotentOperation();
  private payPending: PendingIdempotentOperation = new PendingIdempotentOperation();
  private cancelPending: PendingIdempotentOperation = new PendingIdempotentOperation();
  private refundPending: PendingIdempotentOperation = new PendingIdempotentOperation();
  private reschedulePending: PendingIdempotentOperation = new PendingIdempotentOperation();
  private slotRequestVersion: number = 0;
  private orderRequestVersion: number = 0;

  aboutToAppear(): void {
    if (this.loggedIn) {
      const userId: string = AuthStore.getInstance().getUserId();
      this.orders = TravelPersistenceStore.getInstance().loadTicketOrders(userId);
      const cachedTicket: CachedTicketIdentity | null =
        TravelPersistenceStore.getInstance().loadTicketIdentity(userId);
      if (cachedTicket !== null) {
        this.qrTicketCode = cachedTicket.ticket_code;
        this.qrExpiresAt = cachedTicket.expires_at;
        this.operationMessage = '已恢复离线票据身份；出于安全考虑，扫码凭证需联网重新获取';
      }
    }
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

  private clearSlotSelection(message: string = ''): void {
    // 日期或票种一旦变化，旧场次和报价立即失效。递增版本号还能阻止迟到响应
    // 把上一日期的场次重新写回页面，避免用户实际买到与输入日期不同的票。
    this.slotRequestVersion++;
    this.selectedSlotId = '';
    this.quote = null;
    this.slots = [];
    this.inventoryNotice = message;
  }

  private async loadTypes(): Promise<void> {
    this.bookingState = ContentState.LOADING;
    this.bookingErrorMessage = '';
    const result: NetworkResult<TicketTypeListResponse> = await this.service.listTypes();
    if (!result.successful || result.data === null) {
      this.bookingState = ContentState.ERROR;
      this.bookingErrorMessage = this.errorText(result.error);
      return;
    }
    this.ticketTypes = result.data.items;
    if (this.ticketTypes.length === 0) {
      this.bookingState = ContentState.EMPTY;
      return;
    }
    if (this.selectedTypeId.length === 0) {
      this.selectedTypeId = this.ticketTypes[0].id;
    }
    await this.loadSlots();
  }

  private async loadSlots(): Promise<void> {
    const requestedDate: string = this.visitDate;
    const requestedTypeId: string = this.selectedTypeId;
    const dateResult: TicketRuleResult = validateVisitDate(requestedDate);
    if (!dateResult.valid) {
      this.bookingState = ContentState.ERROR;
      this.bookingErrorMessage = dateResult.message;
      return;
    }
    const requestVersion: number = ++this.slotRequestVersion;
    this.bookingState = ContentState.LOADING;
    this.bookingErrorMessage = '';
    const priorSelected: TicketSlot | null = this.findSlot(this.slots, this.selectedSlotId);
    const result: NetworkResult<TicketSlotListResponse> =
      await this.service.listSlots(requestedDate, requestedTypeId);
    if (requestVersion !== this.slotRequestVersion || this.visitDate !== requestedDate ||
      this.selectedTypeId !== requestedTypeId) {
      return;
    }
    if (!result.successful || result.data === null) {
      this.bookingState = ContentState.ERROR;
      this.bookingErrorMessage = this.errorText(result.error);
      return;
    }
    const updatedSlots: TicketSlot[] = result.data.items;
    for (let index: number = 0; index < updatedSlots.length; index++) {
      if (updatedSlots[index].visit_date !== requestedDate ||
        (requestedTypeId.length > 0 && updatedSlots[index].ticket_type_id !== requestedTypeId)) {
        this.slots = [];
        this.selectedSlotId = '';
        this.quote = null;
        this.bookingState = ContentState.ERROR;
        this.bookingErrorMessage = '服务端返回的门票日期或票种与当前查询不一致，请重新查询';
        return;
      }
    }
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
    this.bookingState = this.slots.length === 0 ? ContentState.EMPTY : ContentState.CONTENT;
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
    const requestedSlotId: string = slot.id;
    const requestedSlotVersion: number = this.slotRequestVersion;
    const requestedDate: string = this.visitDate;
    const requestedTypeId: string = this.selectedTypeId;
    const requestedQuantity: number = this.quantity;
    const result: NetworkResult<TicketQuote> = await this.service.createQuote(requestedSlotId, requestedQuantity);
    this.operationBusy = false;
    if (requestedSlotVersion !== this.slotRequestVersion ||
      this.selectedSlotId !== requestedSlotId || this.visitDate !== requestedDate ||
      this.selectedTypeId !== requestedTypeId || this.quantity !== requestedQuantity) {
      this.quote = null;
      this.operationMessage = '日期、票种、时段或数量已变化，请按当前选择重新报价';
      return;
    }
    if (!result.successful || result.data === null) {
      this.quote = null;
      this.operationMessage = this.errorText(result.error);
      await this.loadSlots();
      return;
    }
    if (result.data.slot_id !== requestedSlotId || result.data.ticket_type_id !== requestedTypeId ||
      result.data.visit_date !== requestedDate || result.data.start_time !== slot.start_time ||
      result.data.end_time !== slot.end_time || result.data.quantity !== requestedQuantity) {
      this.quote = null;
      this.operationMessage = '报价对应的日期或场次已变化，请刷新后重新选择';
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
    if (slot.visit_date !== this.visitDate || slot.ticket_type_id !== this.selectedTypeId ||
      this.quote.slot_id !== slot.id || this.quote.visit_date !== this.visitDate ||
      this.quote.ticket_type_id !== this.selectedTypeId || this.quote.quantity !== this.quantity ||
      this.quote.quote_token.length === 0) {
      this.quote = null;
      this.operationMessage = '日期或时段已变化，请重新选择场次并获取价格';
      return;
    }
    this.operationBusy = true;
    this.operationMessage = '';
    const createOperationId: string = `${slot.id}:${this.quantity.toString()}`;
    const createKey: string = this.createPending.getOrCreate(createOperationId, 'ticket-order');
    const result: NetworkResult<TicketOrder> =
      await this.service.createOrder(slot.id, this.quantity, this.quote.quote_token, createKey);
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
      this.ordersState = ContentState.NO_PERMISSION;
      return;
    }
    const requestVersion: number = ++this.orderRequestVersion;
    this.ordersState = ContentState.LOADING;
    const result: NetworkResult<TicketOrderListResponse> = await this.service.listOrders();
    if (requestVersion !== this.orderRequestVersion) {
      return;
    }
    if (!result.successful || result.data === null) {
      const cached: TicketOrder[] = TravelPersistenceStore.getInstance().loadTicketOrders(
        AuthStore.getInstance().getUserId());
      if (cached.length > 0 && result.error !== null && result.error.code === ApiErrorCode.OFFLINE) {
        this.orders = cached;
        this.ordersState = ContentState.CONTENT;
        this.operationMessage = '网络不可用，正在展示本地缓存订单与电子票';
        return;
      }
      this.ordersState = ContentState.ERROR;
      this.ordersErrorMessage = this.errorText(result.error);
      return;
    }
    this.orders = result.data.items;
    this.reconcileExpandedOrderActions();
    TravelPersistenceStore.getInstance().saveTicketOrders(AuthStore.getInstance().getUserId(), this.orders);
    this.ordersState = this.orders.length === 0 ? ContentState.EMPTY : ContentState.CONTENT;
  }

  private replaceOrder(order: TicketOrder): void {
    const updated: TicketOrder[] = this.orders.slice();
    for (let index: number = 0; index < updated.length; index++) {
      if (updated[index].id === order.id) {
        updated[index] = order;
      }
    }
    this.orders = updated;
    this.reconcileExpandedOrderActions();
    TravelPersistenceStore.getInstance().saveTicketOrders(AuthStore.getInstance().getUserId(), this.orders);
  }

  private reconcileExpandedOrderActions(): void {
    if (this.refundOrderId.length > 0) {
      let refundStillAllowed: boolean = false;
      for (let index: number = 0; index < this.orders.length; index++) {
        if (this.orders[index].id === this.refundOrderId && canRefundTicketOrder(this.orders[index])) {
          refundStillAllowed = true;
          break;
        }
      }
      if (!refundStillAllowed) {
        this.refundOrderId = '';
        this.refundReason = '';
      }
    }
    if (this.faceTicketId.length > 0) {
      let faceStillAllowed: boolean = false;
      for (let orderIndex: number = 0; orderIndex < this.orders.length; orderIndex++) {
        const order: TicketOrder = this.orders[orderIndex];
        if (order.status !== TicketOrderStatus.PAID) {
          continue;
        }
        for (let ticketIndex: number = 0; ticketIndex < order.tickets.length; ticketIndex++) {
          if (order.tickets[ticketIndex].id === this.faceTicketId &&
            order.tickets[ticketIndex].status === ElectronicTicketStatus.ISSUED) {
            faceStillAllowed = true;
          }
        }
      }
      if (!faceStillAllowed) {
        this.faceTicketId = '';
        this.faceMessage = '';
      }
    }
  }

  private async pay(order: TicketOrder): Promise<void> {
    if (this.operationBusy) {
      return;
    }
    this.operationBusy = true;
    const payKey: string = this.payPending.getOrCreate(order.id, 'ticket-pay');
    const result: NetworkResult<TicketOrder> = await this.service.payOrder(order.id, payKey);
    if (result.successful && result.data !== null) {
      this.payPending.resolveSuccess();
      this.replaceOrder(result.data);
      await this.loadOrders();
      this.operationMessage = `订单 ${result.data.order_no} 演示支付成功`;
    } else {
      this.resolvePendingFailure(this.payPending, result.error);
      if (result.error !== null && result.error.statusCode === 409) {
        await this.loadOrders();
      }
      this.operationMessage = this.errorText(result.error);
    }
    this.operationBusy = false;
  }

  private async cancel(order: TicketOrder): Promise<void> {
    if (this.operationBusy) {
      return;
    }
    this.operationBusy = true;
    const cancelKey: string = this.cancelPending.getOrCreate(order.id, 'ticket-cancel');
    const result: NetworkResult<TicketOrder> = await this.service.cancelOrder(order.id, cancelKey);
    if (result.successful && result.data !== null) {
      this.cancelPending.resolveSuccess();
      this.replaceOrder(result.data);
      this.clearSlotSelection('订单已取消，原场次余票将在返回购票页时刷新');
      await this.loadOrders();
      this.operationMessage = `订单 ${result.data.order_no} 已取消，余票已释放`;
    } else {
      this.resolvePendingFailure(this.cancelPending, result.error);
      if (result.error !== null && result.error.statusCode === 409) {
        await this.loadOrders();
      }
      this.operationMessage = this.errorText(result.error);
    }
    this.operationBusy = false;
  }

  private async refund(order: TicketOrder): Promise<void> {
    if (this.operationBusy) {
      return;
    }
    if (this.refundReason.trim().length < 3) {
      this.operationMessage = '请填写至少 3 个字符的退款原因';
      return;
    }
    this.operationBusy = true;
    const reason: string = this.refundReason.trim();
    const refundOperationId: string = `${order.id}:${reason}`;
    const refundKey: string = this.refundPending.getOrCreate(refundOperationId, 'ticket-refund');
    const result: NetworkResult<TicketOrder> = await this.service.refundOrder(order.id, reason, refundKey);
    if (result.successful && result.data !== null) {
      this.refundPending.resolveSuccess();
      this.replaceOrder(result.data);
      this.refundOrderId = '';
      this.clearSlotSelection('退款已完成，原场次余票将在返回购票页时刷新');
      await this.loadOrders();
      this.operationMessage = `订单 ${result.data.order_no} 已退款，原场次余票已恢复`;
    } else {
      this.resolvePendingFailure(this.refundPending, result.error);
      if (result.error !== null && result.error.statusCode === 409) {
        await this.loadOrders();
      }
      this.operationMessage = this.errorText(result.error);
    }
    this.operationBusy = false;
  }

  private async reschedule(order: TicketOrder): Promise<void> {
    if (this.operationBusy) {
      return;
    }
    const target: TicketSlot | null = this.selectedSlot();
    if (target === null || target.id === order.slot_id) {
      this.operationMessage = '请先在购票页选择另一个有库存的目标时段';
      return;
    }
    this.operationBusy = true;
    const rescheduleOperationId: string = `${order.id}:${target.id}`;
    const rescheduleKey: string = this.reschedulePending.getOrCreate(rescheduleOperationId, 'ticket-reschedule');
    const result: NetworkResult<TicketOrder> = await this.service.rescheduleOrder(order.id, target.id, rescheduleKey);
    if (result.successful && result.data !== null) {
      this.reschedulePending.resolveSuccess();
      this.replaceOrder(result.data);
      this.clearSlotSelection('改签已完成，相关场次余票将在返回购票页时刷新');
      await this.loadOrders();
      this.operationMessage = `订单 ${result.data.order_no} 已改签到 ${formatScenicClock(result.data.start_time)}`;
    } else {
      this.resolvePendingFailure(this.reschedulePending, result.error);
      if (result.error !== null && result.error.statusCode === 409) {
        await this.loadOrders();
      }
      this.operationMessage = this.errorText(result.error);
    }
    this.operationBusy = false;
  }

  private async showQr(ticket: ElectronicTicket): Promise<void> {
    this.operationBusy = true;
    const result: NetworkResult<TicketQrResponse> = await this.service.getTicketQr(ticket.id);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.qrData = result.data.qr_data;
      this.qrTicketCode = result.data.ticket_code;
      this.qrExpiresAt = result.data.expires_at;
      TravelPersistenceStore.getInstance().saveTicketIdentity(AuthStore.getInstance().getUserId(), result.data);
    } else {
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async verifyFaceDemo(ticket: ElectronicTicket): Promise<void> {
    if (this.operationBusy) {
      return;
    }
    this.operationBusy = true;
    const result: NetworkResult<FaceDemoVerifyResponse> = await this.service.verifyFaceDemo(
      ticket.id, this.faceSample, true);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      const resultText: string = result.data.result === FaceDemoResult.MATCHED ?
        '演示结果：身份样本匹配' : '演示结果：身份样本不匹配';
      this.faceMessage = `${resultText}。${result.data.disclaimer}`;
    } else {
      this.faceMessage = this.errorText(result.error);
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
    .enabled(!this.operationBusy)
    .onClick(() => {
      this.selectedTypeId = item.id;
      this.clearSlotSelection();
      this.loadSlots();
    })
  }

  @Builder
  private slotCard(slot: TicketSlot) {
    Column({ space: 7 }) {
      Row() {
        Text(`${slot.visit_date}  ${formatScenicClock(slot.start_time)} - ${formatScenicClock(slot.end_time)}`)
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
    .enabled(!this.operationBusy)
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
            .enabled(!this.operationBusy)
            .layoutWeight(1)
            .fontColor($r('app.color.text_primary'))
            .backgroundColor($r('app.color.surface'))
            .onChange((value: string) => {
              if (value === this.visitDate) {
                return;
              }
              this.visitDate = value;
              this.clearSlotSelection('日期已修改，正在查询与该日期绑定的门票场次');
              if (validateVisitDate(value).valid) {
                this.loadSlots();
              } else {
                this.bookingState = ContentState.EMPTY;
                this.bookingErrorMessage = '';
              }
            })
          Button('查询时段')
            .enabled(!this.operationBusy)
            .fontColor(Color.White)
            .backgroundColor($r('app.color.primary'))
            .onClick(() => {
              this.quote = null;
              this.loadSlots();
            })
          Button('刷新库存')
            .enabled(!this.operationBusy)
            .fontColor($r('app.color.primary'))
            .backgroundColor($r('app.color.surface_tint'))
            .onClick(() => {
              this.loadSlots();
            })
        }
        .width('100%')

        Text('演示退票规则：仅已支付且未核验的门票可退，具体截止时间由服务端配置并显示在订单卡片。')
          .width('100%')
          .fontSize(11)
          .fontColor($r('app.color.text_secondary'))

        if (this.inventoryNotice.length > 0) {
          Text(this.inventoryNotice)
            .width('100%')
            .padding(12)
            .fontSize(12)
            .fontColor($r('app.color.warning'))
            .borderRadius(12)
            .backgroundColor($r('app.color.surface_tint'))
        }

        if (this.bookingState === ContentState.LOADING || this.bookingState === ContentState.EMPTY ||
          this.bookingState === ContentState.ERROR) {
          StatePanel({
            state: this.bookingState,
            message: this.bookingErrorMessage,
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
          }, (slot: TicketSlot) => ticketSlotRenderKey(slot))

          Row({ space: 12 }) {
            Text('购票数量')
              .fontSize(15)
              .fontColor($r('app.color.text_primary'))
              .layoutWeight(1)
            Button('−').enabled(!this.operationBusy).width(38).height(38).onClick(() => {
              if (this.quantity > 1) {
                this.quantity -= 1;
                this.quote = null;
              }
            })
            Text(this.quantity.toString())
              .width(30)
              .textAlign(TextAlign.Center)
              .fontColor($r('app.color.text_primary'))
            Button('+').enabled(!this.operationBusy).width(38).height(38).onClick(() => {
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
              Text(`适用日期 ${this.quote.visit_date} · ${formatScenicClock(this.quote.start_time)}-` +
                `${formatScenicClock(this.quote.end_time)}`)
                .width('100%')
                .fontSize(12)
                .fontColor($r('app.color.primary'))
              Text(this.quote.pricing_explanation.join(' · '))
                .width('100%')
                .fontSize(12)
                .fontColor($r('app.color.warning'))
              Text(`报价有效至 ${formatShanghaiDateTime(this.quote.expires_at)}`)
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
      Text(`${order.visit_date}  ${formatScenicClock(order.start_time)}-${formatScenicClock(order.end_time)}  ·  ` +
        `${order.quantity} 张`)
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
          Column({ space: 7 }) {
            Row({ space: 6 }) {
              Text(`电子票 ${ticket.ticket_code}`)
                .fontSize(12)
                .fontColor($r('app.color.text_primary'))
                .maxLines(1)
                .layoutWeight(1)
              if (ticket.status === ElectronicTicketStatus.ISSUED) {
                Button('二维码')
                  .fontSize(10)
                  .fontColor($r('app.color.primary'))
                  .backgroundColor($r('app.color.surface_tint'))
                  .onClick(() => {
                    this.showQr(ticket);
                  })
                Button('人脸演示')
                  .fontSize(10)
                  .fontColor($r('app.color.primary'))
                  .backgroundColor($r('app.color.surface_tint'))
                  .onClick(() => {
                    this.faceTicketId = ticket.id;
                    this.faceSample = FaceDemoSample.OWNER;
                    this.faceMessage = '请选择演示样本后执行核验';
                  })
              } else {
                Text(ticket.status === ElectronicTicketStatus.USED ? '已核验' : '已失效')
                  .fontSize(11)
                  .fontColor($r('app.color.text_secondary'))
              }
            }
            .width('100%')
            if (this.faceTicketId === ticket.id) {
              Column({ space: 7 }) {
                Text('人脸核验接口演示：不调用摄像头，不上传照片或特征，不会放行或核销门票。')
                  .width('100%').fontSize(10).fontColor($r('app.color.warning'))
                Row({ space: 6 }) {
                  Button('模拟本人')
                    .fontSize(10)
                    .fontColor(this.faceSample === FaceDemoSample.OWNER ? Color.White : $r('app.color.primary'))
                    .backgroundColor(this.faceSample === FaceDemoSample.OWNER ? $r('app.color.primary') :
                      $r('app.color.surface'))
                    .onClick(() => { this.faceSample = FaceDemoSample.OWNER; })
                  Button('模拟他人')
                    .fontSize(10)
                    .fontColor(this.faceSample === FaceDemoSample.OTHER ? Color.White : $r('app.color.primary'))
                    .backgroundColor(this.faceSample === FaceDemoSample.OTHER ? $r('app.color.primary') :
                      $r('app.color.surface'))
                    .onClick(() => { this.faceSample = FaceDemoSample.OTHER; })
                  Button(this.operationBusy ? '核验中…' : '执行核验')
                    .enabled(!this.operationBusy)
                    .fontSize(10).fontColor(Color.White).backgroundColor($r('app.color.primary'))
                    .onClick(() => { this.verifyFaceDemo(ticket); })
                }
                .width('100%')
                Text(this.faceMessage).width('100%').fontSize(10).fontColor($r('app.color.text_secondary'))
              }
              .width('100%').padding(10).borderRadius(10).backgroundColor($r('app.color.page_background'))
            }
          }
          .width('100%')
        }, (ticket: ElectronicTicket) => ticket.id)
        if (typeof order.refund_deadline_at === 'string' && order.refund_deadline_at.length > 0) {
          Text(`退票截止 ${formatShanghaiDateTime(order.refund_deadline_at)} · 需提前 ` +
            `${order.refund_cutoff_hours} 小时 · ${order.refundable ? '当前可申请' : '当前不可申请'}`)
            .width('100%')
            .fontSize(10)
            .fontColor(order.refundable ? $r('app.color.success') : $r('app.color.warning'))
        }
      }

      Row({ space: 8 }) {
        if (canApplyTicketAction(order.status, TicketOrderAction.PAY)) {
          Button('演示支付').enabled(!this.operationBusy).fontSize(12).fontColor(Color.White)
            .backgroundColor($r('app.color.primary')).onClick(() => {
              this.pay(order);
            })
        }
        if (canApplyTicketAction(order.status, TicketOrderAction.CANCEL)) {
          Button('取消订单').enabled(!this.operationBusy).fontSize(12).fontColor($r('app.color.error'))
            .backgroundColor($r('app.color.surface_tint')).onClick(() => {
              this.cancel(order);
            })
        }
        if (canRefundTicketOrder(order)) {
          Button('申请退款').enabled(!this.operationBusy).fontSize(12).fontColor($r('app.color.error'))
            .backgroundColor($r('app.color.surface_tint'))
            .onClick(() => {
              this.refundOrderId = order.id;
            })
        }
        if (hasRequiredIssuedTickets(order)) {
          Button('改签到已选时段').enabled(!this.operationBusy).fontSize(12).fontColor($r('app.color.primary'))
            .backgroundColor($r('app.color.surface_tint')).onClick(() => {
              this.reschedule(order);
            })
        }
      }
      .width('100%')

      if (this.refundOrderId === order.id && canRefundTicketOrder(order)) {
        Row({ space: 8 }) {
          TextInput({ text: this.refundReason, placeholder: '请输入退款原因' })
            .layoutWeight(1)
            .fontColor($r('app.color.text_primary'))
            .backgroundColor($r('app.color.page_background'))
            .onChange((value: string) => {
              this.refundReason = value;
            })
          Button('确认退款')
            .enabled(!this.operationBusy)
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
        } else if (this.ordersState !== ContentState.CONTENT) {
          StatePanel({
            state: this.ordersState,
            message: this.ordersErrorMessage,
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
          Text('待支付订单可主动取消并立即释放余票；退票截止与当前资格以订单卡片中的服务端规则为准。')
            .width('100%')
            .fontSize(11)
            .fontColor($r('app.color.text_secondary'))
          ForEach(this.orders, (order: TicketOrder) => {
            this.orderCard(order)
          }, (order: TicketOrder) => ticketOrderRenderKey(order))
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
            .enabled(!this.operationBusy)
            .layoutWeight(1)
            .fontColor(this.tab === TicketPageTab.BOOKING ? Color.White : $r('app.color.primary'))
            .backgroundColor(this.tab === TicketPageTab.BOOKING ? $r('app.color.primary') : $r('app.color.surface_tint'))
            .onClick(() => {
              this.tab = TicketPageTab.BOOKING;
              if (this.ticketTypes.length === 0) {
                this.loadTypes();
              } else {
                // 取消、退款、改签都会改变库存；每次回到购票页都重新读取服务端余票。
                this.loadSlots();
              }
            })
          Button('我的订单')
            .enabled(!this.operationBusy)
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
          Text(`有效至 ${formatShanghaiDateTime(this.qrExpiresAt)} · 演示票码`)
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
