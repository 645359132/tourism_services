import { StatePanel } from '../components/StatePanel';
import { ContentState } from '../models/AppModels';
import {
  Itinerary,
  ItineraryConflict,
  ItineraryConflictResponse,
  ItineraryGenerateRequest,
  ItineraryItem,
  ItinerarySuggestion
} from '../models/GuideModels';
import { ApiErrorCode, ApiErrorInfo } from '../network/ApiError';
import { NetworkResult } from '../network/HttpClient';
import { ItineraryService } from '../network/services/ItineraryService';
import { AppStore } from '../stores/AppStore';
import { AccessibilitySettings, AccessibilityStore } from '../stores/AccessibilityStore';
import { AuthStore } from '../stores/AuthStore';
import { TravelPersistenceStore } from '../stores/TravelPersistenceStore';
import {
  GuideRuleResult,
  ReplanAssessment,
  TimelineConflictDisplay,
  assessReplan,
  findTimelineConflict,
  itineraryActionLabel,
  itineraryCrowdLabel,
  itineraryKindLabel,
  itinerarySeverityLabel,
  localizeItineraryText,
  localizeItineraryTexts,
  validateItineraryGenerateInput
} from '../utils/GuideRules';

@Component
export struct TripPage {
  @Prop loggedIn: boolean = false;
  onLoginTap: () => void = (): void => {};
  @State visitDate: string =
    new Date(Date.now() + (24 + 8) * 60 * 60 * 1000).toISOString().substring(0, 10);
  @State startTime: string = '09:00';
  @State durationMinutes: number = 360;
  @State interests: string[] = ['culture', 'nature'];
  @State companionType: string = 'family';
  @State fitnessLevel: string = 'medium';
  @State accessible: boolean = false;
  @State itinerary: Itinerary | null = null;
  @State conflictResult: ItineraryConflictResponse | null = null;
  @State contentState: ContentState = ContentState.CONTENT;
  @State operationBusy: boolean = false;
  @State operationMessage: string = '';
  @State requireLogin: boolean = false;
  private service: ItineraryService = new ItineraryService();

  aboutToAppear(): void {
    const settings: AccessibilitySettings = AccessibilityStore.getInstance().getSettings();
    this.accessible = settings.wheelchair || settings.stroller;
    if (this.loggedIn && this.itinerary === null) {
      const cached: Itinerary | null = TravelPersistenceStore.getInstance().loadItinerary(
        AuthStore.getInstance().getUserId());
      if (cached !== null) {
        this.itinerary = cached;
        this.syncCurrentItinerary(cached);
        this.operationMessage = '已恢复本地缓存行程，联网后可刷新版本';
      }
    }
  }

  private syncCurrentItinerary(value: Itinerary): void {
    AppStore.getInstance().setCurrentItinerary(value.id, value.revision);
    TravelPersistenceStore.getInstance().saveItinerary(AuthStore.getInstance().getUserId(), value);
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
    return error === null ? '行程服务请求失败，请稍后重试' : error.userMessage;
  }

  private createInput(): ItineraryGenerateRequest {
    const input: ItineraryGenerateRequest = new ItineraryGenerateRequest();
    input.visit_date = this.visitDate;
    input.start_time = this.startTime;
    input.duration_minutes = this.durationMinutes;
    input.interests = this.interests.slice();
    input.companion_type = this.companionType;
    input.fitness_level = this.fitnessLevel;
    input.accessible = this.accessible;
    return input;
  }

  private toggleInterest(value: string): void {
    const updated: string[] = [];
    let existed: boolean = false;
    for (let index: number = 0; index < this.interests.length; index++) {
      if (this.interests[index] === value) {
        existed = true;
      } else {
        updated.push(this.interests[index]);
      }
    }
    if (!existed) {
      updated.push(value);
    }
    this.interests = updated;
  }

  private hasInterest(value: string): boolean {
    for (let index: number = 0; index < this.interests.length; index++) {
      if (this.interests[index] === value) {
        return true;
      }
    }
    return false;
  }

  private async generate(): Promise<void> {
    if (!this.loggedIn) {
      this.requireLogin = true;
      this.contentState = ContentState.NO_PERMISSION;
      this.operationMessage = '登录后由服务端规则引擎生成并保存行程';
      return;
    }
    const input: ItineraryGenerateRequest = this.createInput();
    const validation: GuideRuleResult = validateItineraryGenerateInput(input);
    if (!validation.valid) {
      this.contentState = ContentState.ERROR;
      this.operationMessage = validation.message;
      return;
    }
    this.operationBusy = true;
    this.contentState = ContentState.LOADING;
    this.operationMessage = '';
    const result: NetworkResult<Itinerary> = await this.service.generate(input);
    this.operationBusy = false;
    if (!result.successful || result.data === null) {
      this.contentState = this.stateForError(result.error);
      this.operationMessage = this.errorText(result.error);
      return;
    }
    this.itinerary = result.data;
    this.syncCurrentItinerary(result.data);
    this.conflictResult = null;
    this.contentState = result.data.items.length === 0 ? ContentState.EMPTY : ContentState.CONTENT;
    this.requireLogin = false;
    this.operationMessage = '规则行程已生成；未调用外部智能模型';
  }

  private async refreshItinerary(): Promise<void> {
    if (this.itinerary === null) {
      return;
    }
    this.operationBusy = true;
    const result: NetworkResult<Itinerary> = await this.service.getItinerary(this.itinerary.id);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.itinerary = result.data;
      this.syncCurrentItinerary(result.data);
      this.contentState = result.data.items.length === 0 ? ContentState.EMPTY : ContentState.CONTENT;
      this.operationMessage = `已刷新到版本 ${result.data.revision}`;
    } else {
      this.contentState = this.stateForError(result.error);
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async checkConflicts(): Promise<void> {
    if (this.itinerary === null) {
      return;
    }
    this.operationBusy = true;
    const result: NetworkResult<ItineraryConflictResponse> =
      await this.service.checkConflicts(this.itinerary.id, 10);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.conflictResult = result.data;
      this.operationMessage = result.data.feasible ? '冲突检查通过，已计入 10 分钟步行缓冲' :
        '检测到冲突，请查看服务端建议';
    } else {
      this.contentState = this.stateForError(result.error);
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async replan(): Promise<void> {
    if (this.itinerary === null) {
      return;
    }
    const previous: Itinerary = this.itinerary;
    this.operationBusy = true;
    const result: NetworkResult<Itinerary> = await this.service.replan(previous.id, previous.revision);
    this.operationBusy = false;
    if (!result.successful || result.data === null) {
      this.contentState = this.stateForError(result.error);
      this.operationMessage = result.error !== null && result.error.statusCode === 409 ?
        '行程版本已变化，请刷新后重试' : this.errorText(result.error);
      return;
    }
    // 创新点 3：服务端负责重排，客户端仍二次验收版本递增及锁定预约不被移动，避免旧响应覆盖承诺行程。
    const assessment: ReplanAssessment = assessReplan(previous, result.data);
    if (!assessment.accepted) {
      this.contentState = ContentState.ERROR;
      this.operationMessage = assessment.message;
      return;
    }
    this.itinerary = result.data;
    this.syncCurrentItinerary(result.data);
    this.conflictResult = null;
    this.contentState = result.data.items.length === 0 ? ContentState.EMPTY : ContentState.CONTENT;
    this.operationMessage = assessment.message;
  }

  private timeText(value: string): string {
    const parsed: number = Date.parse(value);
    if (Number.isNaN(parsed)) {
      return value.length >= 16 ? value.substring(11, 16) : value;
    }
    return new Date(parsed + 8 * 60 * 60 * 1000).toISOString().substring(11, 16);
  }

  @Builder
  private optionButton(label: string, value: string, selectedValue: string, kind: string) {
    Button(label)
      .fontSize(12)
      .fontColor(selectedValue === value ? Color.White : $r('app.color.primary'))
      .backgroundColor(selectedValue === value ? $r('app.color.primary') : $r('app.color.surface_tint'))
      .onClick(() => {
        if (kind === 'companion') {
          this.companionType = value;
        } else {
          this.fitnessLevel = value;
        }
      })
  }

  @Builder
  private interestButton(label: string, value: string) {
    Button(label)
      .fontSize(12)
      .fontColor(this.hasInterest(value) ? Color.White : $r('app.color.primary'))
      .backgroundColor(this.hasInterest(value) ? $r('app.color.primary') : $r('app.color.surface_tint'))
      .onClick(() => {
        this.toggleInterest(value);
      })
  }

  @Builder
  private timelineItem(item: ItineraryItem) {
    Row({ space: 12 }) {
      Column({ space: 2 }) {
        Text(this.timeText(item.start_at))
          .fontSize(14)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.primary'))
        Text(this.timeText(item.end_at))
          .fontSize(11)
          .fontColor($r('app.color.text_secondary'))
      }
      .width(50)
      Column({ space: 5 }) {
        Row() {
          Text(item.title)
            .fontSize(16)
            .fontWeight(FontWeight.Medium)
            .fontColor($r('app.color.text_primary'))
            .layoutWeight(1)
          if (item.locked) {
            Text('🔒 锁定预约')
              .fontSize(10)
              .fontColor($r('app.color.warning'))
          }
        }
        .width('100%')
        Text(`${itineraryKindLabel(item.kind)} · 步行 ${item.walk_minutes} 分钟 · ` +
          `模拟人流：${itineraryCrowdLabel(item.crowd_level)}`)
          .fontSize(11)
          .fontColor($r('app.color.text_secondary'))
        // 创新点 1：展示层兼容历史英文评分说明，旧缓存无需迁移也能与新中文响应一致呈现。
        Text(localizeItineraryTexts(item.explanation).join(' · '))
          .fontSize(11)
          .fontColor($r('app.color.primary'))
          .maxLines(2)
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
    }
    .width('100%')
    .padding(15)
    .borderRadius(17)
    .border({ width: item.locked ? 2 : 0, color: $r('app.color.warning') })
    .backgroundColor($r('app.color.surface'))
  }

  build() {
    Scroll() {
      Column({ space: 16 }) {
        Column({ space: 12 }) {
          Row() {
            Column({ space: 3 }) {
              Text('规则行程管家')
                .fontSize(22)
                .fontWeight(FontWeight.Bold)
                .fontColor($r('app.color.text_primary'))
              Text('本地规则引擎 · 使用可解释评分，未连接外部智能模型')
                .fontSize(11)
                .fontColor($r('app.color.warning'))
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)
          }
          .width('100%')

          Row({ space: 8 }) {
            TextInput({ text: this.visitDate, placeholder: 'YYYY-MM-DD' })
              .layoutWeight(1)
              .fontColor($r('app.color.text_primary'))
              .backgroundColor($r('app.color.page_background'))
              .onChange((value: string) => {
                this.visitDate = value;
              })
            TextInput({ text: this.startTime, placeholder: 'HH:mm' })
              .width(100)
              .fontColor($r('app.color.text_primary'))
              .backgroundColor($r('app.color.page_background'))
              .onChange((value: string) => {
                this.startTime = value;
              })
          }
          .width('100%')

          Row({ space: 8 }) {
            Text('游玩时长').fontColor($r('app.color.text_primary')).layoutWeight(1)
            Button('−60').fontSize(11).onClick(() => {
              this.durationMinutes = Math.max(60, this.durationMinutes - 60);
            })
            Text(`${this.durationMinutes} 分钟`).fontColor($r('app.color.primary'))
            Button('+60').fontSize(11).onClick(() => {
              this.durationMinutes = Math.min(720, this.durationMinutes + 60);
            })
          }
          .width('100%')

          Text('兴趣偏好').width('100%').fontSize(14).fontColor($r('app.color.text_primary'))
          Row({ space: 7 }) {
            this.interestButton('文化', 'culture')
            this.interestButton('自然', 'nature')
            this.interestButton('亲子', 'family')
            this.interestButton('休闲', 'relax')
          }
          .width('100%')

          Text('同行人群').width('100%').fontSize(14).fontColor($r('app.color.text_primary'))
          Row({ space: 7 }) {
            this.optionButton('独自', 'solo', this.companionType, 'companion')
            this.optionButton('家庭', 'family', this.companionType, 'companion')
            this.optionButton('朋友', 'friends', this.companionType, 'companion')
            this.optionButton('长者', 'senior', this.companionType, 'companion')
          }
          .width('100%')

          Row() {
            Column({ space: 5 }) {
              Text('体力等级').fontSize(14).fontColor($r('app.color.text_primary'))
              Row({ space: 6 }) {
                this.optionButton('低', 'low', this.fitnessLevel, 'fitness')
                this.optionButton('中', 'medium', this.fitnessLevel, 'fitness')
                this.optionButton('高', 'high', this.fitnessLevel, 'fitness')
              }
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)
            Column({ space: 5 }) {
              Text('无障碍路线').fontSize(14).fontColor($r('app.color.text_primary'))
              Toggle({ type: ToggleType.Switch, isOn: this.accessible })
                .selectedColor($r('app.color.primary'))
                .onChange((value: boolean) => {
                  this.accessible = value;
                  if (value) {
                    const settings: AccessibilitySettings = AccessibilityStore.getInstance().getSettings();
                    if (!settings.wheelchair && !settings.stroller) {
                      AccessibilityStore.getInstance().setWheelchair(true);
                    }
                  } else {
                    AccessibilityStore.getInstance().setWheelchair(false);
                    AccessibilityStore.getInstance().setStroller(false);
                  }
                })
            }
          }
          .width('100%')

          Button(this.operationBusy ? '生成中…' : '生成真实规则行程')
            .enabled(!this.operationBusy)
            .width('100%')
            .height(46)
            .fontColor(Color.White)
            .backgroundColor($r('app.color.primary'))
            .onClick(() => {
              this.generate();
            })
        }
        .width('100%')
        .padding(17)
        .borderRadius(20)
        .backgroundColor($r('app.color.surface'))

        if (this.contentState !== ContentState.CONTENT) {
          StatePanel({
            state: this.contentState,
            message: this.operationMessage,
            onRetry: (): void => {
              if (this.itinerary === null) {
                this.generate();
              } else {
                this.refreshItinerary();
              }
            }
          })
          if (this.contentState === ContentState.NO_PERMISSION) {
            Button(this.loggedIn ? '继续生成行程' : '登录后生成行程')
              .width('100%')
              .fontColor(Color.White)
              .backgroundColor($r('app.color.primary'))
              .onClick(() => {
                if (this.loggedIn) {
                  this.generate();
                } else {
                  this.onLoginTap();
                }
              })
          }
        }

        if (this.itinerary !== null) {
          Row() {
            Column({ space: 4 }) {
              Text(this.itinerary.name)
                .fontSize(20)
                .fontWeight(FontWeight.Bold)
                .fontColor($r('app.color.text_primary'))
              Text(`${this.itinerary.visit_date} · 版本 ${this.itinerary.revision} · ` +
                `评分 ${this.itinerary.total_score}`)
                .fontSize(11)
                .fontColor($r('app.color.text_secondary'))
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)
            Button('刷新版本').fontSize(11).onClick(() => {
              this.refreshItinerary();
            })
          }
          .width('100%')

          Text(localizeItineraryTexts(this.itinerary.explanation).join(' · '))
            .width('100%')
            .padding(12)
            .borderRadius(13)
            .fontSize(11)
            .fontColor($r('app.color.primary'))
            .backgroundColor($r('app.color.surface_tint'))

          if (!this.itinerary.is_complete) {
            Text(`未完全排入：${localizeItineraryTexts(this.itinerary.unscheduled_reasons).join(' · ')}`)
              .width('100%')
              .padding(12)
              .borderRadius(13)
              .fontSize(11)
              .fontColor($r('app.color.warning'))
              .backgroundColor($r('app.color.surface'))
          }

          ForEach(this.itinerary.items, (item: ItineraryItem) => {
            this.timelineItem(item)
          }, (item: ItineraryItem) => item.id)

          Text(findTimelineConflict(this.itinerary.items).message)
            .width('100%')
            .fontSize(11)
            .fontColor(findTimelineConflict(this.itinerary.items).conflicted ? $r('app.color.error') : $r('app.color.success'))

          Row({ space: 8 }) {
            Button('服务端冲突检查')
              .layoutWeight(1)
              .fontSize(12)
              .fontColor($r('app.color.primary'))
              .backgroundColor($r('app.color.surface_tint'))
              .onClick(() => {
                this.checkConflicts();
              })
            Button('按最新模拟人流重排')
              .layoutWeight(1)
              .fontSize(12)
              .fontColor(Color.White)
              .backgroundColor($r('app.color.primary'))
              .onClick(() => {
                this.replan();
              })
          }
          .width('100%')

          Text('重排时会保留锁定预约；客户端也会拒绝任何移动锁定预约的结果。')
            .width('100%')
            .fontSize(10)
            .fontColor($r('app.color.warning'))

          if (this.conflictResult !== null) {
            Column({ space: 9 }) {
              Text(this.conflictResult.feasible ? '可执行' : '发现冲突')
                .width('100%')
                .fontSize(17)
                .fontWeight(FontWeight.Bold)
                .fontColor(this.conflictResult.feasible ? $r('app.color.success') : $r('app.color.error'))
              ForEach(this.conflictResult.conflicts, (conflict: ItineraryConflict) => {
                Text(`[${itinerarySeverityLabel(conflict.severity)}] ${localizeItineraryText(conflict.message)}`)
                  .width('100%')
                  .fontSize(12)
                  .fontColor(conflict.severity === 'ERROR' ? $r('app.color.error') : $r('app.color.warning'))
              }, (conflict: ItineraryConflict) => `${conflict.code}:${conflict.item_ids.join(',')}`)
              ForEach(this.conflictResult.suggestions, (suggestion: ItinerarySuggestion) => {
                Text(`建议${itineraryActionLabel(suggestion.action)}：${localizeItineraryText(suggestion.message)}`)
                  .width('100%')
                  .fontSize(11)
                  .fontColor($r('app.color.primary'))
              }, (suggestion: ItinerarySuggestion) => `${suggestion.action}:${suggestion.item_id}`)
            }
            .width('100%')
            .padding(15)
            .borderRadius(17)
            .backgroundColor($r('app.color.surface'))
          }
        }

        if (this.operationMessage.length > 0 && this.contentState === ContentState.CONTENT) {
          Text(this.operationMessage)
            .width('100%')
            .padding(11)
            .borderRadius(12)
            .fontSize(11)
            .fontColor($r('app.color.warning'))
            .backgroundColor($r('app.color.surface_tint'))
        }
      }
      .width('100%')
      .constraintSize({ maxWidth: 820 })
      .padding({ left: 18, right: 18, top: 18, bottom: 30 })
    }
    .width('100%')
    .height('100%')
    .scrollBar(BarState.Off)
    .backgroundColor($r('app.color.page_background'))
  }
}
