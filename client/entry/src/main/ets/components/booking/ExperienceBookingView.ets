import { StatePanel } from '../StatePanel';
import { ContentState } from '../../models/AppModels';
import {
  Experience,
  ExperienceListResponse,
  ExperienceSession,
  ExperienceSessionListResponse,
  FastPass,
  NearbyRecommendation,
  QueueEntry,
  QueueEventEnvelope,
  QueueStatus,
  Reservation,
  ReservationKind,
  ReservationListResponse,
  ReservationStatus,
  SessionStatus
} from '../../models/BookingModels';
import { Itinerary } from '../../models/GuideModels';
import { ApiErrorCode, ApiErrorInfo } from '../../network/ApiError';
import { NetworkResult } from '../../network/HttpClient';
import { QueueSocket, QueueSocketState } from '../../network/QueueSocket';
import { BookingService } from '../../network/services/BookingService';
import { ItineraryService } from '../../network/services/ItineraryService';
import { AppStore } from '../../stores/AppStore';
import {
  BookingRuleResult,
  SessionInventoryChange,
  detectSessionInventoryChange,
  hasReservationConflict,
  isCurrentItinerarySuggestion,
  isTerminalQueueStatus,
  reservationRenderKey,
  reservationStatusLabel,
  shanghaiDateAfterDays,
  shouldAcceptQueueEvent,
  validateBookingDate,
  validateSessionReservation
} from '../../utils/BookingRules';
import { PendingIdempotentOperation, formatMoney } from '../../utils/TicketRules';

@Component
export struct ExperienceBookingView {
  @Prop loggedIn: boolean = false;
  onLoginTap: () => void = (): void => {};
  onTripTap: () => void = (): void => {};
  @State contentState: ContentState = ContentState.LOADING;
  @State errorMessage: string = '';
  @State experiences: Experience[] = [];
  @State selectedExperienceId: string = '';
  @State visitDate: string = shanghaiDateAfterDays(1);
  @State sessions: ExperienceSession[] = [];
  @State selectedSessionId: string = '';
  @State partySize: number = 2;
  @State reservations: Reservation[] = [];
  @State queue: QueueEntry | null = null;
  @State fastPass: FastPass | null = null;
  @State queueSocketState: QueueSocketState = QueueSocketState.STOPPED;
  @State queueSocketMessage: string = '尚未加入队列';
  @State operationMessage: string = '';
  @State operationBusy: boolean = false;
  @State inventoryNotice: string = '';
  @State cancelReason: string = '游客行程调整';
  @State reminderEnabled: boolean = true;
  @State replanAvailable: boolean = false;
  @State suggestedItineraryId: string = '';
  @State suggestedItineraryRevision: number = -1;
  private service: BookingService = new BookingService();
  private itineraryService: ItineraryService = new ItineraryService();
  private queueSocket: QueueSocket | null = null;
  private reservationPending: PendingIdempotentOperation = new PendingIdempotentOperation();
  private confirmPending: PendingIdempotentOperation = new PendingIdempotentOperation();
  private cancelPending: PendingIdempotentOperation = new PendingIdempotentOperation();
  private joinPending: PendingIdempotentOperation = new PendingIdempotentOperation();
  private leavePending: PendingIdempotentOperation = new PendingIdempotentOperation();
  private fastPassPending: PendingIdempotentOperation = new PendingIdempotentOperation();

  aboutToAppear(): void {
    this.loadExperiences();
    if (this.loggedIn) {
      this.loadReservations();
    }
  }

  aboutToDisappear(): void {
    this.stopQueueSocket();
  }

  private stateForError(error: ApiErrorInfo | null): ContentState {
    if (error !== null && error.code === ApiErrorCode.OFFLINE) {
      return ContentState.OFFLINE;
    }
    if (error !== null && (error.code === ApiErrorCode.UNAUTHORIZED || error.code === ApiErrorCode.FORBIDDEN)) {
      return ContentState.NO_PERMISSION;
    }
    return ContentState.ERROR;
  }

  private errorText(error: ApiErrorInfo | null): string {
    return error === null ? '预约服务请求失败，请稍后重试' : error.userMessage;
  }

  private resolveFailure(pending: PendingIdempotentOperation, error: ApiErrorInfo | null): void {
    if (error !== null) {
      pending.resolveFailure(error.statusCode, error.retriable);
    }
  }

  private selectedExperience(): Experience | null {
    for (let index: number = 0; index < this.experiences.length; index++) {
      if (this.experiences[index].id === this.selectedExperienceId) {
        return this.experiences[index];
      }
    }
    return null;
  }

  private selectedSession(): ExperienceSession | null {
    for (let index: number = 0; index < this.sessions.length; index++) {
      if (this.sessions[index].id === this.selectedSessionId) {
        return this.sessions[index];
      }
    }
    return null;
  }

  private queuedExperience(): Experience | null {
    if (this.queue === null) {
      return null;
    }
    for (let index: number = 0; index < this.experiences.length; index++) {
      if (this.experiences[index].id === this.queue?.experience_id) {
        return this.experiences[index];
      }
    }
    return null;
  }

  private withRecommendation(queue: QueueEntry, recommendation: NearbyRecommendation | null): QueueEntry {
    if (recommendation === null) {
      return queue;
    }
    for (let index: number = 0; index < queue.nearby_recommendations.length; index++) {
      if (queue.nearby_recommendations[index].ref_id === recommendation.ref_id) {
        return queue;
      }
    }
    const updated: NearbyRecommendation[] = queue.nearby_recommendations.slice();
    updated.push(recommendation);
    queue.nearby_recommendations = updated;
    return queue;
  }

  private settleTerminalQueue(status: QueueStatus): boolean {
    if (!isTerminalQueueStatus(status)) {
      return false;
    }
    this.replanAvailable = false;
    this.suggestedItineraryId = '';
    this.suggestedItineraryRevision = -1;
    this.stopQueueSocket();
    this.queueSocketMessage = '队列已进入终态，实时连接与自动重连均已停止';
    if (status === QueueStatus.COMPLETED) {
      this.operationMessage = '本次排队服务已完成';
    } else if (status === QueueStatus.LEFT) {
      this.operationMessage = '已离开队列';
    } else {
      this.operationMessage = '本次排队已过期，请重新加入队列';
    }
    return true;
  }

  private async loadExperiences(): Promise<void> {
    this.contentState = ContentState.LOADING;
    const result: NetworkResult<ExperienceListResponse> = await this.service.listExperiences();
    if (!result.successful || result.data === null) {
      this.contentState = this.stateForError(result.error);
      this.errorMessage = this.errorText(result.error);
      return;
    }
    this.experiences = result.data.items;
    if (this.experiences.length === 0) {
      this.contentState = ContentState.EMPTY;
      return;
    }
    if (this.selectedExperienceId.length === 0) {
      this.selectedExperienceId = this.experiences[0].id;
    }
    await this.loadSessions();
  }

  private async loadSessions(): Promise<void> {
    const dateResult: BookingRuleResult = validateBookingDate(this.visitDate);
    if (!dateResult.valid) {
      this.contentState = ContentState.ERROR;
      this.errorMessage = dateResult.message;
      return;
    }
    const prior: ExperienceSession | null = this.selectedSession();
    this.contentState = ContentState.LOADING;
    const result: NetworkResult<ExperienceSessionListResponse> =
      await this.service.listSessions(this.selectedExperienceId, this.visitDate);
    if (!result.successful || result.data === null) {
      this.contentState = this.stateForError(result.error);
      this.errorMessage = this.errorText(result.error);
      return;
    }
    this.sessions = result.data.items;
    const current: ExperienceSession | null = this.selectedSession();
    if (prior !== null && current !== null) {
      const change: SessionInventoryChange = detectSessionInventoryChange(prior, current);
      if (change.changed) {
        this.inventoryNotice = change.message;
      }
    } else if (this.selectedSessionId.length > 0) {
      this.selectedSessionId = '';
      this.inventoryNotice = '所选场次已下架，请重新选择';
    }
    this.contentState = this.sessions.length === 0 ? ContentState.EMPTY : ContentState.CONTENT;
  }

  private async loadReservations(): Promise<void> {
    if (!this.loggedIn) {
      return;
    }
    const result: NetworkResult<ReservationListResponse> = await this.service.listReservations();
    if (result.successful && result.data !== null) {
      this.reservations = result.data.items;
    }
  }

  private replaceReservation(value: Reservation): void {
    const updated: Reservation[] = this.reservations.slice();
    let replaced: boolean = false;
    for (let index: number = 0; index < updated.length; index++) {
      if (updated[index].id === value.id) {
        updated[index] = value;
        replaced = true;
      }
    }
    if (!replaced) {
      updated.unshift(value);
    }
    this.reservations = updated;
  }

  private async createReservation(): Promise<void> {
    if (this.operationBusy) {
      return;
    }
    if (!this.loggedIn) {
      this.contentState = ContentState.NO_PERMISSION;
      this.operationMessage = '登录后才能创建真实预约';
      return;
    }
    const session: ExperienceSession | null = this.selectedSession();
    const validation: BookingRuleResult = validateSessionReservation(session, this.partySize);
    if (!validation.valid || session === null) {
      this.operationMessage = validation.message;
      return;
    }
    if (hasReservationConflict(this.reservations, session.starts_at, session.ends_at)) {
      this.operationMessage = '该场次与已有预约冲突，请更换场次';
      return;
    }
    this.operationBusy = true;
    const operationId: string = `${session.id}:${this.partySize}`;
    const key: string = this.reservationPending.getOrCreate(operationId, 'experience-reservation');
    const result: NetworkResult<Reservation> = await this.service.createReservation(session.id, this.partySize, key);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.reservationPending.resolveSuccess();
      this.replaceReservation(result.data);
      this.operationMessage = `预约 ${result.data.booking_no} 已保留，请确认`;
      await this.loadSessions();
    } else {
      this.resolveFailure(this.reservationPending, result.error);
      this.operationMessage = this.errorText(result.error);
      await this.loadSessions();
    }
  }

  private async confirmReservation(value: Reservation): Promise<void> {
    if (this.operationBusy) {
      return;
    }
    this.operationBusy = true;
    const key: string = this.confirmPending.getOrCreate(value.id, 'reservation-confirm');
    const result: NetworkResult<Reservation> = await this.service.confirmReservation(value.id, key);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.confirmPending.resolveSuccess();
      this.replaceReservation(result.data);
      this.operationMessage = `预约 ${result.data.booking_no} 已确认`;
    } else {
      this.resolveFailure(this.confirmPending, result.error);
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async cancelReservation(value: Reservation): Promise<void> {
    if (this.operationBusy) {
      return;
    }
    if (this.cancelReason.trim().length === 0) {
      this.operationMessage = '请填写取消原因';
      return;
    }
    this.operationBusy = true;
    const operationId: string = `${value.id}:${this.cancelReason.trim()}`;
    const key: string = this.cancelPending.getOrCreate(operationId, 'reservation-cancel');
    const result: NetworkResult<Reservation> = await this.service.cancelReservation(
      value.id, this.cancelReason.trim(), key);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.cancelPending.resolveSuccess();
      this.replaceReservation(result.data);
      this.operationMessage = `预约 ${result.data.booking_no} 已取消`;
      await this.loadSessions();
    } else {
      this.resolveFailure(this.cancelPending, result.error);
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async joinQueue(): Promise<void> {
    if (this.operationBusy) {
      return;
    }
    if (!this.loggedIn) {
      this.contentState = ContentState.NO_PERMISSION;
      this.operationMessage = '登录后才能加入模拟队列';
      return;
    }
    const experience: Experience | null = this.selectedExperience();
    if (experience === null || this.partySize < 1 || this.partySize > 8) {
      this.operationMessage = '请选择项目并检查同行人数';
      return;
    }
    const appStore: AppStore = AppStore.getInstance();
    const itineraryId: string | null = appStore.hasCurrentItinerary() ? appStore.getCurrentItineraryId() : null;
    const operationId: string = `${experience.id}:${this.partySize}:` +
      `${itineraryId === null ? 'no-itinerary' : itineraryId}`;
    const key: string = this.joinPending.getOrCreate(operationId, 'queue-join');
    this.operationBusy = true;
    const result: NetworkResult<QueueEntry> = await this.service.joinQueue(
      experience.id, this.partySize, itineraryId, key);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.joinPending.resolveSuccess();
      this.queue = result.data;
      this.fastPass = result.data.fast_pass;
      this.replanAvailable = false;
      this.suggestedItineraryId = '';
      this.suggestedItineraryRevision = -1;
      this.operationMessage = `已加入模拟队列 ${result.data.queue_no}`;
      if (!this.settleTerminalQueue(result.data.status)) {
        this.connectQueueSocket(result.data.id);
      }
    } else {
      this.resolveFailure(this.joinPending, result.error);
      this.operationMessage = this.errorText(result.error);
    }
  }

  private connectQueueSocket(queueId: string): void {
    this.stopQueueSocket();
    this.queueSocket = new QueueSocket(queueId, (event: QueueEventEnvelope): void => {
      if (this.queue === null || event.data.queue.id !== this.queue.id ||
        !shouldAcceptQueueEvent(this.queue.sequence, event.data.queue.sequence, event.type)) {
        return;
      }
      this.queue = this.withRecommendation(event.data.queue, event.data.recommendation);
      this.fastPass = event.data.queue.fast_pass;
      if (this.settleTerminalQueue(this.queue.status)) {
        return;
      }
      if (event.type === 'nearby.recommended' && event.data.recommendation !== null) {
        this.operationMessage = `新推荐：${event.data.recommendation.name}`;
      }
      if (event.type === 'itinerary.replan_available') {
        const appStore: AppStore = AppStore.getInstance();
        if (appStore.hasCurrentItinerary() && isCurrentItinerarySuggestion(
          appStore.getCurrentItineraryId(), appStore.getCurrentItineraryRevision(),
          event.data.itinerary_id, event.data.itinerary_revision)) {
          this.replanAvailable = true;
          this.suggestedItineraryId = event.data.itinerary_id ?? '';
          this.suggestedItineraryRevision = event.data.itinerary_revision ?? -1;
          this.operationMessage = '等待时间变化，可应用排队联动调整后续行程';
        } else {
          this.replanAvailable = false;
          this.suggestedItineraryId = '';
          this.suggestedItineraryRevision = -1;
          this.operationMessage = '收到的排队联动建议对应旧行程，已忽略；请刷新行程后重试';
        }
      }
      if (this.queue.status === QueueStatus.CALLED && this.reminderEnabled) {
        this.operationMessage = '队列已叫号：这是应用内提醒，未接系统通知服务';
      }
    }, (state: QueueSocketState, message: string): void => {
      this.queueSocketState = state;
      this.queueSocketMessage = message;
    });
    this.queueSocket.start();
  }

  private stopQueueSocket(): void {
    if (this.queueSocket !== null) {
      this.queueSocket.stop();
      this.queueSocket = null;
    }
  }

  private async refreshQueue(): Promise<void> {
    if (this.queue === null) {
      return;
    }
    const result: NetworkResult<QueueEntry> = await this.service.getQueue(this.queue.id);
    if (result.successful && result.data !== null) {
      this.queue = result.data;
      this.fastPass = result.data.fast_pass;
      if (!this.settleTerminalQueue(result.data.status)) {
        this.operationMessage = '已刷新模拟队列状态';
      }
    } else {
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async leaveQueue(): Promise<void> {
    if (this.queue === null || this.operationBusy) {
      return;
    }
    this.operationBusy = true;
    const key: string = this.leavePending.getOrCreate(this.queue.id, 'queue-leave');
    const result: NetworkResult<QueueEntry> = await this.service.leaveQueue(this.queue.id, key);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.leavePending.resolveSuccess();
      this.queue = result.data;
      this.fastPass = result.data.fast_pass;
      this.settleTerminalQueue(result.data.status);
    } else {
      this.resolveFailure(this.leavePending, result.error);
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async buyFastPass(): Promise<void> {
    if (this.queue === null || this.operationBusy) {
      return;
    }
    this.operationBusy = true;
    const key: string = this.fastPassPending.getOrCreate(this.queue.id, 'fast-pass');
    const result: NetworkResult<FastPass> = await this.service.buyFastPass(this.queue.id, key);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.fastPassPending.resolveSuccess();
      this.fastPass = result.data;
      this.operationMessage = '演示 FastPass 已创建；未接真实支付且不承诺立即入场';
    } else {
      this.resolveFailure(this.fastPassPending, result.error);
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async applyQueueReplan(): Promise<void> {
    if (this.operationBusy) {
      return;
    }
    const appStore: AppStore = AppStore.getInstance();
    if (!appStore.hasCurrentItinerary()) {
      this.operationMessage = '尚无当前行程，请先前往行程页生成';
      this.onTripTap();
      return;
    }
    if (!this.replanAvailable || !isCurrentItinerarySuggestion(
      appStore.getCurrentItineraryId(), appStore.getCurrentItineraryRevision(),
      this.suggestedItineraryId, this.suggestedItineraryRevision)) {
      this.replanAvailable = false;
      this.operationMessage = '排队联动建议已过期，请等待新的实时建议';
      return;
    }
    this.operationBusy = true;
    const result: NetworkResult<Itinerary> = await this.itineraryService.replan(
      this.suggestedItineraryId, this.suggestedItineraryRevision);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      appStore.setCurrentItinerary(result.data.id, result.data.revision);
      this.replanAvailable = false;
      this.suggestedItineraryId = '';
      this.suggestedItineraryRevision = -1;
      this.operationMessage = `排队联动已应用，行程更新至版本 ${result.data.revision}`;
    } else {
      this.operationMessage = this.errorText(result.error);
    }
  }

  @Builder
  private experienceCard(value: Experience) {
    Column({ space: 5 }) {
      Row() {
        Text(value.name).fontWeight(FontWeight.Bold).fontColor(this.selectedExperienceId === value.id ? Color.White :
          $r('app.color.text_primary')).layoutWeight(1)
        Text(value.kind).fontSize(10).fontColor(this.selectedExperienceId === value.id ? Color.White :
          $r('app.color.primary'))
      }.width('100%')
      Text(`${value.duration_minutes} 分钟 · 当前等待 ${value.wait_minutes} 分钟`)
        .fontSize(11).fontColor(this.selectedExperienceId === value.id ? '#E8F2FF' : $r('app.color.text_secondary'))
      Text(value.fastpass_allowed ? `FastPass 演示价 ${formatMoney(value.fastpass_price_cents)}` : '不提供 FastPass')
        .fontSize(11).fontColor(this.selectedExperienceId === value.id ? Color.White : $r('app.color.warning'))
    }
    .width(190).height(96).padding(13).alignItems(HorizontalAlign.Start).borderRadius(16)
    .backgroundColor(this.selectedExperienceId === value.id ? $r('app.color.primary') : $r('app.color.surface'))
    .onClick(() => {
      this.selectedExperienceId = value.id;
      this.selectedSessionId = '';
      this.loadSessions();
    })
  }

  @Builder
  private reservationCard(value: Reservation) {
    Column({ space: 7 }) {
      Row() {
        Text(value.resource_name).fontWeight(FontWeight.Medium).fontColor($r('app.color.text_primary')).layoutWeight(1)
        Text(reservationStatusLabel(value.status)).fontSize(11).fontColor(value.status === ReservationStatus.CONFIRMED ?
          $r('app.color.success') : $r('app.color.warning'))
      }.width('100%')
      Text(`${value.starts_at} · ${value.party_size} 人 · provider=${value.provider} · demo=${value.is_demo}`)
        .fontSize(10).fontColor($r('app.color.text_secondary'))
      if (value.status === ReservationStatus.HELD) {
        Row({ space: 8 }) {
          Button('确认预约').fontSize(11).fontColor(Color.White).backgroundColor($r('app.color.primary')).onClick(() => {
            this.confirmReservation(value);
          })
          Button('取消').fontSize(11).fontColor($r('app.color.error')).backgroundColor($r('app.color.surface_tint'))
            .onClick(() => { this.cancelReservation(value); })
        }.width('100%')
      } else if (value.status === ReservationStatus.CONFIRMED) {
        Button('取消预约').fontSize(11).fontColor($r('app.color.error')).backgroundColor($r('app.color.surface_tint'))
          .onClick(() => { this.cancelReservation(value); })
      }
    }
    .width('100%').padding(14).borderRadius(15).backgroundColor($r('app.color.surface'))
  }

  build() {
    Scroll() {
      Column({ space: 14 }) {
        Text('项目与演出').width('100%').fontSize(20).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.text_primary'))
        Text('场次、库存与预约来自真实 API；队列经真实 REST/WebSocket 传输，排队算法和提醒来源为演示适配器。')
          .width('100%').fontSize(11).fontColor($r('app.color.warning'))

        Scroll() {
          Row({ space: 10 }) {
            ForEach(this.experiences, (value: Experience) => { this.experienceCard(value) },
              (value: Experience) => value.id)
          }
        }.width('100%').scrollable(ScrollDirection.Horizontal).scrollBar(BarState.Off)

        Row({ space: 8 }) {
          TextInput({ text: this.visitDate, placeholder: 'YYYY-MM-DD' }).layoutWeight(1)
            .fontColor($r('app.color.text_primary')).backgroundColor($r('app.color.surface'))
            .onChange((value: string) => { this.visitDate = value; })
          Button('查询场次').fontColor(Color.White).backgroundColor($r('app.color.primary')).onClick(() => {
            this.loadSessions();
          })
          Button('刷新库存').fontColor($r('app.color.primary')).backgroundColor($r('app.color.surface_tint'))
            .onClick(() => { this.loadSessions(); })
        }.width('100%')

        if (this.contentState !== ContentState.CONTENT) {
          StatePanel({ state: this.contentState, message: this.errorMessage.length > 0 ? this.errorMessage :
            this.operationMessage, onRetry: (): void => { this.loadExperiences(); } })
          if (this.contentState === ContentState.NO_PERMISSION) {
            Button(this.loggedIn ? '继续' : '登录后继续').fontColor(Color.White)
              .backgroundColor($r('app.color.primary')).onClick(() => {
                if (this.loggedIn) { this.contentState = ContentState.CONTENT; } else { this.onLoginTap(); }
              })
          }
        } else {
          if (this.inventoryNotice.length > 0) {
            Text(this.inventoryNotice).width('100%').padding(10).fontSize(11).fontColor($r('app.color.warning'))
          }
          ForEach(this.sessions, (session: ExperienceSession) => {
            Row() {
              Column({ space: 3 }) {
                Text(`${session.starts_at} - ${session.ends_at}`).fontWeight(FontWeight.Medium)
                  .fontColor($r('app.color.text_primary'))
                Text(`${session.status} · 余量 ${session.remaining}/${session.capacity}`).fontSize(11)
                  .fontColor(session.status === SessionStatus.OPEN ? $r('app.color.success') : $r('app.color.warning'))
              }.alignItems(HorizontalAlign.Start).layoutWeight(1)
              Text(this.selectedSessionId === session.id ? '已选' : '选择').fontColor($r('app.color.primary'))
            }.width('100%').padding(13).borderRadius(14).backgroundColor($r('app.color.surface'))
              .border({ width: this.selectedSessionId === session.id ? 2 : 0, color: $r('app.color.primary') })
              .onClick(() => { if (session.status === SessionStatus.OPEN && session.remaining > 0) {
                this.selectedSessionId = session.id; } })
          }, (session: ExperienceSession) => session.id)

          Row({ space: 8 }) {
            Text('同行人数').fontColor($r('app.color.text_primary')).layoutWeight(1)
            Button('−').onClick(() => { this.partySize = Math.max(1, this.partySize - 1); })
            Text(this.partySize.toString()).fontColor($r('app.color.primary'))
            Button('+').onClick(() => { this.partySize = Math.min(8, this.partySize + 1); })
          }.width('100%')
          Row({ space: 8 }) {
            Button(this.operationBusy ? '处理中…' : '预约所选场次').enabled(!this.operationBusy)
              .layoutWeight(1).fontColor(Color.White).backgroundColor($r('app.color.primary'))
              .onClick(() => { this.createReservation(); })
            Button('加入智慧队列').enabled(!this.operationBusy).layoutWeight(1).fontColor($r('app.color.primary'))
              .backgroundColor($r('app.color.surface_tint')).onClick(() => { this.joinQueue(); })
          }.width('100%')
        }

        if (this.queue !== null) {
          Column({ space: 9 }) {
            Row() {
              Text(`模拟队列 ${this.queue.queue_no}`).fontWeight(FontWeight.Bold)
                .fontColor($r('app.color.text_primary')).layoutWeight(1)
              Text(this.queue.status).fontColor(this.queue.status === QueueStatus.CALLED ?
                $r('app.color.error') : $r('app.color.warning'))
            }.width('100%')
            Text(`预计等待 ${this.queue.estimated_wait_minutes} 分钟 · sequence=${this.queue.sequence}`)
              .width('100%').fontColor($r('app.color.primary'))
            Text(`${this.queueSocketMessage} · source=simulated`).width('100%').fontSize(10)
              .fontColor(this.queueSocketState === QueueSocketState.CONNECTED ?
                $r('app.color.success') : $r('app.color.warning'))
            Row() {
              Text('接近叫号应用内提醒（未接系统通知）').fontSize(11)
                .fontColor($r('app.color.text_secondary')).layoutWeight(1)
              Toggle({ type: ToggleType.Switch, isOn: this.reminderEnabled })
                .onChange((value: boolean) => { this.reminderEnabled = value; })
            }.width('100%')
            ForEach(this.queue.nearby_recommendations, (recommendation: NearbyRecommendation) => {
              Text(`${recommendation.name} · 步行 ${recommendation.walk_minutes} 分钟 · ${recommendation.reason}`)
                .width('100%').padding(9).fontSize(11).fontColor($r('app.color.primary'))
                .backgroundColor($r('app.color.surface_tint')).borderRadius(10)
            }, (recommendation: NearbyRecommendation) => recommendation.ref_id)
            if (!isTerminalQueueStatus(this.queue.status)) {
              Row({ space: 7 }) {
                Button('刷新').enabled(!this.operationBusy).fontSize(11).onClick(() => { this.refreshQueue(); })
                Button('离队').enabled(!this.operationBusy).fontSize(11).fontColor($r('app.color.error'))
                  .onClick(() => { this.leaveQueue(); })
                if (this.queuedExperience() !== null && this.queuedExperience()?.fastpass_allowed &&
                  this.fastPass === null) {
                  Button(`FastPass ${formatMoney(this.queuedExperience()?.fastpass_price_cents ?? 0)}`)
                    .enabled(!this.operationBusy).fontSize(11).fontColor($r('app.color.warning'))
                    .onClick(() => { this.buyFastPass(); })
                }
              }.width('100%')
            } else {
              Text(this.operationMessage).width('100%').padding(9).fontSize(11)
                .fontColor($r('app.color.text_secondary')).backgroundColor($r('app.color.surface_tint'))
                .borderRadius(10)
            }
            if (this.fastPass !== null) {
              Text(`FastPass ${this.fastPass.code} · ${formatMoney(this.fastPass.price_cents)} · ` +
                `provider=${this.fastPass.provider}/demo=${this.fastPass.is_demo} · 未接真实支付`)
                .width('100%').fontSize(10).fontColor($r('app.color.warning'))
            }
            if (this.replanAvailable) {
              Button('应用排队联动').width('100%').fontColor(Color.White).backgroundColor($r('app.color.primary'))
                .enabled(!this.operationBusy)
                .onClick(() => { this.applyQueueReplan(); })
            }
          }.width('100%').padding(15).borderRadius(18).backgroundColor($r('app.color.surface'))
        }

        if (this.reservations.length > 0) {
          Text('我的项目预约').width('100%').fontSize(17).fontWeight(FontWeight.Bold)
            .fontColor($r('app.color.text_primary'))
          ForEach(this.reservations.filter((value: Reservation) => value.kind === ReservationKind.EXPERIENCE),
            (value: Reservation) => { this.reservationCard(value) },
            (value: Reservation) => reservationRenderKey(value))
          TextInput({ text: this.cancelReason, placeholder: '取消预约原因' }).width('100%')
            .fontColor($r('app.color.text_primary')).backgroundColor($r('app.color.surface'))
            .onChange((value: string) => { this.cancelReason = value; })
        }

        if (this.operationMessage.length > 0) {
          Text(this.operationMessage).width('100%').padding(10).borderRadius(10).fontSize(11)
            .fontColor($r('app.color.warning')).backgroundColor($r('app.color.surface_tint'))
        }
      }.width('100%').padding({ left: 16, right: 16, top: 14, bottom: 30 })
    }.width('100%').height('100%').scrollBar(BarState.Off)
  }
}
