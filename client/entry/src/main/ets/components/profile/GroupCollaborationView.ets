import { StatePanel } from '../StatePanel';
import { ContentState } from '../../models/AppModels';
import { GroupMember, LostAlertResponse, TravelGroup } from '../../models/ServiceModels';
import { ApiErrorCode, ApiErrorInfo } from '../../network/ApiError';
import { NetworkResult } from '../../network/HttpClient';
import { ServiceService } from '../../network/services/ServiceService';
import { AppStore } from '../../stores/AppStore';
import { AuthStore } from '../../stores/AuthStore';
import {
  ServiceRuleResult,
  validateInviteCode,
  validateMeetingPoint,
  validateMemberStatus
} from '../../utils/ServiceRules';

@Component
export struct GroupCollaborationView {
  @Prop loggedIn: boolean = false;
  onLoginTap: () => void = (): void => {};
  @State contentState: ContentState = ContentState.CONTENT;
  @State group: TravelGroup | null = null;
  @State groupName: string = '我的同行小队';
  @State inviteCode: string = '';
  @State meetingName: string = '游客中心集合点';
  @State meetingNodeId: string = '';
  @State meetingNote: string = '请在整点前 10 分钟集合';
  @State memberStatus: string = 'TOGETHER';
  @State memberNote: string = '与队伍同行中';
  @State selfShareLocation: boolean = false;
  @State selfShareStatus: boolean = true;
  @State demoLatitude: string = '';
  @State demoLongitude: string = '';
  @State shareItinerary: boolean = true;
  @State shareLocation: boolean = false;
  @State shareMemberStatus: boolean = true;
  @State lostMessage: string = '我与队伍走散，请在集合点等待';
  @State lastSeenNodeId: string = '';
  @State operationBusy: boolean = false;
  @State operationMessage: string = '';
  private service: ServiceService = new ServiceService();

  aboutToAppear(): void {
    const appStore: AppStore = AppStore.getInstance();
    if (this.loggedIn && appStore.hasCurrentGroup()) {
      this.loadStoredGroup(appStore.getCurrentGroupId());
    }
  }

  private async loadStoredGroup(groupId: string): Promise<void> {
    this.contentState = ContentState.LOADING;
    const result: NetworkResult<TravelGroup> = await this.service.getGroup(groupId);
    if (result.successful && result.data !== null) {
      this.applyGroup(result.data);
    } else {
      this.contentState = this.stateForError(result.error);
      this.operationMessage = this.errorText(result.error);
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
    return error === null ? '同行协作服务请求失败，请稍后重试' : error.userMessage;
  }

  private applyGroup(value: TravelGroup): void {
    this.group = value;
    AppStore.getInstance().setCurrentGroupId(value.id);
    this.shareItinerary = value.share_itinerary;
    this.shareLocation = value.share_location;
    this.shareMemberStatus = value.share_member_status;
    // 创新点 5：成员可见状态由服务端按“小队总开关 ∩ 成员个人开关”裁剪，客户端只投影获准字段。
    const currentUserId: string = AuthStore.getInstance().getUserId();
    for (let index: number = 0; index < value.members.length; index++) {
      const member: GroupMember = value.members[index];
      if (member.user_id === currentUserId) {
        this.selfShareLocation = member.share_location;
        this.selfShareStatus = member.share_status;
        if (member.status !== 'HIDDEN') {
          this.memberStatus = member.status;
        }
        this.memberNote = member.note;
        this.demoLatitude = member.latitude === null ? '' : member.latitude.toString();
        this.demoLongitude = member.longitude === null ? '' : member.longitude.toString();
      }
    }
    this.contentState = ContentState.CONTENT;
  }

  private async createGroup(): Promise<void> {
    if (!this.loggedIn || this.operationBusy) {
      this.contentState = ContentState.NO_PERMISSION;
      return;
    }
    if (this.groupName.trim().length < 2 || this.groupName.trim().length > 160) {
      this.operationMessage = '小队名称应为 2 至 160 个字符';
      return;
    }
    const appStore: AppStore = AppStore.getInstance();
    const itineraryId: string | null = appStore.hasCurrentItinerary() ? appStore.getCurrentItineraryId() : null;
    this.operationBusy = true;
    const result: NetworkResult<TravelGroup> = await this.service.createGroup(this.groupName.trim(), itineraryId);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.applyGroup(result.data);
      this.operationMessage = `小队已创建，邀请码 ${result.data.invite_code}`;
    } else {
      this.contentState = this.stateForError(result.error);
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async joinGroup(): Promise<void> {
    if (!this.loggedIn || this.operationBusy) {
      this.contentState = ContentState.NO_PERMISSION;
      return;
    }
    const validation: ServiceRuleResult = validateInviteCode(this.inviteCode);
    if (!validation.valid) {
      this.operationMessage = validation.message;
      return;
    }
    this.operationBusy = true;
    const result: NetworkResult<TravelGroup> = await this.service.joinGroup(this.inviteCode.trim().toUpperCase());
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.applyGroup(result.data);
      this.operationMessage = `已加入 ${result.data.name}`;
    } else {
      this.contentState = this.stateForError(result.error);
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async refreshGroup(): Promise<void> {
    if (this.group === null || this.operationBusy) {
      return;
    }
    this.operationBusy = true;
    const result: NetworkResult<TravelGroup> = await this.service.getGroup(this.group.id);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.applyGroup(result.data);
      this.operationMessage = `协作状态已刷新至版本 ${result.data.revision}`;
    } else {
      this.contentState = this.stateForError(result.error);
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async linkCurrentItinerary(): Promise<void> {
    if (this.group === null || this.operationBusy) {
      return;
    }
    const appStore: AppStore = AppStore.getInstance();
    if (!appStore.hasCurrentItinerary()) {
      this.operationMessage = '尚无当前行程，请先在行程页生成';
      return;
    }
    this.operationBusy = true;
    // 创新点 5：链接行程携带当前小队 revision，以乐观并发控制阻止多人同时编辑时的静默覆盖。
    const result: NetworkResult<TravelGroup> = await this.service.linkGroupItinerary(
      this.group.id, appStore.getCurrentItineraryId(), this.group.revision);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.applyGroup(result.data);
      this.operationMessage = `共享行程已链接，协作版本 ${result.data.revision}`;
    } else {
      this.operationMessage = result.error !== null && result.error.statusCode === 409 ?
        '小队版本已变化，请刷新后重试' : this.errorText(result.error);
    }
  }

  private async updatePrivacy(): Promise<void> {
    if (this.group === null || this.operationBusy) {
      return;
    }
    this.operationBusy = true;
    // 创新点 5：小队级开关与成员自己的共享开关分层保存，位置默认关闭且不能被队友单方面开启。
    const result: NetworkResult<TravelGroup> = await this.service.updateGroupPrivacy(
      this.group.id, this.shareItinerary, this.shareLocation, this.shareMemberStatus);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.applyGroup(result.data);
      this.operationMessage = '隐私开关已保存到服务端';
    } else {
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async setMeetingPoint(): Promise<void> {
    if (this.group === null || this.operationBusy) {
      return;
    }
    const validation: ServiceRuleResult = validateMeetingPoint(this.meetingName, this.meetingNodeId);
    if (!validation.valid) {
      this.operationMessage = validation.message;
      return;
    }
    this.operationBusy = true;
    const result: NetworkResult<TravelGroup> = await this.service.setMeetingPoint(
      this.group.id, this.meetingName.trim(), this.meetingNodeId.trim(), this.meetingNote.trim());
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.applyGroup(result.data);
      this.operationMessage = '集合点已同步给同行成员';
    } else {
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async updateStatus(): Promise<void> {
    if (this.group === null || this.operationBusy) {
      return;
    }
    const validation: ServiceRuleResult = validateMemberStatus(this.memberStatus, this.memberNote);
    if (!validation.valid) {
      this.operationMessage = validation.message;
      return;
    }
    let latitude: number | null = null;
    let longitude: number | null = null;
    if (this.selfShareLocation) {
      latitude = Number(this.demoLatitude);
      longitude = Number(this.demoLongitude);
      if (this.demoLatitude.trim().length === 0 || this.demoLongitude.trim().length === 0 ||
        Number.isNaN(latitude) || Number.isNaN(longitude) || latitude < -90 || latitude > 90 ||
        longitude < -180 || longitude > 180) {
        this.operationMessage = '启用位置共享时，请先使用定位演示或输入有效经纬度';
        return;
      }
    }
    this.operationBusy = true;
    const result: NetworkResult<TravelGroup> = await this.service.updateMemberStatus(
      this.group.id, this.memberStatus, this.memberNote.trim(), this.selfShareLocation,
      this.selfShareStatus, latitude, longitude);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.applyGroup(result.data);
      this.operationMessage = '成员状态已同步';
    } else {
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async createLostAlert(): Promise<void> {
    if (this.group === null || this.operationBusy || this.lostMessage.trim().length < 1) {
      this.operationMessage = '请填写走散说明';
      return;
    }
    this.operationBusy = true;
    const result: NetworkResult<LostAlertResponse> = await this.service.createLostAlert(
      this.group.id, this.lostMessage.trim(), this.lastSeenNodeId.trim());
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.operationMessage = `走散提醒 ${result.data.status}；provider=${result.data.provider}/demo=${result.data.is_demo}`;
      await this.refreshGroup();
    } else {
      this.operationMessage = this.errorText(result.error);
    }
  }

  @Builder
  private statusButton(label: string, value: string) {
    Button(label).layoutWeight(1).fontSize(9)
      .fontColor(this.memberStatus === value ? Color.White : $r('app.color.primary'))
      .backgroundColor(this.memberStatus === value ? $r('app.color.primary') : $r('app.color.surface_tint'))
      .onClick(() => { this.memberStatus = value; })
  }

  build() {
    Column({ space: 11 }) {
      Text('多人同行协作').width('100%').fontSize(18).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.text_primary'))
      Text('邀请码、共享行程、集合点和成员状态经真实 API 同步；走散提醒为演示适配器。')
        .width('100%').fontSize(9).fontColor($r('app.color.warning'))
      if (!this.loggedIn) {
        StatePanel({ state: ContentState.NO_PERMISSION, message: '登录后创建或加入同行小队' })
        Button('立即登录').width('100%').fontColor(Color.White).backgroundColor($r('app.color.primary'))
          .onClick(() => { this.onLoginTap(); })
      } else if (this.group === null) {
        Column({ space: 7 }) {
          TextInput({ text: this.groupName, placeholder: '小队名称' }).width('100%')
            .onChange((value: string) => { this.groupName = value; })
          Button(this.operationBusy ? '创建中…' : '创建小队').enabled(!this.operationBusy).width('100%')
            .fontColor(Color.White).backgroundColor($r('app.color.primary')).onClick(() => { this.createGroup(); })
          Text('或使用邀请码加入').width('100%').fontSize(10).fontColor($r('app.color.text_secondary'))
          Row({ space: 7 }) {
            TextInput({ text: this.inviteCode, placeholder: '6-32 位邀请码' }).layoutWeight(1)
              .onChange((value: string) => { this.inviteCode = value; })
            Button('加入').enabled(!this.operationBusy).onClick(() => { this.joinGroup(); })
          }.width('100%')
        }.width('100%').padding(13).borderRadius(15).backgroundColor($r('app.color.surface'))
      } else {
        Row() {
          Column({ space: 3 }) {
            Text(this.group.name).fontSize(17).fontWeight(FontWeight.Bold).fontColor($r('app.color.text_primary'))
            Text(`邀请码 ${this.group.invite_code} · 版本 ${this.group.revision}`).fontSize(9)
              .fontColor($r('app.color.text_secondary'))
          }.alignItems(HorizontalAlign.Start).layoutWeight(1)
          Button('刷新').enabled(!this.operationBusy).fontSize(10).onClick(() => { this.refreshGroup(); })
        }.width('100%')
        Column({ space: 6 }) {
          Text(`共享行程：${this.group.itinerary_id ?? '尚未链接'} · 行程版本 ` +
            `${this.group.itinerary_revision ?? 0}`).width('100%').fontSize(10).fontColor($r('app.color.primary'))
          Button('链接当前行程').enabled(!this.operationBusy).width('100%').fontColor(Color.White)
            .backgroundColor($r('app.color.primary')).onClick(() => { this.linkCurrentItinerary(); })
        }.width('100%').padding(12).borderRadius(14).backgroundColor($r('app.color.surface'))
        Column({ space: 6 }) {
          Row() {
            Text('共享行程').layoutWeight(1).fontColor($r('app.color.text_primary'))
            Toggle({ type: ToggleType.Switch, isOn: this.shareItinerary })
              .onChange((value: boolean) => { this.shareItinerary = value; })
          }.width('100%')
          Row() {
            Text('共享位置（默认关闭）').layoutWeight(1).fontColor($r('app.color.text_primary'))
            Toggle({ type: ToggleType.Switch, isOn: this.shareLocation })
              .onChange((value: boolean) => { this.shareLocation = value; })
          }.width('100%')
          Row() {
            Text('共享成员状态').layoutWeight(1).fontColor($r('app.color.text_primary'))
            Toggle({ type: ToggleType.Switch, isOn: this.shareMemberStatus })
              .onChange((value: boolean) => { this.shareMemberStatus = value; })
          }.width('100%')
          Button('保存隐私设置').enabled(!this.operationBusy).width('100%').onClick(() => { this.updatePrivacy(); })
        }.width('100%').padding(12).borderRadius(14).backgroundColor($r('app.color.surface'))
        Text('成员状态').width('100%').fontWeight(FontWeight.Bold).fontColor($r('app.color.text_primary'))
        ForEach(this.group.members, (member: GroupMember) => {
          Column({ space: 3 }) {
            Row() {
              Text(`${member.display_name} · ${member.role}`).layoutWeight(1).fontColor($r('app.color.text_primary'))
              Text(member.status).fontSize(10).fontColor(member.status === 'LOST' ?
                $r('app.color.error') : $r('app.color.success'))
            }.width('100%')
            if (member.share_location && member.latitude !== null && member.longitude !== null) {
              Text(`定位演示 ${member.latitude}, ${member.longitude}`).width('100%').fontSize(8)
                .fontColor($r('app.color.warning'))
            } else {
              Text('位置 HIDDEN').width('100%').fontSize(8).fontColor($r('app.color.text_secondary'))
            }
          }.width('100%').padding(10).borderRadius(11).backgroundColor($r('app.color.surface'))
        }, (member: GroupMember) => member.user_id)
        Row({ space: 5 }) {
          this.statusButton('同行', 'TOGETHER')
          this.statusButton('移动中', 'MOVING')
          this.statusButton('等待', 'WAITING')
          this.statusButton('走散', 'LOST')
        }.width('100%')
        TextInput({ text: this.memberNote, placeholder: '状态备注' }).width('100%')
          .onChange((value: string) => { this.memberNote = value; })
        Row() {
          Text('共享我的状态').layoutWeight(1).fontColor($r('app.color.text_primary'))
          Toggle({ type: ToggleType.Switch, isOn: this.selfShareStatus })
            .onChange((value: boolean) => { this.selfShareStatus = value; })
        }.width('100%')
        Row() {
          Text('共享我的位置（双重同意）').layoutWeight(1).fontColor($r('app.color.text_primary'))
          Toggle({ type: ToggleType.Switch, isOn: this.selfShareLocation })
            .onChange((value: boolean) => { this.selfShareLocation = value; })
        }.width('100%')
        if (this.selfShareLocation) {
          Row({ space: 6 }) {
            TextInput({ text: this.demoLatitude, placeholder: '纬度' }).layoutWeight(1)
              .onChange((value: string) => { this.demoLatitude = value; })
            TextInput({ text: this.demoLongitude, placeholder: '经度' }).layoutWeight(1)
              .onChange((value: string) => { this.demoLongitude = value; })
            Button('定位演示').fontSize(9).onClick(() => {
              this.demoLatitude = '30.2741';
              this.demoLongitude = '120.1551';
              this.operationMessage = '已填入固定演示坐标；未调用真实定位硬件';
            })
          }.width('100%')
        }
        Button('同步我的状态').enabled(!this.operationBusy).width('100%').onClick(() => { this.updateStatus(); })
        Column({ space: 6 }) {
          Text('集合点').width('100%').fontWeight(FontWeight.Bold).fontColor($r('app.color.text_primary'))
          Row({ space: 6 }) {
            TextInput({ text: this.meetingName, placeholder: '名称' }).layoutWeight(1)
              .onChange((value: string) => { this.meetingName = value; })
            TextInput({ text: this.meetingNodeId, placeholder: '地图节点 UUID（选填）' }).layoutWeight(1)
              .onChange((value: string) => { this.meetingNodeId = value; })
          }.width('100%')
          TextInput({ text: this.meetingNote, placeholder: '集合说明' }).width('100%')
            .onChange((value: string) => { this.meetingNote = value; })
          Button('同步集合点').enabled(!this.operationBusy).width('100%').onClick(() => { this.setMeetingPoint(); })
        }.width('100%').padding(12).borderRadius(14).backgroundColor($r('app.color.surface'))
        Column({ space: 6 }) {
          Text('走散提醒演示').width('100%').fontWeight(FontWeight.Bold).fontColor($r('app.color.error'))
          TextInput({ text: this.lostMessage, placeholder: '提醒内容' }).width('100%')
            .onChange((value: string) => { this.lostMessage = value; })
          TextInput({ text: this.lastSeenNodeId, placeholder: '最后位置节点' }).width('100%')
            .onChange((value: string) => { this.lastSeenNodeId = value; })
          Button(this.operationBusy ? '发送中…' : '发送演示走散提醒').enabled(!this.operationBusy).width('100%')
            .fontColor(Color.White).backgroundColor($r('app.color.error')).onClick(() => { this.createLostAlert(); })
          Text('仅为服务端演示适配器，不代表短信、定位或系统推送已接入。').width('100%').fontSize(8)
            .fontColor($r('app.color.warning'))
        }.width('100%').padding(12).borderRadius(14).backgroundColor($r('app.color.surface_tint'))
        Text(`provider=${this.group.provider}/demo=${this.group.is_demo}`).width('100%').fontSize(8)
          .fontColor($r('app.color.warning'))
      }
      if (this.contentState !== ContentState.CONTENT && this.loggedIn) {
        StatePanel({ state: this.contentState, message: this.operationMessage,
          onRetry: (): void => { this.refreshGroup(); } })
      }
      if (this.operationMessage.length > 0) {
        Text(this.operationMessage).width('100%').padding(9).fontSize(9).borderRadius(10)
          .fontColor($r('app.color.warning')).backgroundColor($r('app.color.surface_tint'))
      }
    }.width('100%')
  }
}
