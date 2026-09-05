import { StatePanel } from '../StatePanel';
import { ContentState } from '../../models/AppModels';
import {
  AvailabilityBucket,
  AvailabilityResponse,
  BundleComponent,
  HospitalityOffer,
  HospitalityOfferListResponse,
  OfferKind,
  Reservation,
  ReservationKind,
  ReservationListResponse,
  ReservationStatus,
  ReviewResponse,
  Venue,
  VenueKind,
  VenueListResponse
} from '../../models/BookingModels';
import { ApiErrorCode, ApiErrorInfo } from '../../network/ApiError';
import { NetworkResult } from '../../network/HttpClient';
import { BookingService } from '../../network/services/BookingService';
import {
  BookingRuleResult,
  hasActiveStayConflict,
  isCurrentAvailableTimedBucket,
  reservationRenderKey,
  reservationStatusLabel,
  shanghaiDateAfterDays,
  validateBookingDate,
  validateReview,
  validateStayBooking,
  validateTimedBooking
} from '../../utils/BookingRules';
import { PendingIdempotentOperation, formatMoney } from '../../utils/TicketRules';
import { formatShanghaiDateTime, formatShanghaiRange } from '../../utils/DateTimeRules';

@Component
export struct HospitalityBookingView {
  @Prop loggedIn: boolean = false;
  onLoginTap: () => void = (): void => {};
  @State contentState: ContentState = ContentState.LOADING;
  @State selectedKind: OfferKind = OfferKind.ROOM;
  @State venues: Venue[] = [];
  @State offers: HospitalityOffer[] = [];
  @State selectedOfferId: string = '';
  @State availability: AvailabilityBucket[] = [];
  @State dateFrom: string = shanghaiDateAfterDays(1);
  @State dateTo: string = shanghaiDateAfterDays(2);
  @State startsAt: string = '';
  @State quantity: number = 1;
  @State partySize: number = 2;
  @State reservations: Reservation[] = [];
  @State operationMessage: string = '';
  @State operationBusy: boolean = false;
  @State inventoryNotice: string = '';
  @State reviewReservationId: string = '';
  @State reviewRating: number = 5;
  @State reviewContent: string = '服务体验很好';
  @State cancelReason: string = '游客行程调整';
  private service: BookingService = new BookingService();
  private bookingPending: PendingIdempotentOperation = new PendingIdempotentOperation();
  private confirmPending: PendingIdempotentOperation = new PendingIdempotentOperation();
  private cancelPending: PendingIdempotentOperation = new PendingIdempotentOperation();
  private availabilityRequestVersion: number = 0;

  aboutToAppear(): void {
    this.loadCatalog();
    if (this.loggedIn) {
      this.loadReservations();
    }
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
    return error === null ? '餐住服务请求失败，请稍后重试' : error.userMessage;
  }

  private resolveFailure(pending: PendingIdempotentOperation, error: ApiErrorInfo | null): void {
    if (error !== null) {
      pending.resolveFailure(error.statusCode, error.retriable);
    }
  }

  private filteredOffers(): HospitalityOffer[] {
    return this.offers.filter((value: HospitalityOffer) => value.kind === this.selectedKind);
  }

  private selectedOffer(): HospitalityOffer | null {
    for (let index: number = 0; index < this.offers.length; index++) {
      if (this.offers[index].id === this.selectedOfferId) {
        return this.offers[index];
      }
    }
    return null;
  }

  private venueFor(venueId: string): Venue | null {
    for (let index: number = 0; index < this.venues.length; index++) {
      if (this.venues[index].id === venueId) {
        return this.venues[index];
      }
    }
    return null;
  }

  private hasSelectedStayConflict(): boolean {
    return this.selectedKind === OfferKind.ROOM &&
      hasActiveStayConflict(this.reservations, this.dateFrom, this.dateTo);
  }

  private clearAvailabilitySelection(): void {
    // 版本递增会使飞行中的旧查询失效，避免切换产品/日期后迟到响应覆盖新状态。
    this.availabilityRequestVersion++;
    this.availability = [];
    this.startsAt = '';
    this.inventoryNotice = '';
  }

  private async loadCatalog(): Promise<void> {
    this.contentState = ContentState.LOADING;
    const venueResult: NetworkResult<VenueListResponse> = await this.service.listVenues();
    if (!venueResult.successful || venueResult.data === null) {
      this.contentState = this.stateForError(venueResult.error);
      this.operationMessage = this.errorText(venueResult.error);
      return;
    }
    this.venues = venueResult.data.items;
    const offerResult: NetworkResult<HospitalityOfferListResponse> = await this.service.listOffers();
    if (!offerResult.successful || offerResult.data === null) {
      this.contentState = this.stateForError(offerResult.error);
      this.operationMessage = this.errorText(offerResult.error);
      return;
    }
    this.offers = offerResult.data.items;
    const visible: HospitalityOffer[] = this.filteredOffers();
    if (visible.length > 0) {
      this.selectedOfferId = visible[0].id;
    }
    this.contentState = visible.length === 0 ? ContentState.EMPTY : ContentState.CONTENT;
  }

  private async loadReservations(): Promise<boolean> {
    const result: NetworkResult<ReservationListResponse> = await this.service.listReservations();
    if (result.successful && result.data !== null) {
      this.reservations = result.data.items;
      return true;
    }
    return false;
  }

  private switchKind(value: OfferKind): void {
    this.selectedKind = value;
    const visible: HospitalityOffer[] = this.offers.filter((item: HospitalityOffer) => item.kind === value);
    this.selectedOfferId = visible.length > 0 ? visible[0].id : '';
    this.clearAvailabilitySelection();
    this.contentState = visible.length > 0 ? ContentState.CONTENT : ContentState.EMPTY;
  }

  private async checkAvailability(announce: boolean = true): Promise<void> {
    if (this.operationBusy) {
      return;
    }
    const offer: HospitalityOffer | null = this.selectedOffer();
    if (offer === null) {
      this.operationMessage = '请先选择餐住产品';
      return;
    }
    if (!validateBookingDate(this.dateFrom).valid || !validateBookingDate(this.dateTo).valid ||
      this.dateFrom > this.dateTo) {
      this.operationMessage = '请使用 YYYY-MM-DD，并确保查询结束日期不早于开始日期';
      return;
    }
    this.operationBusy = true;
    const requestVersion: number = ++this.availabilityRequestVersion;
    const requestOfferId: string = offer.id;
    const requestDateFrom: string = this.dateFrom;
    const requestDateTo: string = this.dateTo;
    const previous: AvailabilityBucket[] = this.availability.slice();
    // 新查询开始即撤销旧选择，网络失败或空结果时也不能继续提交旧产品/旧日期的时段。
    this.availability = [];
    this.startsAt = '';
    this.inventoryNotice = '';
    const result: NetworkResult<AvailabilityResponse> = await this.service.getAvailability(
      requestOfferId, requestDateFrom, requestDateTo);
    this.operationBusy = false;
    if (requestVersion !== this.availabilityRequestVersion || this.selectedOfferId !== requestOfferId ||
      this.dateFrom !== requestDateFrom || this.dateTo !== requestDateTo) {
      this.operationMessage = announce ? '查询条件已变化，请按当前条件重新查询库存' : this.operationMessage;
      return;
    }
    if (!result.successful || result.data === null) {
      if (announce) {
        this.contentState = this.stateForError(result.error);
        this.operationMessage = this.errorText(result.error);
      }
      return;
    }
    this.availability = result.data.items;
    if (previous.length > 0 && this.availability.length > 0 &&
      previous[0].remaining !== this.availability[0].remaining) {
      this.inventoryNotice = `库存已从 ${previous[0].remaining} 更新为 ${this.availability[0].remaining}`;
    }
    for (let index: number = 0; index < this.availability.length; index++) {
      if (this.availability[index].remaining > 0) {
        this.startsAt = this.availability[index].start_at;
        break;
      }
    }
    if (announce) {
      this.contentState = this.availability.length === 0 ? ContentState.EMPTY : ContentState.CONTENT;
      this.operationMessage = this.availability.length === 0 ? '当前日期范围无可用库存' : '已读取真实库存';
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

  private async bookSelected(): Promise<void> {
    if (this.operationBusy) {
      return;
    }
    if (!this.loggedIn) {
      this.contentState = ContentState.NO_PERMISSION;
      this.operationMessage = '登录后才能提交真实餐住预约';
      return;
    }
    const offer: HospitalityOffer | null = this.selectedOffer();
    if (offer === null) {
      this.operationMessage = '请先选择餐住产品';
      return;
    }
    const bookingKind: OfferKind = this.selectedKind;
    const bookingDateFrom: string = this.dateFrom;
    const bookingDateTo: string = this.dateTo;
    const bookingStartsAt: string = this.startsAt;
    const bookingQuantity: number = this.quantity;
    const bookingPartySize: number = this.partySize;
    if (bookingPartySize > offer.max_party_size) {
      this.operationMessage = `该产品最多接待 ${offer.max_party_size} 人`;
      return;
    }
    let validation: BookingRuleResult = new BookingRuleResult(true, '');
    if (bookingKind === OfferKind.ROOM) {
      validation = validateStayBooking(bookingDateFrom, bookingDateTo, bookingQuantity, bookingPartySize);
    } else if (bookingKind === OfferKind.MEAL) {
      if (!isCurrentAvailableTimedBucket(
        this.availability, offer.id, bookingStartsAt, bookingDateFrom, bookingDateTo)) {
        this.operationMessage = '请重新查询库存并选择当前餐饮产品的可用时段';
        return;
      }
      validation = validateTimedBooking(bookingStartsAt, bookingPartySize);
    } else {
      validation = validateTimedBooking(`${bookingDateFrom}T09:00`, bookingPartySize);
    }
    if (!validation.valid) {
      this.operationMessage = validation.message;
      return;
    }
    this.operationBusy = true;
    const reservationsCurrent: boolean = await this.loadReservations();
    if (!reservationsCurrent) {
      this.operationBusy = false;
      this.operationMessage = '无法刷新已有预约，请检查网络后重试';
      return;
    }
    if (bookingKind === OfferKind.ROOM && hasActiveStayConflict(
      this.reservations, bookingDateFrom, bookingDateTo)) {
      this.operationBusy = false;
      this.operationMessage = '所选日期已有待确认或已确认的住宿，请先处理下方已有预约';
      return;
    }
    const operationId: string = `${offer.id}:${bookingDateFrom}:${bookingDateTo}:${bookingStartsAt}:` +
      `${bookingQuantity}:${bookingPartySize}`;
    const key: string = this.bookingPending.getOrCreate(operationId, 'hospitality-booking');
    let result: NetworkResult<Reservation>;
    if (bookingKind === OfferKind.ROOM) {
      result = await this.service.bookStay(offer.id, bookingDateFrom, bookingDateTo,
        bookingQuantity, bookingPartySize, key);
    } else if (bookingKind === OfferKind.MEAL) {
      result = await this.service.bookDining(offer.id, bookingStartsAt, bookingPartySize, key);
    } else {
      result = await this.service.bookBundle(offer.id, bookingDateFrom, bookingPartySize, key);
    }
    if (result.successful && result.data !== null) {
      this.bookingPending.resolveSuccess();
      this.replaceReservation(result.data);
      await this.loadReservations();
      this.contentState = ContentState.CONTENT;
      this.operationBusy = false;
      await this.checkAvailability(false);
      this.operationMessage = `预约 ${result.data.booking_no} 已创建，请在下方确认`;
    } else {
      this.resolveFailure(this.bookingPending, result.error);
      if (result.error !== null && result.error.statusCode === 409) {
        await this.loadReservations();
      }
      this.operationBusy = false;
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async confirm(value: Reservation): Promise<void> {
    if (this.operationBusy) {
      return;
    }
    this.operationBusy = true;
    const key: string = this.confirmPending.getOrCreate(value.id, 'hospitality-confirm');
    const result: NetworkResult<Reservation> = await this.service.confirmReservation(value.id, key);
    if (result.successful && result.data !== null) {
      this.confirmPending.resolveSuccess();
      this.replaceReservation(result.data);
      await this.loadReservations();
      this.operationMessage = '餐住预约已确认；未发生真实支付';
    } else {
      this.resolveFailure(this.confirmPending, result.error);
      if (result.error !== null && result.error.statusCode === 409) {
        await this.loadReservations();
      }
      this.operationMessage = this.errorText(result.error);
    }
    this.operationBusy = false;
  }

  private async cancel(value: Reservation): Promise<void> {
    if (this.operationBusy) {
      return;
    }
    if (this.cancelReason.trim().length === 0) {
      this.operationMessage = '请填写取消原因';
      return;
    }
    this.operationBusy = true;
    const operationId: string = `${value.id}:${this.cancelReason.trim()}`;
    const key: string = this.cancelPending.getOrCreate(operationId, 'hospitality-cancel');
    const result: NetworkResult<Reservation> = await this.service.cancelReservation(
      value.id, this.cancelReason.trim(), key);
    if (result.successful && result.data !== null) {
      this.cancelPending.resolveSuccess();
      this.replaceReservation(result.data);
      await this.loadReservations();
      this.operationMessage = '餐住预约已取消';
    } else {
      this.resolveFailure(this.cancelPending, result.error);
      if (result.error !== null && result.error.statusCode === 409) {
        await this.loadReservations();
      }
      this.operationMessage = this.errorText(result.error);
    }
    this.operationBusy = false;
  }

  private async submitReview(value: Reservation): Promise<void> {
    if (this.operationBusy) {
      return;
    }
    const validation: BookingRuleResult = validateReview(this.reviewRating, this.reviewContent);
    if (!validation.valid) { this.operationMessage = validation.message; return; }
    this.operationBusy = true;
    const result: NetworkResult<ReviewResponse> = await this.service.createReview(
      value.id, this.reviewRating, this.reviewContent.trim());
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.reviewReservationId = ''; this.operationMessage = `评价已提交，状态 ${result.data.status}`;
    } else { this.operationMessage = this.errorText(result.error); }
  }

  @Builder
  private kindButton(label: string, value: OfferKind) {
    Button(label).layoutWeight(1).fontSize(12)
      .fontColor(this.selectedKind === value ? Color.White : $r('app.color.primary'))
      .backgroundColor(this.selectedKind === value ? $r('app.color.primary') : $r('app.color.surface_tint'))
      .onClick(() => { this.switchKind(value); })
  }

  @Builder
  private offerCard(value: HospitalityOffer) {
    Column({ space: 5 }) {
      Text(value.name).width('100%').fontWeight(FontWeight.Bold)
        .fontColor(this.selectedOfferId === value.id ? Color.White : $r('app.color.text_primary'))
      Text(value.description).width('100%').fontSize(11).maxLines(2)
        .fontColor(this.selectedOfferId === value.id ? '#E8F2FF' : $r('app.color.text_secondary'))
      Text(`${formatMoney(value.base_price_cents)} · 容量 ${value.capacity}`).fontSize(12)
        .fontColor(this.selectedOfferId === value.id ? Color.White : $r('app.color.error'))
      Text(`最多 ${value.max_party_size} 人 · provider=${value.provider}/demo=${value.is_demo}`).width('100%')
        .fontSize(9).fontColor(this.selectedOfferId === value.id ? '#E8F2FF' : $r('app.color.warning'))
      Text(`设施/属性：${value.attributes.join('、')}`).width('100%').fontSize(10).maxLines(1)
        .fontColor(this.selectedOfferId === value.id ? '#E8F2FF' : $r('app.color.text_secondary'))
    }.width('48%').height(146).padding(13).borderRadius(16)
      .backgroundColor(this.selectedOfferId === value.id ? $r('app.color.primary') : $r('app.color.surface'))
      .onClick(() => {
        this.selectedOfferId = value.id;
        this.clearAvailabilitySelection();
      })
  }

  build() {
    Scroll() {
      Column({ space: 14 }) {
        Text('餐住真实预约').width('100%').fontSize(20).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.text_primary'))
        Text('酒店/民宿/餐厅目录与库存来自 API；provider=demo，不代表真实商家、支付或履约已接入。')
          .width('100%').fontSize(11).fontColor($r('app.color.warning'))

        Row({ space: 7 }) {
          this.kindButton('酒店/民宿房型', OfferKind.ROOM)
          this.kindButton('餐厅/套餐时段', OfferKind.MEAL)
          this.kindButton('住玩/餐玩组合', OfferKind.BUNDLE)
        }.width('100%')

        Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.SpaceBetween }) {
          ForEach(this.filteredOffers(), (value: HospitalityOffer) => { this.offerCard(value) },
            (value: HospitalityOffer) => value.id)
        }.width('100%')

        if (this.selectedOffer() !== null && this.venueFor(this.selectedOffer()?.venue_id ?? '') !== null) {
          Text(`${this.venueFor(this.selectedOffer()?.venue_id ?? '')?.kind} · ` +
            `${this.venueFor(this.selectedOffer()?.venue_id ?? '')?.name} · ` +
            `评分 ${this.venueFor(this.selectedOffer()?.venue_id ?? '')?.rating} · ` +
            `设施 ${this.venueFor(this.selectedOffer()?.venue_id ?? '')?.amenities.join('、')}`)
            .width('100%').padding(10).fontSize(11).fontColor($r('app.color.primary'))
            .backgroundColor($r('app.color.surface_tint')).borderRadius(10)
          Text(`${this.venueFor(this.selectedOffer()?.venue_id ?? '')?.description} · 无障碍：` +
            `${this.venueFor(this.selectedOffer()?.venue_id ?? '')?.accessibility.join('、')}`)
            .width('100%').fontSize(10).fontColor($r('app.color.text_secondary'))
        }

        if (this.selectedKind === OfferKind.BUNDLE && this.selectedOffer() !== null) {
          Column({ space: 5 }) {
            Text('组合包含').width('100%').fontWeight(FontWeight.Medium).fontColor($r('app.color.text_primary'))
            ForEach(this.selectedOffer()?.bundle_components ?? [], (component: BundleComponent) => {
              Text(`${component.name} × ${component.quantity} · 第 ${component.offset_minutes} 分钟开始`)
                .width('100%').fontSize(11).fontColor($r('app.color.primary'))
            }, (component: BundleComponent) => `${component.kind}:${component.ref_id}:${component.offset_minutes}`)
          }.width('100%').padding(11).borderRadius(12).backgroundColor($r('app.color.surface_tint'))
        }

        Row({ space: 8 }) {
          TextInput({ text: this.dateFrom, placeholder: this.selectedKind === OfferKind.ROOM ? '入住日期' : '游玩日期' })
            .layoutWeight(1).fontColor($r('app.color.text_primary')).backgroundColor($r('app.color.surface'))
            .onChange((value: string) => {
              this.dateFrom = value;
              this.clearAvailabilitySelection();
            })
          TextInput({ text: this.dateTo, placeholder: '离店/查询结束日期' }).layoutWeight(1)
            .fontColor($r('app.color.text_primary')).backgroundColor($r('app.color.surface'))
            .onChange((value: string) => {
              this.dateTo = value;
              this.clearAvailabilitySelection();
            })
          Button('查库存').fontColor(Color.White).backgroundColor($r('app.color.primary'))
            .onClick(() => { this.checkAvailability(); })
        }.width('100%')

        if (this.contentState !== ContentState.CONTENT) {
          StatePanel({ state: this.contentState, message: this.operationMessage,
            onRetry: (): void => { this.loadCatalog(); } })
          if (this.contentState === ContentState.NO_PERMISSION) {
            Button(this.loggedIn ? '继续' : '登录后继续').fontColor(Color.White)
              .backgroundColor($r('app.color.primary')).onClick(() => {
                if (this.loggedIn) { this.contentState = ContentState.CONTENT; } else { this.onLoginTap(); }
              })
          }
        }

        if (this.inventoryNotice.length > 0) {
          Text(this.inventoryNotice).width('100%').padding(10).fontSize(11).fontColor($r('app.color.warning'))
        }
        ForEach(this.availability, (bucket: AvailabilityBucket) => {
          Row() {
            Column({ space: 3 }) {
              Text(formatShanghaiRange(bucket.start_at, bucket.end_at)).fontColor($r('app.color.text_primary'))
              Text(`余量 ${bucket.remaining} · ${formatMoney(bucket.unit_price_cents)}`).fontSize(11)
                .fontColor(bucket.remaining > 0 ? $r('app.color.success') : $r('app.color.error'))
            }.alignItems(HorizontalAlign.Start).layoutWeight(1)
            Button('选此时段').enabled(bucket.remaining > 0).fontSize(11)
              .onClick(() => { this.startsAt = bucket.start_at; })
          }.width('100%').padding(12).borderRadius(13).backgroundColor($r('app.color.surface'))
        }, (bucket: AvailabilityBucket) => bucket.bucket_id)

        Row({ space: 8 }) {
          Text(`数量 ${this.quantity}`).fontColor($r('app.color.text_primary')).layoutWeight(1)
          Button('−').onClick(() => { this.quantity = Math.max(1, this.quantity - 1); })
          Button('+').onClick(() => { this.quantity = Math.min(4, this.quantity + 1); })
          Text(`同行 ${this.partySize}`).fontColor($r('app.color.text_primary'))
          Button('−').onClick(() => { this.partySize = Math.max(1, this.partySize - 1); })
          Button('+').onClick(() => { this.partySize = Math.min(12, this.partySize + 1); })
        }.width('100%')
        if (this.selectedKind === OfferKind.MEAL) {
          Text(this.startsAt.length > 0 ? `已选餐饮时段：${formatShanghaiDateTime(this.startsAt)}` :
            '请先查询库存并选择餐饮时段')
            .width('100%').padding(10).fontSize(11).fontColor($r('app.color.text_secondary'))
            .backgroundColor($r('app.color.surface')).borderRadius(10)
        }
        if (this.hasSelectedStayConflict()) {
          Text('检测到所选日期已有住宿预约；提交时会先刷新状态')
            .width('100%').fontSize(11).fontColor($r('app.color.warning'))
        }
        Button(this.operationBusy ? '处理中…' : '提交 API 预约')
          .enabled(!this.operationBusy).width('100%')
          .fontColor(Color.White).backgroundColor($r('app.color.primary')).onClick(() => { this.bookSelected(); })

        if (this.reservations.length > 0) {
          Text('我的餐住预约').width('100%').fontSize(17).fontWeight(FontWeight.Bold)
            .fontColor($r('app.color.text_primary'))
          TextInput({ text: this.cancelReason, placeholder: '取消预约原因' }).width('100%')
            .fontColor($r('app.color.text_primary')).backgroundColor($r('app.color.surface'))
            .onChange((value: string) => { this.cancelReason = value; })
          ForEach(this.reservations.filter((value: Reservation) => value.kind !== ReservationKind.EXPERIENCE),
            (value: Reservation) => {
              Column({ space: 6 }) {
                Row() {
                  Text(value.resource_name).fontWeight(FontWeight.Medium).fontColor($r('app.color.text_primary'))
                    .layoutWeight(1)
                  Text(reservationStatusLabel(value.status)).fontSize(11)
                    .fontColor(value.status === ReservationStatus.CONFIRMED ?
                      $r('app.color.success') : $r('app.color.warning'))
                }.width('100%')
                Text(`${formatShanghaiRange(value.starts_at, value.ends_at)} · ${formatMoney(value.total_cents)} · ` +
                  `provider=${value.provider}/demo=${value.is_demo}`).fontSize(10).fontColor($r('app.color.text_secondary'))
                if (value.status === ReservationStatus.HELD) {
                  Row({ space: 8 }) {
                    Button('确认').enabled(!this.operationBusy).fontSize(11).fontColor(Color.White)
                      .backgroundColor($r('app.color.primary'))
                      .onClick(() => { this.confirm(value); })
                    Button('取消').enabled(!this.operationBusy).fontSize(11).fontColor($r('app.color.error'))
                      .onClick(() => { this.cancel(value); })
                  }.width('100%')
                } else if (value.status === ReservationStatus.CONFIRMED) {
                  Button('取消预约').enabled(!this.operationBusy).fontSize(11).fontColor($r('app.color.error'))
                    .onClick(() => { this.cancel(value); })
                } else if (value.status === ReservationStatus.COMPLETED) {
                  Button('评价').enabled(!this.operationBusy).fontSize(11)
                    .onClick(() => { this.reviewReservationId = value.id; })
                }
                if (this.reviewReservationId === value.id) {
                  Column({ space: 7 }) {
                    Row({ space: 6 }) {
                      Button('−').onClick(() => { this.reviewRating = Math.max(1, this.reviewRating - 1); })
                      Text(`${this.reviewRating} 星`).fontColor($r('app.color.primary'))
                      Button('+').onClick(() => { this.reviewRating = Math.min(5, this.reviewRating + 1); })
                    }.width('100%')
                    TextInput({ text: this.reviewContent, placeholder: '评价内容（3-500 字）' }).width('100%')
                      .onChange((text: string) => { this.reviewContent = text; })
                    Row({ space: 8 }) {
                      Button(this.operationBusy ? '提交中…' : '提交评价').enabled(!this.operationBusy)
                        .onClick(() => { this.submitReview(value); })
                      Button('收起').onClick(() => { this.reviewReservationId = ''; })
                    }.width('100%')
                  }.width('100%')
                }
              }.width('100%').padding(13).borderRadius(14).backgroundColor($r('app.color.surface'))
            }, (value: Reservation) => reservationRenderKey(value))
        }
        if (this.operationMessage.length > 0) {
          Text(this.operationMessage).width('100%').padding(10).fontSize(11).fontColor($r('app.color.warning'))
            .backgroundColor($r('app.color.surface_tint')).borderRadius(10)
        }
      }.width('100%').padding({ left: 16, right: 16, top: 14, bottom: 30 })
    }.width('100%').height('100%').scrollBar(BarState.Off)
  }
}
