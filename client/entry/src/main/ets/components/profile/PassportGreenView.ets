import { StatePanel } from '../StatePanel';
import { ContentState } from '../../models/AppModels';
import {
  GreenTask,
  GreenTaskCompletionResponse,
  GreenTaskListResponse,
  PassportCheckInResponse,
  PassportStamp,
  PassportSummary
} from '../../models/JourneyModels';
import { PointsAccount } from '../../models/ShopModels';
import { ApiErrorCode, ApiErrorInfo } from '../../network/ApiError';
import { NetworkResult } from '../../network/HttpClient';
import { JourneyService } from '../../network/services/JourneyService';
import { ShopService } from '../../network/services/ShopService';
import { NetworkStore } from '../../stores/NetworkStore';
import { JourneyRuleResult, validateGreenEvidence } from '../../utils/JourneyRules';
import { PendingIdempotentOperation } from '../../utils/TicketRules';
import { isWideWindow } from '../../utils/ResponsiveRules';

@Component
export struct PassportGreenView {
  @Prop loggedIn: boolean = false;
  onLoginTap: () => void = (): void => {};
  @State passport: PassportSummary | null = null;
  @State tasks: GreenTask[] = [];
  @State pointsAccount: PointsAccount | null = null;
  @State selectedTaskId: string = '';
  @State evidence: string = '已完成演示绿色任务并提交说明';
  @State contentState: ContentState = ContentState.LOADING;
  @State operationBusy: boolean = false;
  @State operationMessage: string = '';
  @State isWide: boolean = false;
  private service: JourneyService = new JourneyService();
  private shopService: ShopService = new ShopService();
  // 创新点 8：同一打卡/任务在可重试失败期间复用幂等键，配合服务端不可变积分流水防止重复入账。
  private checkInPending: PendingIdempotentOperation = new PendingIdempotentOperation();
  private taskPending: PendingIdempotentOperation = new PendingIdempotentOperation();

  aboutToAppear(): void {
    this.loadAll();
  }

  private stateForError(error: ApiErrorInfo | null): ContentState {
    if (error !== null && error.code === ApiErrorCode.OFFLINE) { return ContentState.OFFLINE; }
    if (error !== null && (error.code === ApiErrorCode.UNAUTHORIZED || error.code === ApiErrorCode.FORBIDDEN)) {
      return ContentState.NO_PERMISSION;
    }
    return ContentState.ERROR;
  }

  private errorText(error: ApiErrorInfo | null): string {
    return error === null ? '文化护照与绿色任务请求失败' : error.userMessage;
  }

  private async loadAll(): Promise<void> {
    if (!this.loggedIn) {
      this.contentState = ContentState.NO_PERMISSION;
      return;
    }
    this.contentState = ContentState.LOADING;
    const passportResult: NetworkResult<PassportSummary> = await this.service.getPassport();
    if (!passportResult.successful || passportResult.data === null) {
      this.contentState = this.stateForError(passportResult.error);
      this.operationMessage = this.errorText(passportResult.error);
      return;
    }
    this.passport = passportResult.data;
    const taskResult: NetworkResult<GreenTaskListResponse> = await this.service.listGreenTasks();
    if (!taskResult.successful || taskResult.data === null) {
      this.contentState = this.stateForError(taskResult.error);
      this.operationMessage = this.errorText(taskResult.error);
      return;
    }
    this.tasks = taskResult.data.items;
    if (this.selectedTaskId.length === 0 && this.tasks.length > 0) {
      this.selectedTaskId = this.tasks[0].id;
    }
    // 护照、绿色任务与商城读取同一积分账户，完成操作后整体刷新以展示一致余额。
    const accountResult: NetworkResult<PointsAccount> = await this.shopService.getPointsAccount();
    if (accountResult.successful && accountResult.data !== null) {
      this.pointsAccount = accountResult.data;
    }
    this.contentState = this.passport.stamps.length === 0 && this.tasks.length === 0 ?
      ContentState.EMPTY : ContentState.CONTENT;
  }

  private selectedTask(): GreenTask | null {
    for (let index: number = 0; index < this.tasks.length; index++) {
      if (this.tasks[index].id === this.selectedTaskId) { return this.tasks[index]; }
    }
    return null;
  }

  private async checkIn(value: PassportStamp): Promise<void> {
    if (value.collected || this.operationBusy) { return; }
    // 创新点 8：文化打卡必须在线交给 Provider 验证，不进入可自动重放的通用离线队列。
    if (NetworkStore.getInstance().isOffline()) {
      this.contentState = ContentState.OFFLINE;
      this.operationMessage = '打卡需由服务端验证，未加入通用离线重放队列';
      return;
    }
    const key: string = this.checkInPending.getOrCreate(value.code, 'passport-check-in');
    this.operationBusy = true;
    const result: NetworkResult<PassportCheckInResponse> = await this.service.checkIn(value.code, key);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.checkInPending.resolveSuccess();
      this.operationMessage = `印章 ${result.data.stamp.title} 已收集，奖励 ${result.data.points_awarded} 分，` +
        `账户余额 ${result.data.point_balance}；provider=${result.data.provider}/demo=${result.data.is_demo}`;
      await this.loadAll();
    } else {
      if (result.error !== null) {
        this.checkInPending.resolveFailure(result.error.statusCode, result.error.retriable);
      }
      this.contentState = this.stateForError(result.error);
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async completeTask(): Promise<void> {
    const task: GreenTask | null = this.selectedTask();
    if (task === null || task.completed || this.operationBusy) { return; }
    // 绿色凭证也保持在线验证边界，避免客户端离线自证后直接获得积分。
    if (NetworkStore.getInstance().isOffline()) {
      this.contentState = ContentState.OFFLINE;
      this.operationMessage = '绿色任务凭证需服务端验证，未加入通用离线重放队列';
      return;
    }
    const validation: JourneyRuleResult = validateGreenEvidence(this.evidence);
    if (!validation.valid) { this.operationMessage = validation.message; return; }
    const operationId: string = `${task.id}:${this.evidence.trim()}`;
    const key: string = this.taskPending.getOrCreate(operationId, 'green-task');
    this.operationBusy = true;
    const result: NetworkResult<GreenTaskCompletionResponse> = await this.service.completeGreenTask(
      task.id, this.evidence.trim(), key);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.taskPending.resolveSuccess();
      this.operationMessage = `绿色任务 ${result.data.task_code} 已完成，奖励 ${result.data.points_awarded} 分，` +
        `积分账户余额 ${result.data.point_balance}；provider=${result.data.provider}/demo=${result.data.is_demo}`;
      await this.loadAll();
    } else {
      if (result.error !== null) { this.taskPending.resolveFailure(result.error.statusCode, result.error.retriable); }
      this.contentState = this.stateForError(result.error);
      this.operationMessage = this.errorText(result.error);
    }
  }

  @Builder
  private passportPanel() {
    Column({ space: 8 }) {
      Text('文化数字护照').width('100%').fontSize(18).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.text_primary'))
      Text(`${this.passport?.collected_count ?? 0}/${this.passport?.total_count ?? 0} 枚 · ` +
        `护照累计 ${this.passport?.points_earned ?? 0} 分 · 账户 ${this.passport?.point_balance ?? 0} 分`)
        .width('100%').fontColor($r('app.color.primary'))
      ForEach(this.passport?.stamps ?? [], (stamp: PassportStamp) => {
        Column({ space: 4 }) {
          Row() {
            Text(`${stamp.collected ? '✓' : '○'} ${stamp.title}`).fontWeight(FontWeight.Medium)
              .fontColor(stamp.collected ? $r('app.color.success') : $r('app.color.text_primary')).layoutWeight(1)
            Text(`+${stamp.points_award} 分`).fontSize(10).fontColor($r('app.color.warning'))
          }.width('100%')
          Text(`${stamp.description} · 节点 ${stamp.node_id}`).width('100%').fontSize(9)
            .fontColor($r('app.color.text_secondary'))
          Text(`provider=${stamp.provider}/demo=${stamp.is_demo}`).width('100%').fontSize(7)
            .fontColor($r('app.color.warning'))
          if (!stamp.collected) {
            Button(this.operationBusy ? '处理中…' : '演示到访打卡').enabled(!this.operationBusy).width('100%')
              .fontColor(Color.White).backgroundColor($r('app.color.primary')).onClick(() => { this.checkIn(stamp); })
          }
        }.width('100%').padding(10).borderRadius(12).backgroundColor($r('app.color.surface_tint'))
      }, (stamp: PassportStamp) => stamp.id)
      Text('打卡由 demo_checkin 验证，不代表已接真实定位、NFC 或闸机硬件。').width('100%')
        .fontSize(8).fontColor($r('app.color.warning'))
    }.width('100%').padding(13).borderRadius(16).backgroundColor($r('app.color.surface'))
  }

  @Builder
  private greenPanel() {
    Column({ space: 8 }) {
      Text('绿色任务与积分联动').width('100%').fontSize(18).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.text_primary'))
      Text(`任务账户 ${this.passport?.point_balance ?? 0} 分 · 商城积分账户 ${this.pointsAccount?.balance ?? 0} 分`)
        .width('100%').fontColor($r('app.color.primary'))
      ForEach(this.tasks, (task: GreenTask) => {
        Column({ space: 4 }) {
          Row() {
            Text(`${task.completed ? '✓' : '○'} ${task.title}`).fontWeight(FontWeight.Medium)
              .fontColor(task.completed ? $r('app.color.success') : $r('app.color.text_primary')).layoutWeight(1)
            Text(`+${task.points_award}`).fontColor($r('app.color.warning'))
          }.width('100%')
          Text(`${task.kind} · ${task.description}`).width('100%').fontSize(9)
            .fontColor($r('app.color.text_secondary'))
          Text(`凭证提示：${task.evidence_hint}`).width('100%').fontSize(8).fontColor($r('app.color.primary'))
        }.width('100%').padding(10).borderRadius(12)
          .backgroundColor(this.selectedTaskId === task.id ? $r('app.color.surface_tint') : $r('app.color.surface'))
          .border({ width: this.selectedTaskId === task.id ? 2 : 0, color: $r('app.color.primary') })
          .onClick(() => { this.selectedTaskId = task.id; })
      }, (task: GreenTask) => task.id)
      TextArea({ text: this.evidence, placeholder: '任务凭证说明' }).width('100%').height(70)
        .onChange((value: string) => { this.evidence = value; })
      Button(this.operationBusy ? '验证中…' : '完成所选演示任务').enabled(!this.operationBusy).width('100%')
        .fontColor(Color.White).backgroundColor($r('app.color.primary')).onClick(() => { this.completeTask(); })
      Text('DemoGreenVerifier 仅验证演示凭证；积分由服务端统一记账并与商城账户联动。').width('100%')
        .fontSize(8).fontColor($r('app.color.warning'))
    }.width('100%').padding(13).borderRadius(16).backgroundColor($r('app.color.surface'))
  }

  build() {
    Column({ space: 10 }) {
      Text('文化数字护照与绿色积分').width('100%').fontSize(19).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.text_primary'))
      if (!this.loggedIn) {
        StatePanel({ state: ContentState.NO_PERMISSION, message: '登录后同步印章、绿色任务和积分账户' })
        Button('立即登录').width('100%').fontColor(Color.White).backgroundColor($r('app.color.primary'))
          .onClick(() => { this.onLoginTap(); })
      } else if (this.contentState !== ContentState.CONTENT) {
        StatePanel({ state: this.contentState, message: this.operationMessage,
          onRetry: (): void => { this.loadAll(); } })
      }
      if (this.loggedIn && this.contentState === ContentState.CONTENT && this.isWide) {
        Row({ space: 12 }) {
          Column() { this.passportPanel() }.layoutWeight(1)
          Column() { this.greenPanel() }.layoutWeight(1)
        }.width('100%').alignItems(VerticalAlign.Top)
      } else if (this.loggedIn && this.contentState === ContentState.CONTENT) {
        this.passportPanel()
        this.greenPanel()
      }
      if (this.operationMessage.length > 0) {
        Text(this.operationMessage).width('100%').padding(9).fontSize(9).borderRadius(10)
          .fontColor($r('app.color.warning')).backgroundColor($r('app.color.surface_tint'))
      }
    // 创新点 6：护照与绿色任务在宽屏并排、窄屏顺排，业务状态不随布局切换而重建。
    }.width('100%').onAreaChange((_oldArea: Area, newArea: Area) => {
      this.isWide = isWideWindow(Number(newArea.width));
    })
  }
}
