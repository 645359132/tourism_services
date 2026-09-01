import { AccessibilityView } from '../components/profile/AccessibilityView';
import { GroupCollaborationView } from '../components/profile/GroupCollaborationView';
import { SupportCenterView } from '../components/profile/SupportCenterView';
import { AppConfig } from '../config/AppConfig';
import { AccessibilitySettings, AccessibilityStore } from '../stores/AccessibilityStore';

enum ProfileSection {
  OVERVIEW = 0,
  SUPPORT = 1,
  GROUP = 2,
  ACCESSIBILITY = 3
}

@Component
export struct ProfilePage {
  @Link loggedIn: boolean;
  @Link displayName: string;
  onLoginTap: () => void = (): void => {};
  onAccessibilityChanged: (largeText: boolean, highContrast: boolean) => void =
    (_largeText: boolean, _highContrast: boolean): void => {};
  @State section: ProfileSection = ProfileSection.OVERVIEW;
  @State largeText: boolean = false;
  @State highContrast: boolean = false;
  @State offlinePackReady: boolean = false;
  @State apiUrl: string = AppConfig.getApiBaseUrl();
  @State configFeedback: string = '';

  aboutToAppear(): void {
    const settings: AccessibilitySettings = AccessibilityStore.getInstance().getSettings();
    this.largeText = settings.largeText;
    this.highContrast = settings.highContrast;
  }

  private applyVisualSettings(largeText: boolean, highContrast: boolean): void {
    this.largeText = largeText;
    this.highContrast = highContrast;
    this.onAccessibilityChanged(largeText, highContrast);
  }

  @Builder
  private sectionButton(label: string, value: ProfileSection) {
    Button(label).layoutWeight(1).fontSize(this.largeText ? 14 : 10)
      .fontColor(this.section === value ? (this.highContrast ? '#000000' : Color.White) :
        (this.highContrast ? '#FFFFFF' : $r('app.color.primary')))
      .backgroundColor(this.section === value ? (this.highContrast ? '#FFFF00' : $r('app.color.primary')) :
        (this.highContrast ? '#171717' : $r('app.color.surface_tint')))
      .onClick(() => { this.section = value; })
  }

  @Builder
  private overviewContent() {
    Column({ space: 12 }) {
      Column({ space: 7 }) {
        Text('服务入口已真实接入').width('100%').fontSize(this.largeText ? 21 : 16).fontWeight(FontWeight.Bold)
          .fontColor(this.highContrast ? '#FFFFFF' : $r('app.color.text_primary'))
        Text('客服与反馈：工单状态、回访评分、FAQ、持久化会话与 WebSocket').width('100%')
          .fontSize(this.largeText ? 15 : 11).fontColor(this.highContrast ? '#FFFFFF' : $r('app.color.text_secondary'))
        Text('多人同行：邀请码、共享行程、集合点、成员状态、隐私与走散提醒').width('100%')
          .fontSize(this.largeText ? 15 : 11).fontColor(this.highContrast ? '#FFFFFF' : $r('app.color.text_secondary'))
        Text('适老无障碍：持久化视觉/路线偏好与真实便民设施列表').width('100%')
          .fontSize(this.largeText ? 15 : 11).fontColor(this.highContrast ? '#FFFFFF' : $r('app.color.text_secondary'))
      }.width('100%').padding(15).borderRadius(16)
        .backgroundColor(this.highContrast ? '#171717' : $r('app.color.surface'))
      Column({ space: 10 }) {
        Row() {
          Column({ space: 3 }) {
            Text('弱网离线旅行包').fontSize(this.largeText ? 18 : 14).fontWeight(FontWeight.Medium)
              .fontColor(this.highContrast ? '#FFFFFF' : $r('app.color.text_primary'))
            Text(this.offlinePackReady ? '电子票、地图和行程已可离线使用' : '下载核心地图、电子票、行程与讲解')
              .fontSize(this.largeText ? 14 : 10)
              .fontColor(this.highContrast ? '#FFFF00' : $r('app.color.text_secondary'))
          }.alignItems(HorizontalAlign.Start).layoutWeight(1)
          Button(this.offlinePackReady ? '已下载' : '下载').fontSize(this.largeText ? 14 : 11)
            .fontColor(this.offlinePackReady ? $r('app.color.success') : Color.White)
            .backgroundColor(this.offlinePackReady ? $r('app.color.surface_tint') : $r('app.color.primary'))
            .onClick(() => { this.offlinePackReady = true; })
        }.width('100%')
        Text('离线包仍为客户端演示状态；检查点 8 将补齐持久化和恢复同步。').width('100%')
          .fontSize(this.largeText ? 12 : 8).fontColor(this.highContrast ? '#FFFF00' : $r('app.color.warning'))
      }.width('100%').padding(15).borderRadius(16)
        .backgroundColor(this.highContrast ? '#171717' : $r('app.color.surface'))
      Column({ space: 8 }) {
        Text('开发环境 API 地址').width('100%').fontSize(this.largeText ? 18 : 14).fontWeight(FontWeight.Medium)
          .fontColor(this.highContrast ? '#FFFFFF' : $r('app.color.text_primary'))
        TextInput({ text: this.apiUrl, placeholder: 'http://127.0.0.1:8000/api/v1' }).width('100%')
          .onChange((value: string) => { this.apiUrl = value; })
        Row() {
          Text(this.configFeedback).fontSize(this.largeText ? 13 : 9)
            .fontColor(this.configFeedback === '已应用' ? $r('app.color.success') : $r('app.color.error'))
            .layoutWeight(1)
          Button('应用地址').fontSize(this.largeText ? 14 : 11).onClick(() => {
            this.configFeedback = AppConfig.setApiBaseUrl(this.apiUrl) ? '已应用' : '地址格式无效';
          })
        }.width('100%')
      }.width('100%').padding(15).borderRadius(16)
        .backgroundColor(this.highContrast ? '#171717' : $r('app.color.surface'))
    }.width('100%')
  }

  build() {
    Scroll() {
      Column({ space: 13 }) {
        Row({ space: 13 }) {
          Text(this.loggedIn ? this.displayName.substring(0, 1) : '游').width(56).height(56)
            .textAlign(TextAlign.Center).fontSize(this.largeText ? 28 : 22).fontWeight(FontWeight.Bold)
            .fontColor(this.highContrast ? '#000000' : Color.White)
            .backgroundColor(this.highContrast ? '#FFFF00' : $r('app.color.primary')).borderRadius(28)
          Column({ space: 4 }) {
            Text(this.loggedIn ? this.displayName : '游客模式').fontSize(this.largeText ? 24 : 19)
              .fontWeight(FontWeight.Bold).fontColor(this.highContrast ? '#FFFFFF' : $r('app.color.text_primary'))
            Text(this.loggedIn ? '身份已验证，可同步服务、协作与积分数据' : '登录后同步多端旅行数据')
              .fontSize(this.largeText ? 15 : 11)
              .fontColor(this.highContrast ? '#FFFF00' : $r('app.color.text_secondary'))
          }.alignItems(HorizontalAlign.Start).layoutWeight(1)
          if (!this.loggedIn) {
            Button('立即登录').fontColor(this.highContrast ? '#000000' : Color.White)
              .backgroundColor(this.highContrast ? '#FFFF00' : $r('app.color.primary'))
              .onClick(() => { this.onLoginTap(); })
          }
        }.width('100%').padding(17).borderRadius(18)
          .backgroundColor(this.highContrast ? '#171717' : $r('app.color.surface'))
        Row({ space: 5 }) {
          this.sectionButton('概览', ProfileSection.OVERVIEW)
          this.sectionButton('客服服务', ProfileSection.SUPPORT)
          this.sectionButton('同行协作', ProfileSection.GROUP)
          this.sectionButton('无障碍', ProfileSection.ACCESSIBILITY)
        }.width('100%')
        if (this.section === ProfileSection.OVERVIEW) {
          this.overviewContent()
        } else if (this.section === ProfileSection.SUPPORT) {
          SupportCenterView({ loggedIn: this.loggedIn, onLoginTap: this.onLoginTap })
        } else if (this.section === ProfileSection.GROUP) {
          GroupCollaborationView({ loggedIn: this.loggedIn, onLoginTap: this.onLoginTap })
        } else {
          AccessibilityView({
            onVisualChanged: (largeText: boolean, highContrast: boolean): void => {
              this.applyVisualSettings(largeText, highContrast);
            }
          })
        }
      }.width('100%').constraintSize({ maxWidth: 960 })
        .padding({ left: 16, right: 16, top: 16, bottom: 30 })
    }.width('100%').height('100%').scrollBar(BarState.Off)
      .backgroundColor(this.highContrast ? '#000000' : $r('app.color.page_background'))
  }
}
