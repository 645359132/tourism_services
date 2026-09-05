import { StatePanel } from '../components/StatePanel';
import {
  Attraction,
  AttractionListResponse,
  CrowdItem,
  CrowdLevel,
  CrowdResponse,
  GuideMapNode,
  GuideMapResponse,
  Narration,
  NarrationListResponse,
  RoutePlanResponse
} from '../models/GuideModels';
import { ApiErrorCode, ApiErrorInfo } from '../network/ApiError';
import { CrowdSocket, CrowdSocketState } from '../network/CrowdSocket';
import { NetworkResult } from '../network/HttpClient';
import { GuideService } from '../network/services/GuideService';
import {
  buildCrowdAlternative,
  plannedRoutePathText,
  plannedRouteStepLabel,
  shouldAcceptCrowdSequence
} from '../utils/GuideRules';
import { ContentState } from '../models/AppModels';
import { formatShanghaiDateTime } from '../utils/DateTimeRules';

@Component
export struct GuidePage {
  @State contentState: ContentState = ContentState.LOADING;
  @State errorMessage: string = '';
  @State attractions: Attraction[] = [];
  @State mapData: GuideMapResponse | null = null;
  @State crowdItems: CrowdItem[] = [];
  @State crowdSequence: number = -1;
  @State crowdCapturedAt: string = '';
  @State socketState: CrowdSocketState = CrowdSocketState.CONNECTING;
  @State socketMessage: string = '正在连接模拟人流服务';
  @State alternativeSuggestion: string = '';
  @State selectedDetail: Attraction | null = null;
  @State narrations: Narration[] = [];
  @State playingNarrationId: string = '';
  @State operationMessage: string = '';
  @State operationBusy: boolean = false;
  @State showHeat: boolean = true;
  @State locationDemo: boolean = false;
  @State originNodeId: string = '';
  @State targetNodeId: string = '';
  @State routePlan: RoutePlanResponse | null = null;
  @State routeMessage: string = '选择起点和终点后，点击“规划路线”';
  @State routeBusy: boolean = false;
  @State routeError: boolean = false;
  private routeRequestVersion: number = 0;
  private service: GuideService = new GuideService();
  private crowdSocket: CrowdSocket | null = null;

  aboutToAppear(): void {
    this.loadAll();
    this.startCrowdSocket();
  }

  aboutToDisappear(): void {
    if (this.crowdSocket !== null) {
      this.crowdSocket.stop();
      this.crowdSocket = null;
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
    return error === null ? '导览服务请求失败，请稍后重试' : error.userMessage;
  }

  private async loadAll(): Promise<void> {
    this.contentState = ContentState.LOADING;
    this.errorMessage = '';
    const attractionResult: NetworkResult<AttractionListResponse> = await this.service.listAttractions();
    if (!attractionResult.successful || attractionResult.data === null) {
      this.contentState = this.stateForError(attractionResult.error);
      this.errorMessage = this.errorText(attractionResult.error);
      return;
    }
    this.attractions = attractionResult.data.items;
    if (this.crowdItems.length > 0) {
      this.mergeCrowdIntoAttractions(this.crowdItems);
      this.alternativeSuggestion = buildCrowdAlternative(this.attractions, this.crowdItems);
    }
    if (this.attractions.length === 0) {
      this.contentState = ContentState.EMPTY;
      return;
    }
    const mapResult: NetworkResult<GuideMapResponse> = await this.service.getMap();
    if (!mapResult.successful || mapResult.data === null) {
      this.contentState = this.stateForError(mapResult.error);
      this.errorMessage = this.errorText(mapResult.error);
      return;
    }
    this.mapData = mapResult.data;
    if (this.mapData.nodes.length > 0) {
      this.originNodeId = this.mapData.nodes[0].id;
      this.targetNodeId = this.mapData.nodes.length > 1 ? this.mapData.nodes[1].id : this.mapData.nodes[0].id;
    }
    const crowdResult: NetworkResult<CrowdResponse> = await this.service.getCrowd();
    if (!crowdResult.successful || crowdResult.data === null) {
      this.contentState = this.stateForError(crowdResult.error);
      this.errorMessage = this.errorText(crowdResult.error);
      return;
    }
    this.acceptCrowdSnapshot(crowdResult.data);
    this.contentState = ContentState.CONTENT;
  }

  private startCrowdSocket(): void {
    if (this.crowdSocket === null) {
      this.crowdSocket = new CrowdSocket((snapshot: CrowdResponse): void => {
        this.acceptCrowdSnapshot(snapshot);
      }, (state: CrowdSocketState, message: string): void => {
        this.socketState = state;
        this.socketMessage = message;
      });
    }
    this.crowdSocket.start();
  }

  private acceptCrowdSnapshot(snapshot: CrowdResponse): void {
    // 创新点 2：REST 与 WebSocket 共用单调序列门禁，迟到或重复快照不能把界面人流回滚到旧状态。
    if (!shouldAcceptCrowdSequence(this.crowdSequence, snapshot.sequence)) {
      return;
    }
    this.crowdSequence = snapshot.sequence;
    this.crowdCapturedAt = snapshot.items.length > 0 ? snapshot.items[0].captured_at : '';
    this.crowdItems = snapshot.items;
    this.mergeCrowdIntoAttractions(snapshot.items);
    this.alternativeSuggestion = buildCrowdAlternative(this.attractions, this.crowdItems);
  }

  private mergeCrowdIntoAttractions(crowdItems: CrowdItem[]): void {
    const updatedAttractions: Attraction[] = this.attractions.slice();
    for (let crowdIndex: number = 0; crowdIndex < crowdItems.length; crowdIndex++) {
      for (let attractionIndex: number = 0; attractionIndex < updatedAttractions.length; attractionIndex++) {
        if (updatedAttractions[attractionIndex].id === crowdItems[crowdIndex].attraction_id) {
          updatedAttractions[attractionIndex].crowd_level = crowdItems[crowdIndex].level;
          updatedAttractions[attractionIndex].occupancy_bps = crowdItems[crowdIndex].occupancy_bps;
          updatedAttractions[attractionIndex].wait_minutes = crowdItems[crowdIndex].wait_minutes;
        }
      }
    }
    this.attractions = updatedAttractions;
  }

  private crowdLevelForNode(nodeId: string): CrowdLevel {
    for (let index: number = 0; index < this.attractions.length; index++) {
      if (this.attractions[index].node_id === nodeId) {
        return this.attractions[index].crowd_level;
      }
    }
    return CrowdLevel.LOW;
  }

  private async refreshCrowd(): Promise<void> {
    this.operationBusy = true;
    const result: NetworkResult<CrowdResponse> = await this.service.getCrowd();
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.acceptCrowdSnapshot(result.data);
      this.operationMessage = '已读取最新模拟人流 REST 快照';
    } else {
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async showAttractionDetail(attractionId: string): Promise<void> {
    this.operationBusy = true;
    this.operationMessage = '';
    const detailResult: NetworkResult<Attraction> = await this.service.getAttraction(attractionId);
    if (!detailResult.successful || detailResult.data === null) {
      this.operationBusy = false;
      this.operationMessage = this.errorText(detailResult.error);
      return;
    }
    this.selectedDetail = detailResult.data;
    const narrationResult: NetworkResult<NarrationListResponse> = await this.service.listNarrations(attractionId);
    this.operationBusy = false;
    if (narrationResult.successful && narrationResult.data !== null) {
      this.narrations = narrationResult.data.items;
    } else {
      this.narrations = [];
      this.operationMessage = this.errorText(narrationResult.error);
    }
  }

  private nodeName(nodeId: string): string {
    if (this.mapData === null) {
      return '未选择';
    }
    for (let index: number = 0; index < this.mapData.nodes.length; index++) {
      if (this.mapData.nodes[index].id === nodeId) {
        return this.mapData.nodes[index].name;
      }
    }
    return '未选择';
  }

  private cycleNode(currentNodeId: string): string {
    if (this.mapData === null || this.mapData.nodes.length === 0) {
      return '';
    }
    for (let index: number = 0; index < this.mapData.nodes.length; index++) {
      if (this.mapData.nodes[index].id === currentNodeId) {
        return this.mapData.nodes[(index + 1) % this.mapData.nodes.length].id;
      }
    }
    return this.mapData.nodes[0].id;
  }

  private routeStepLabel(nodeId: string): string {
    return this.routePlan === null ? '' : plannedRouteStepLabel(this.routePlan.node_ids, nodeId);
  }

  private routePathText(): string {
    if (this.mapData === null || this.routePlan === null) {
      return '';
    }
    return plannedRoutePathText(this.mapData.nodes, this.routePlan.node_ids);
  }

  private invalidateRoute(message: string): void {
    // 创新点 2：起终点变化时同时作废请求版本和旧高亮，保证屏幕只表达当前选择对应的路线。
    this.routeRequestVersion += 1;
    this.routePlan = null;
    this.routeMessage = message;
    this.routeBusy = false;
    this.routeError = false;
  }

  private async planAccessibleRoute(): Promise<void> {
    if (this.originNodeId.length === 0 || this.targetNodeId.length === 0 ||
      this.originNodeId === this.targetNodeId) {
      this.invalidateRoute('请选择两个不同的起点和终点');
      this.routeError = true;
      return;
    }
    const requestVersion: number = this.routeRequestVersion + 1;
    this.routeRequestVersion = requestVersion;
    const originNodeId: string = this.originNodeId;
    const targetNodeId: string = this.targetNodeId;
    this.routeBusy = true;
    this.routeError = false;
    this.routePlan = null;
    this.routeMessage = '正在计算示意路线…';
    const result: NetworkResult<RoutePlanResponse> = await this.service.planRoute(originNodeId, targetNodeId);
    // 创新点 2：网络返回顺序不可控，只允许仍匹配当前请求版本的结果更新路线状态。
    if (requestVersion !== this.routeRequestVersion) {
      return;
    }
    this.routeBusy = false;
    if (result.successful && result.data !== null) {
      this.routePlan = result.data;
      this.routeMessage = '路线规划完成';
      this.routeError = false;
    } else {
      this.routePlan = null;
      this.routeMessage = this.errorText(result.error);
      this.routeError = true;
    }
  }

  @Builder
  private mapNode(node: GuideMapNode) {
    Column({ space: 4 }) {
      Row({ space: 5 }) {
        Text(node.kind === 'MEDICAL' ? '医' : node.kind === 'TOILET' ? '厕' : node.kind === 'REST' ? '休' : '●')
          .fontSize(18)
          .fontWeight(FontWeight.Bold)
          .fontColor(!this.showHeat ? $r('app.color.primary') :
            this.crowdLevelForNode(node.id) === CrowdLevel.HIGH ? $r('app.color.error') :
              this.crowdLevelForNode(node.id) === CrowdLevel.MEDIUM ? $r('app.color.warning') :
                $r('app.color.success'))
        // 创新点 2：路径节点同步显示顺序徽标和高亮边框，让规划结果在示意地图上形成连续视觉反馈。
        if (this.routeStepLabel(node.id).length > 0) {
          Text(this.routeStepLabel(node.id))
            .width(22)
            .height(22)
            .textAlign(TextAlign.Center)
            .fontSize(10)
            .fontWeight(FontWeight.Bold)
            .fontColor(Color.White)
            .borderRadius(11)
            .backgroundColor($r('app.color.primary'))
        }
      }
      .justifyContent(FlexAlign.Center)
      Text(node.name)
        .fontSize(12)
        .fontColor($r('app.color.text_primary'))
        .maxLines(1)
      Text(`示意坐标 ${node.x}, ${node.y}`)
        .fontSize(9)
        .fontColor($r('app.color.text_secondary'))
    }
    .width('31%')
    .height(78)
    .justifyContent(FlexAlign.Center)
    .borderRadius(14)
    .border({ width: this.routeStepLabel(node.id).length > 0 ? 3 : (this.showHeat ? 2 : 0),
      color: this.routeStepLabel(node.id).length > 0 ? $r('app.color.primary') :
        this.crowdLevelForNode(node.id) === CrowdLevel.HIGH ? $r('app.color.error') :
          this.crowdLevelForNode(node.id) === CrowdLevel.MEDIUM ? $r('app.color.warning') :
            $r('app.color.success') })
    .backgroundColor($r('app.color.surface_tint'))
  }

  @Builder
  private attractionCard(item: Attraction) {
    Row({ space: 12 }) {
      Column() {
        Text(item.category.length > 0 ? item.category.substring(0, 1) : '景')
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.primary'))
      }
      .width(50)
      .height(50)
      .justifyContent(FlexAlign.Center)
      .borderRadius(15)
      .backgroundColor($r('app.color.surface_tint'))
      Column({ space: 4 }) {
        Row() {
          Text(item.name)
            .fontSize(16)
            .fontWeight(FontWeight.Medium)
            .fontColor($r('app.color.text_primary'))
            .layoutWeight(1)
          Text(item.crowd_level === CrowdLevel.HIGH ? '拥挤' : item.crowd_level === CrowdLevel.MEDIUM ? '较舒适' : '舒适')
            .fontSize(11)
            .fontColor(item.crowd_level === CrowdLevel.HIGH ? $r('app.color.error') :
              item.crowd_level === CrowdLevel.MEDIUM ? $r('app.color.warning') : $r('app.color.success'))
        }
        .width('100%')
        Text(`${item.description} · 建议游览 ${item.visit_minutes} 分钟`)
          .fontSize(11)
          .fontColor($r('app.color.text_secondary'))
          .maxLines(1)
        Text(`模拟人流 ${item.occupancy_bps / 100}% · 等待 ${item.wait_minutes} 分钟`)
          .fontSize(11)
          .fontColor($r('app.color.primary'))
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
    }
    .width('100%')
    .padding(14)
    .borderRadius(17)
    .backgroundColor($r('app.color.surface'))
    .onClick(() => {
      this.showAttractionDetail(item.id);
    })
  }

  build() {
    Scroll() {
      Column({ space: 16 }) {
        if (this.contentState !== ContentState.CONTENT) {
          StatePanel({
            state: this.contentState,
            message: this.errorMessage,
            onRetry: (): void => {
              this.loadAll();
              this.startCrowdSocket();
            }
          })
        } else {
          Row() {
            Column({ space: 3 }) {
              Text('景区示意地图')
                .fontSize(20)
                .fontWeight(FontWeight.Bold)
                .fontColor($r('app.color.text_primary'))
              Text(this.mapData === null ? 'Provider 未加载' :
                `Provider=${this.mapData.provider.mode} · demo=${this.mapData.provider.is_demo}`)
                .fontSize(11)
                .fontColor($r('app.color.warning'))
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)
            Toggle({ type: ToggleType.Switch, isOn: this.showHeat })
              .selectedColor($r('app.color.warning'))
              .onChange((value: boolean) => {
                this.showHeat = value;
              })
          }
          .width('100%')

          if (this.mapData !== null) {
            Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.SpaceBetween, alignContent: FlexAlign.SpaceBetween }) {
              ForEach(this.mapData.nodes, (node: GuideMapNode) => {
                this.mapNode(node)
              }, (node: GuideMapNode) => node.id)
            }
            .width('100%')
            .padding(12)
            .borderRadius(20)
            .backgroundColor($r('app.color.surface'))
            Text(this.mapData.provider.description)
              .width('100%')
              .fontSize(11)
              .fontColor($r('app.color.text_secondary'))
          }

          Row({ space: 8 }) {
            Button(this.locationDemo ? '已定位（演示）' : '定位演示')
              .fontSize(12)
              .fontColor(Color.White)
              .backgroundColor($r('app.color.primary'))
              .onClick(() => {
                this.locationDemo = !this.locationDemo;
              })
            Button('REST 刷新人流')
              .fontSize(12)
              .fontColor($r('app.color.warning'))
              .backgroundColor($r('app.color.surface_tint'))
              .onClick(() => {
                this.refreshCrowd();
              })
            Button('重连推送')
              .fontSize(12)
              .fontColor($r('app.color.primary'))
              .backgroundColor($r('app.color.surface_tint'))
              .onClick(() => {
                if (this.crowdSocket !== null) {
                  this.crowdSocket.stop();
                }
                this.startCrowdSocket();
              })
          }
          .width('100%')

          Text(`${this.socketMessage} · sequence=${this.crowdSequence} · source=simulated`)
            .width('100%')
            .padding(11)
            .borderRadius(12)
            .fontSize(11)
            .fontColor(this.socketState === CrowdSocketState.CONNECTED ? $r('app.color.success') : $r('app.color.warning'))
            .backgroundColor($r('app.color.surface_tint'))

          if (this.showHeat) {
            Row({ space: 8 }) {
              Text('低').fontColor($r('app.color.success'))
              Text('中').fontColor($r('app.color.warning'))
              Text('高').fontColor($r('app.color.error'))
              Text(`模拟热力快照 ${formatShanghaiDateTime(this.crowdCapturedAt)}`)
                .fontSize(11)
                .fontColor($r('app.color.text_secondary'))
                .layoutWeight(1)
            }
            .width('100%')
          }

          Text(this.alternativeSuggestion)
            .width('100%')
            .padding(13)
            .borderRadius(14)
            .fontSize(12)
            .fontColor($r('app.color.primary'))
            .backgroundColor($r('app.color.surface_tint'))

          Column({ space: 10 }) {
            Text('景区路线规划（示意图）')
              .width('100%')
              .fontSize(17)
              .fontWeight(FontWeight.Bold)
              .fontColor($r('app.color.text_primary'))
            Row({ space: 8 }) {
              Button(`起点：${this.nodeName(this.originNodeId)}`)
                .layoutWeight(1)
                .fontSize(11)
                .enabled(!this.routeBusy)
                .onClick(() => {
                  this.originNodeId = this.cycleNode(this.originNodeId);
                  this.invalidateRoute('起点已更新，请重新规划路线');
                })
              Button(`终点：${this.nodeName(this.targetNodeId)}`)
                .layoutWeight(1)
                .fontSize(11)
                .enabled(!this.routeBusy)
                .onClick(() => {
                  this.targetNodeId = this.cycleNode(this.targetNodeId);
                  this.invalidateRoute('终点已更新，请重新规划路线');
                })
            }
            .width('100%')
            if (this.routePlan === null) {
              Text(this.routeMessage)
                .width('100%')
                .padding(12)
                .borderRadius(12)
                .fontSize(12)
                .fontColor(this.routeBusy ? $r('app.color.primary') :
                  this.routeError ? $r('app.color.error') : $r('app.color.text_secondary'))
                .backgroundColor($r('app.color.surface_tint'))
            } else {
              Column({ space: 8 }) {
                Row() {
                  Text('路线规划完成')
                    .fontSize(16)
                    .fontWeight(FontWeight.Bold)
                    .fontColor($r('app.color.primary'))
                    .layoutWeight(1)
                  Text('普通步行路线')
                    .fontSize(10)
                    .fontColor($r('app.color.success'))
                }
                .width('100%')
                Text(this.routePathText())
                  .width('100%')
                  .fontSize(13)
                  .fontWeight(FontWeight.Medium)
                  .fontColor($r('app.color.text_primary'))
                Row({ space: 16 }) {
                  Text(`全程 ${this.routePlan.distance_m} 米`)
                    .fontSize(12)
                    .fontColor($r('app.color.primary'))
                  Text(`步行约 ${this.routePlan.walk_minutes} 分钟`)
                    .fontSize(12)
                    .fontColor($r('app.color.primary'))
                }
                .width('100%')
                Text(this.routePlan.explanation.join(' · '))
                  .width('100%')
                  .fontSize(10)
                  .fontColor($r('app.color.text_secondary'))
              }
              .width('100%')
              .padding(14)
              .borderRadius(14)
              .border({ width: 1, color: $r('app.color.primary') })
              .backgroundColor($r('app.color.surface_tint'))
            }
            Button(this.routeBusy ? '计算中…' : (this.routePlan === null ? '规划路线' : '重新规划路线'))
              .enabled(!this.routeBusy)
              .width('100%')
              .fontColor(Color.White)
              .backgroundColor($r('app.color.primary'))
              .onClick(() => {
                this.planAccessibleRoute();
              })
          }
          .width('100%')
          .padding(16)
          .borderRadius(19)
          .backgroundColor($r('app.color.surface'))

          Text('真实接口景点')
            .width('100%')
            .fontSize(18)
            .fontWeight(FontWeight.Bold)
            .fontColor($r('app.color.text_primary'))
          ForEach(this.attractions, (item: Attraction) => {
            this.attractionCard(item)
          }, (item: Attraction) => item.id)

          if (this.selectedDetail !== null) {
            Column({ space: 10 }) {
              Row() {
                Text(this.selectedDetail.name)
                  .fontSize(19)
                  .fontWeight(FontWeight.Bold)
                  .fontColor($r('app.color.text_primary'))
                  .layoutWeight(1)
                Button('关闭').fontSize(11).onClick(() => {
                  this.selectedDetail = null;
                  this.narrations = [];
                  this.playingNarrationId = '';
                })
              }
              .width('100%')
              Text(this.selectedDetail.description)
                .width('100%')
                .fontSize(13)
                .fontColor($r('app.color.text_secondary'))
              ForEach(this.narrations, (narration: Narration) => {
                Column({ space: 7 }) {
                  Row() {
                    Text(narration.title)
                      .fontWeight(FontWeight.Medium)
                      .fontColor($r('app.color.text_primary'))
                      .layoutWeight(1)
                    Button(this.playingNarrationId === narration.id ? '收起文字讲解' : '展开文字讲解')
                      .fontSize(11)
                      .fontColor($r('app.color.primary'))
                      .backgroundColor($r('app.color.surface_tint'))
                      .onClick(() => {
                        this.playingNarrationId = this.playingNarrationId === narration.id ? '' : narration.id;
                      })
                  }
                  .width('100%')
                  Text(narration.transcript)
                    .width('100%')
                    .fontSize(12)
                    .fontColor($r('app.color.text_secondary'))
                    .maxLines(this.playingNarrationId === narration.id ? 8 : 2)
                  // audio_url 是已落地的服务端扩展接口；空值时只提供策展文字，
                  // 不能把展开/收起文本包装成音频播放，也不请求摄像头或麦克风权限。
                  Text(narration.audio_url.length === 0 ?
                    `文字讲解 · provider=${narration.provider_mode} · 音频接口暂未提供可播放地址` :
                    `音频地址已由 ${narration.provider_mode} 提供 · 当前页面使用文字回退`)
                    .width('100%')
                    .fontSize(10)
                    .fontColor($r('app.color.warning'))
                }
                .width('100%')
                .padding(12)
                .borderRadius(13)
                .backgroundColor($r('app.color.page_background'))
              }, (narration: Narration) => narration.id)
            }
            .width('100%')
            .padding(17)
            .borderRadius(20)
            .backgroundColor($r('app.color.surface'))
          }

          if (this.operationMessage.length > 0) {
            Text(this.operationMessage)
              .width('100%')
              .fontSize(11)
              .fontColor($r('app.color.warning'))
          }
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
