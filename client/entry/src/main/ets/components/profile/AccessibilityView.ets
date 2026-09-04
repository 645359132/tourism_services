import { StatePanel } from '../StatePanel';
import { ContentState } from '../../models/AppModels';
import { FacilityItem, FacilityListResponse } from '../../models/ServiceModels';
import { ApiErrorCode, ApiErrorInfo } from '../../network/ApiError';
import { NetworkResult } from '../../network/HttpClient';
import { ServiceService } from '../../network/services/ServiceService';
import { AccessibilitySettings, AccessibilityStore } from '../../stores/AccessibilityStore';
import { facilityMatchesPreference } from '../../utils/ServiceRules';

@Component
export struct AccessibilityView {
  onVisualChanged: (largeText: boolean, highContrast: boolean) => void =
    (_largeText: boolean, _highContrast: boolean): void => {};
  @State largeText: boolean = false;
  @State highContrast: boolean = false;
  @State voiceAssist: boolean = false;
  @State wheelchair: boolean = false;
  @State stroller: boolean = false;
  @State facilityKind: string = 'ALL';
  @State facilities: FacilityItem[] = [];
  @State contentState: ContentState = ContentState.LOADING;
  @State operationMessage: string = '';
  private service: ServiceService = new ServiceService();

  aboutToAppear(): void {
    const settings: AccessibilitySettings = AccessibilityStore.getInstance().getSettings();
    this.largeText = settings.largeText;
    this.highContrast = settings.highContrast;
    this.voiceAssist = settings.voiceAssist;
    this.wheelchair = settings.wheelchair;
    this.stroller = settings.stroller;
    this.loadFacilities();
  }

  private stateForError(error: ApiErrorInfo | null): ContentState {
    if (error !== null && error.code === ApiErrorCode.OFFLINE) {
      return ContentState.OFFLINE;
    }
    return ContentState.ERROR;
  }

  private async loadFacilities(): Promise<void> {
    this.contentState = ContentState.LOADING;
    const result: NetworkResult<FacilityListResponse> = await this.service.listFacilities();
    if (!result.successful || result.data === null) {
      this.contentState = this.stateForError(result.error);
      this.operationMessage = result.error === null ? '便民设施加载失败' : result.error.userMessage;
      return;
    }
    this.facilities = result.data.items;
    this.contentState = this.facilities.length === 0 ? ContentState.EMPTY : ContentState.CONTENT;
  }

  private visibleFacilities(): FacilityItem[] {
    // 创新点 6：设施类别与轮椅/推车偏好共同过滤，让持久化偏好真正参与便民信息筛选。
    const result: FacilityItem[] = [];
    for (let index: number = 0; index < this.facilities.length; index++) {
      const item: FacilityItem = this.facilities[index];
      const kindMatches: boolean = this.facilityKind === 'ALL' || item.kind === this.facilityKind;
      if (kindMatches && facilityMatchesPreference(item, this.wheelchair, this.stroller)) {
        result.push(item);
      }
    }
    return result;
  }

  private updateLargeText(value: boolean): void {
    // 创新点 6：视觉设置写入统一 Store 后再通知页面容器，当前界面即时响应且重启后仍可恢复。
    this.largeText = value;
    AccessibilityStore.getInstance().setLargeText(value);
    this.onVisualChanged(this.largeText, this.highContrast);
    this.operationMessage = value ? '大字体已持久化并应用到个人服务入口' : '大字体已关闭';
  }

  private updateHighContrast(value: boolean): void {
    this.highContrast = value;
    AccessibilityStore.getInstance().setHighContrast(value);
    this.onVisualChanged(this.largeText, this.highContrast);
    this.operationMessage = value ? '高对比度已持久化并应用' : '高对比度已关闭';
  }

  private updateVoiceAssist(value: boolean): void {
    this.voiceAssist = value;
    AccessibilityStore.getInstance().setVoiceAssist(value);
    this.operationMessage = value ? '语音辅助入口已启用；当前为演示控制，未接系统 TTS' : '语音辅助入口已关闭';
  }

  private updateWheelchair(value: boolean): void {
    this.wheelchair = value;
    AccessibilityStore.getInstance().setWheelchair(value);
    this.operationMessage = '轮椅偏好已持久化，下次进入导览/行程时自动带入真实路线请求';
  }

  private updateStroller(value: boolean): void {
    this.stroller = value;
    AccessibilityStore.getInstance().setStroller(value);
    this.operationMessage = '亲子推车偏好已持久化，下次进入导览/行程时自动带入真实路线请求';
  }

  @Builder
  private settingRow(title: string, caption: string, value: boolean, kind: string) {
    Row() {
      Column({ space: 3 }) {
        Text(title).fontSize(this.largeText ? 18 : 14).fontWeight(FontWeight.Medium)
          .fontColor(this.highContrast ? '#FFFFFF' : $r('app.color.text_primary'))
        Text(caption).fontSize(this.largeText ? 14 : 10)
          .fontColor(this.highContrast ? '#FFFF00' : $r('app.color.text_secondary'))
      }.alignItems(HorizontalAlign.Start).layoutWeight(1)
      Toggle({ type: ToggleType.Switch, isOn: value }).selectedColor(this.highContrast ? '#FFFF00' :
        $r('app.color.primary')).onChange((enabled: boolean) => {
          if (kind === 'large') {
            this.updateLargeText(enabled);
          } else if (kind === 'contrast') {
            this.updateHighContrast(enabled);
          } else if (kind === 'voice') {
            this.updateVoiceAssist(enabled);
          } else if (kind === 'wheelchair') {
            this.updateWheelchair(enabled);
          } else {
            this.updateStroller(enabled);
          }
        })
    }.width('100%').padding(11).borderRadius(12)
      .backgroundColor(this.highContrast ? '#171717' : $r('app.color.surface'))
  }

  @Builder
  private kindButton(label: string, value: string) {
    Button(label).layoutWeight(1).fontSize(this.largeText ? 13 : 10)
      .fontColor(this.facilityKind === value ? (this.highContrast ? '#000000' : Color.White) :
        (this.highContrast ? '#FFFFFF' : $r('app.color.primary')))
      .backgroundColor(this.facilityKind === value ? (this.highContrast ? '#FFFF00' : $r('app.color.primary')) :
        (this.highContrast ? '#171717' : $r('app.color.surface_tint')))
      .onClick(() => { this.facilityKind = value; })
  }

  build() {
    Column({ space: 10 }) {
      Text('适老与无障碍').width('100%').fontSize(this.largeText ? 24 : 18).fontWeight(FontWeight.Bold)
        .fontColor(this.highContrast ? '#FFFFFF' : $r('app.color.text_primary'))
      Text('设置保存在 HarmonyOS Preferences；轮椅/推车偏好会传入现有导览和行程服务。').width('100%')
        .fontSize(this.largeText ? 14 : 9).fontColor(this.highContrast ? '#FFFF00' : $r('app.color.warning'))
      this.settingRow('大字体', '放大个人服务入口与便民设施文字', this.largeText, 'large')
      this.settingRow('高对比度', '黑底、白字与黄色重点提示', this.highContrast, 'contrast')
      this.settingRow('语音辅助入口', '演示开关；不虚称已接系统 TTS', this.voiceAssist, 'voice')
      this.settingRow('轮椅无障碍路线', '自动带入 GuideService wheelchair 参数', this.wheelchair, 'wheelchair')
      this.settingRow('亲子推车路线', '自动带入 GuideService stroller 参数', this.stroller, 'stroller')
      if (this.voiceAssist) {
        Button('试听语音辅助演示').width('100%').fontSize(this.largeText ? 16 : 12)
          .fontColor(this.highContrast ? '#000000' : Color.White)
          .backgroundColor(this.highContrast ? '#FFFF00' : $r('app.color.primary')).onClick(() => {
            this.operationMessage = '语音辅助演示：附近设有无障碍卫生间、医务室和休息点。未调用系统 TTS。';
          })
      }
      Text('便民设施').width('100%').fontSize(this.largeText ? 21 : 16).fontWeight(FontWeight.Bold)
        .fontColor(this.highContrast ? '#FFFFFF' : $r('app.color.text_primary'))
      Row({ space: 5 }) {
        this.kindButton('全部', 'ALL')
        this.kindButton('卫生间', 'TOILET')
        this.kindButton('医务室', 'MEDICAL')
        this.kindButton('休息点', 'REST_AREA')
      }.width('100%')
      if (this.contentState !== ContentState.CONTENT) {
        StatePanel({ state: this.contentState, message: this.operationMessage,
          onRetry: (): void => { this.loadFacilities(); } })
      } else if (this.visibleFacilities().length === 0) {
        StatePanel({ state: ContentState.EMPTY, message: '当前筛选下没有满足偏好的设施' })
      } else {
        ForEach(this.visibleFacilities(), (item: FacilityItem) => {
          Column({ space: 4 }) {
            Row() {
              Text(`${item.kind} · ${item.name}`).fontSize(this.largeText ? 18 : 14).fontWeight(FontWeight.Medium)
                .fontColor(this.highContrast ? '#FFFFFF' : $r('app.color.text_primary')).layoutWeight(1)
              Text(item.open_status).fontSize(this.largeText ? 13 : 9)
                .fontColor(this.highContrast ? '#FFFF00' : $r('app.color.success'))
            }.width('100%')
            Text(item.description).width('100%').fontSize(this.largeText ? 14 : 10)
              .fontColor(this.highContrast ? '#FFFFFF' : $r('app.color.text_secondary'))
            Text(`节点 ${item.node_id} · 轮椅=${item.wheelchair_ok} · 推车=${item.stroller_ok} · ` +
              `source=${item.source}/demo=${item.is_demo}`).width('100%').fontSize(this.largeText ? 12 : 8)
              .fontColor(this.highContrast ? '#FFFF00' : $r('app.color.warning'))
          }.width('100%').padding(12).borderRadius(13)
            .backgroundColor(this.highContrast ? '#171717' : $r('app.color.surface'))
        }, (item: FacilityItem) => item.id)
      }
      if (this.operationMessage.length > 0) {
        Text(this.operationMessage).width('100%').padding(9).borderRadius(10).fontSize(this.largeText ? 14 : 9)
          .fontColor(this.highContrast ? '#FFFF00' : $r('app.color.warning'))
          .backgroundColor(this.highContrast ? '#171717' : $r('app.color.surface_tint'))
      }
    }.width('100%').padding(this.highContrast ? 12 : 0)
      .backgroundColor(this.highContrast ? '#000000' : Color.Transparent)
  }
}
