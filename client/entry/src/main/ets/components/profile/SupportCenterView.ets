import { StatePanel } from '../StatePanel';
import { ContentState } from '../../models/AppModels';
import {
  FaqItem,
  FaqListResponse,
  FeedbackKind,
  FeedbackListResponse,
  FeedbackRecord,
  FeedbackStatus,
  SupportConversation,
  SupportConversationListResponse,
  SupportConversationStatus,
  SupportEventEnvelope,
  SupportMessage,
  SupportMessageListResponse
} from '../../models/ServiceModels';
import { ApiErrorCode, ApiErrorInfo } from '../../network/ApiError';
import { NetworkResult } from '../../network/HttpClient';
import { SupportSocket, SupportSocketState } from '../../network/SupportSocket';
import { ServiceService } from '../../network/services/ServiceService';
import {
  ServiceRuleResult,
  shouldAcceptSupportSequence,
  validateFeedback,
  validateFollowUp,
  validateSupportMessage
} from '../../utils/ServiceRules';
import { PendingIdempotentOperation } from '../../utils/TicketRules';

enum SupportSection {
  FEEDBACK = 0,
  FAQ = 1,
  CHAT = 2
}

@Component
export struct SupportCenterView {
  @Prop loggedIn: boolean = false;
  onLoginTap: () => void = (): void => {};
  @State section: SupportSection = SupportSection.FEEDBACK;
  @State contentState: ContentState = ContentState.LOADING;
  @State feedbackItems: FeedbackRecord[] = [];
  @State faqs: FaqItem[] = [];
  @State conversations: SupportConversation[] = [];
  @State selectedConversationId: string = '';
  @State selectedFeedbackId: string = '';
  @State expandedFaqId: string = '';
  @State messages: SupportMessage[] = [];
  @State lastMessageSequence: number = -1;
  @State feedbackKind: FeedbackKind = FeedbackKind.FEEDBACK;
  @State feedbackTitle: string = '';
  @State feedbackContent: string = '';
  @State followUpRating: number = 5;
  @State followUpComment: string = '问题已解决，感谢处理';
  @State conversationSubject: string = '景区服务咨询';
  @State messageContent: string = '';
  @State operationBusy: boolean = false;
  @State operationMessage: string = '';
  @State socketState: SupportSocketState = SupportSocketState.STOPPED;
  @State socketMessage: string = '尚未选择客服会话';
  private service: ServiceService = new ServiceService();
  private socket: SupportSocket | null = null;
  private messagePending: PendingIdempotentOperation = new PendingIdempotentOperation();

  aboutToAppear(): void {
    this.loadFaqs();
    if (this.loggedIn) {
      this.loadPrivateData();
    } else {
      this.contentState = ContentState.NO_PERMISSION;
    }
  }

  aboutToDisappear(): void {
    this.stopSocket();
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
    return error === null ? '游客服务请求失败，请稍后重试' : error.userMessage;
  }

  private requireLogin(message: string): boolean {
    if (this.loggedIn) {
      return true;
    }
    this.contentState = ContentState.NO_PERMISSION;
    this.operationMessage = message;
    return false;
  }

  private async loadFaqs(): Promise<void> {
    const result: NetworkResult<FaqListResponse> = await this.service.listFaqs();
    if (result.successful && result.data !== null) {
      this.faqs = result.data.items;
      if (!this.loggedIn) {
        this.contentState = ContentState.CONTENT;
      }
    } else if (!this.loggedIn) {
      this.contentState = this.stateForError(result.error);
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async loadPrivateData(): Promise<void> {
    this.contentState = ContentState.LOADING;
    const feedbackResult: NetworkResult<FeedbackListResponse> = await this.service.listFeedback();
    if (!feedbackResult.successful || feedbackResult.data === null) {
      this.contentState = this.stateForError(feedbackResult.error);
      this.operationMessage = this.errorText(feedbackResult.error);
      return;
    }
    this.feedbackItems = feedbackResult.data.items;
    const conversationResult: NetworkResult<SupportConversationListResponse> =
      await this.service.listConversations();
    if (!conversationResult.successful || conversationResult.data === null) {
      this.contentState = this.stateForError(conversationResult.error);
      this.operationMessage = this.errorText(conversationResult.error);
      return;
    }
    this.conversations = conversationResult.data.items;
    this.contentState = ContentState.CONTENT;
  }

  private selectedFeedback(): FeedbackRecord | null {
    for (let index: number = 0; index < this.feedbackItems.length; index++) {
      if (this.feedbackItems[index].id === this.selectedFeedbackId) {
        return this.feedbackItems[index];
      }
    }
    return null;
  }

  private selectedConversation(): SupportConversation | null {
    for (let index: number = 0; index < this.conversations.length; index++) {
      if (this.conversations[index].id === this.selectedConversationId) {
        return this.conversations[index];
      }
    }
    return null;
  }

  private replaceFeedback(value: FeedbackRecord): void {
    const updated: FeedbackRecord[] = this.feedbackItems.slice();
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
    this.feedbackItems = updated;
  }

  private replaceConversation(value: SupportConversation): void {
    const updated: SupportConversation[] = this.conversations.slice();
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
    this.conversations = updated;
  }

  private appendMessage(value: SupportMessage): void {
    for (let index: number = 0; index < this.messages.length; index++) {
      if (this.messages[index].id === value.id || this.messages[index].sequence === value.sequence) {
        return;
      }
    }
    const updated: SupportMessage[] = this.messages.slice();
    updated.push(value);
    updated.sort((first: SupportMessage, second: SupportMessage): number => first.sequence - second.sequence);
    this.messages = updated;
    this.lastMessageSequence = Math.max(this.lastMessageSequence, value.sequence);
  }

  private async createFeedback(): Promise<void> {
    if (!this.requireLogin('登录后才能提交反馈') || this.operationBusy) {
      return;
    }
    const validation: ServiceRuleResult = validateFeedback(
      this.feedbackKind, this.feedbackTitle, this.feedbackContent);
    if (!validation.valid) {
      this.operationMessage = validation.message;
      return;
    }
    this.operationBusy = true;
    const result: NetworkResult<FeedbackRecord> = await this.service.createFeedback(
      this.feedbackKind, this.feedbackTitle.trim(), this.feedbackContent.trim());
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.replaceFeedback(result.data);
      this.feedbackTitle = '';
      this.feedbackContent = '';
      this.operationMessage = `工单 ${result.data.ticket_no} 已提交，可持续查看处理状态`;
    } else {
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async followUp(): Promise<void> {
    const feedback: FeedbackRecord | null = this.selectedFeedback();
    if (feedback === null || this.operationBusy) {
      return;
    }
    const validation: ServiceRuleResult = validateFollowUp(this.followUpRating, this.followUpComment);
    if (!validation.valid) {
      this.operationMessage = validation.message;
      return;
    }
    this.operationBusy = true;
    const result: NetworkResult<FeedbackRecord> = await this.service.followUpFeedback(
      feedback.id, this.followUpRating, this.followUpComment.trim());
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.replaceFeedback(result.data);
      this.operationMessage = `工单 ${result.data.ticket_no} 的回访与 ${this.followUpRating} 星评分已保存`;
    } else {
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async createConversation(): Promise<void> {
    if (!this.requireLogin('登录后才能创建持久化客服会话') || this.operationBusy) {
      return;
    }
    if (this.conversationSubject.trim().length < 2 || this.conversationSubject.trim().length > 160) {
      this.operationMessage = '会话主题应为 2 至 160 个字符';
      return;
    }
    this.operationBusy = true;
    const result: NetworkResult<SupportConversation> =
      await this.service.createConversation(this.conversationSubject.trim());
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.replaceConversation(result.data);
      await this.selectConversation(result.data);
      this.operationMessage = `客服会话已创建；provider=${result.data.provider}/demo=${result.data.is_demo}`;
    } else {
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async selectConversation(value: SupportConversation): Promise<void> {
    this.selectedConversationId = value.id;
    this.stopSocket();
    const result: NetworkResult<SupportMessageListResponse> = await this.service.listMessages(value.id);
    if (!result.successful || result.data === null) {
      this.operationMessage = this.errorText(result.error);
      return;
    }
    this.messages = result.data.items;
    this.lastMessageSequence = -1;
    for (let index: number = 0; index < this.messages.length; index++) {
      this.lastMessageSequence = Math.max(this.lastMessageSequence, this.messages[index].sequence);
    }
    if (value.status === SupportConversationStatus.OPEN) {
      this.connectSocket(value.id);
    } else {
      this.socketState = SupportSocketState.STOPPED;
      this.socketMessage = '会话已关闭，展示服务端持久化历史';
    }
  }

  private connectSocket(conversationId: string): void {
    this.socket = new SupportSocket(conversationId, (event: SupportEventEnvelope): void => {
      if (event.data.conversation.id !== this.selectedConversationId) {
        return;
      }
      this.replaceConversation(event.data.conversation);
      if (event.data.message !== null &&
        shouldAcceptSupportSequence(this.lastMessageSequence, event.data.message.sequence)) {
        this.appendMessage(event.data.message);
      }
      if (event.data.conversation.status === SupportConversationStatus.CLOSED) {
        this.stopSocket();
        this.socketMessage = '会话已关闭，实时连接与自动重连已停止';
      }
    }, (state: SupportSocketState, message: string): void => {
      this.socketState = state;
      this.socketMessage = message;
    });
    this.socket.start();
  }

  private stopSocket(): void {
    if (this.socket !== null) {
      this.socket.stop();
      this.socket = null;
    }
  }

  private async sendMessage(): Promise<void> {
    const conversation: SupportConversation | null = this.selectedConversation();
    if (conversation === null || conversation.status !== SupportConversationStatus.OPEN || this.operationBusy) {
      return;
    }
    const validation: ServiceRuleResult = validateSupportMessage(this.messageContent);
    if (!validation.valid) {
      this.operationMessage = validation.message;
      return;
    }
    const operationId: string = `${conversation.id}:${this.messageContent.trim()}`;
    const key: string = this.messagePending.getOrCreate(operationId, 'support-message');
    this.operationBusy = true;
    const result: NetworkResult<SupportMessageListResponse> = await this.service.sendMessage(
      conversation.id, this.messageContent.trim(), key);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.messagePending.resolveSuccess();
      for (let index: number = 0; index < result.data.items.length; index++) {
        this.appendMessage(result.data.items[index]);
      }
      this.messageContent = '';
      this.operationMessage = '消息已持久化，等待客服或 DemoSupportBot 实时回复';
    } else {
      if (result.error !== null) {
        this.messagePending.resolveFailure(result.error.statusCode, result.error.retriable);
      }
      this.operationMessage = this.errorText(result.error);
    }
  }

  @Builder
  private sectionButton(label: string, value: SupportSection) {
    Button(label).layoutWeight(1).fontSize(11)
      .fontColor(this.section === value ? Color.White : $r('app.color.primary'))
      .backgroundColor(this.section === value ? $r('app.color.primary') : $r('app.color.surface_tint'))
      .onClick(() => { this.section = value; })
  }

  @Builder
  private feedbackKindButton(label: string, value: FeedbackKind) {
    Button(label).layoutWeight(1).fontSize(10)
      .fontColor(this.feedbackKind === value ? Color.White : $r('app.color.primary'))
      .backgroundColor(this.feedbackKind === value ? $r('app.color.primary') : $r('app.color.surface_tint'))
      .onClick(() => { this.feedbackKind = value; })
  }

  @Builder
  private noAuthPanel() {
    StatePanel({ state: ContentState.NO_PERMISSION, message: '登录后使用反馈工单与持久化客服会话' })
    Button('立即登录').width('100%').fontColor(Color.White).backgroundColor($r('app.color.primary'))
      .onClick(() => { this.onLoginTap(); })
  }

  @Builder
  private feedbackSectionContent() {
    if (!this.loggedIn) {
      this.noAuthPanel()
    } else {
      Column({ space: 7 }) {
        Row({ space: 6 }) {
          this.feedbackKindButton('反馈', FeedbackKind.FEEDBACK)
          this.feedbackKindButton('投诉', FeedbackKind.COMPLAINT)
          this.feedbackKindButton('建议', FeedbackKind.SUGGESTION)
        }.width('100%')
        TextInput({ text: this.feedbackTitle, placeholder: '标题' }).width('100%')
          .onChange((value: string) => { this.feedbackTitle = value; })
        TextArea({ text: this.feedbackContent, placeholder: '详细描述' }).width('100%').height(90)
          .onChange((value: string) => { this.feedbackContent = value; })
        Button(this.operationBusy ? '提交中…' : '提交服务端工单').enabled(!this.operationBusy).width('100%')
          .fontColor(Color.White).backgroundColor($r('app.color.primary')).onClick(() => { this.createFeedback(); })
      }.width('100%').padding(13).borderRadius(15).backgroundColor($r('app.color.surface'))
      ForEach(this.feedbackItems, (item: FeedbackRecord) => {
        Column({ space: 5 }) {
          Row() {
            Text(`${item.ticket_no} · ${item.title}`).fontWeight(FontWeight.Medium)
              .fontColor($r('app.color.text_primary')).layoutWeight(1)
            Text(item.status).fontSize(10).fontColor(item.status === FeedbackStatus.RESOLVED ?
              $r('app.color.success') : $r('app.color.warning'))
          }.width('100%')
          Text(`${item.kind} · 优先级 ${item.priority} · ${item.latest_response ?? '等待处理'}`).width('100%').fontSize(9)
            .fontColor($r('app.color.text_secondary')).maxLines(2)
          Button(this.selectedFeedbackId === item.id ? '已选择回访' : '回访/评分').fontSize(10)
            .onClick(() => { this.selectedFeedbackId = item.id; })
        }.width('100%').padding(12).borderRadius(13).backgroundColor($r('app.color.surface'))
      }, (item: FeedbackRecord) => item.id)
      if (this.selectedFeedback() !== null) {
        Column({ space: 6 }) {
          Row({ space: 6 }) {
            Button('−').onClick(() => { this.followUpRating = Math.max(1, this.followUpRating - 1); })
            Text(`${this.followUpRating} 星`).fontColor($r('app.color.primary'))
            Button('+').onClick(() => { this.followUpRating = Math.min(5, this.followUpRating + 1); })
          }.width('100%')
          TextInput({ text: this.followUpComment, placeholder: '回访内容' }).width('100%')
            .onChange((value: string) => { this.followUpComment = value; })
          Button(this.operationBusy ? '保存中…' : '保存回访与评分').enabled(!this.operationBusy).width('100%')
            .fontColor(Color.White).backgroundColor($r('app.color.primary')).onClick(() => { this.followUp(); })
        }.width('100%').padding(12).borderRadius(14).backgroundColor($r('app.color.surface_tint'))
      }
    }
  }

  @Builder
  private faqContent() {
    if (this.faqs.length === 0) {
      StatePanel({ state: ContentState.EMPTY, message: '暂无常见问题' })
    } else {
      ForEach(this.faqs, (item: FaqItem) => {
        Column({ space: 5 }) {
          Row() {
            Text(`${item.category} · ${item.question}`).fontWeight(FontWeight.Medium)
              .fontColor($r('app.color.text_primary')).layoutWeight(1)
            Text(this.expandedFaqId === item.id ? '收起' : '查看').fontSize(10).fontColor($r('app.color.primary'))
          }.width('100%')
          if (this.expandedFaqId === item.id) {
            Text(item.answer).width('100%').fontSize(11).fontColor($r('app.color.text_secondary'))
          }
        }.width('100%').padding(12).borderRadius(13).backgroundColor($r('app.color.surface'))
          .onClick(() => { this.expandedFaqId = this.expandedFaqId === item.id ? '' : item.id; })
      }, (item: FaqItem) => item.id)
    }
  }

  @Builder
  private chatContent() {
    if (!this.loggedIn) {
      this.noAuthPanel()
    } else {
      Row({ space: 7 }) {
        TextInput({ text: this.conversationSubject, placeholder: '会话主题' }).layoutWeight(1)
          .onChange((value: string) => { this.conversationSubject = value; })
        Button('新建会话').enabled(!this.operationBusy).fontColor(Color.White)
          .backgroundColor($r('app.color.primary')).onClick(() => { this.createConversation(); })
      }.width('100%')
      Scroll() {
        Row({ space: 7 }) {
          ForEach(this.conversations, (conversation: SupportConversation) => {
            Button(conversation.subject).fontSize(10).fontColor(this.selectedConversationId === conversation.id ?
              Color.White : $r('app.color.primary')).backgroundColor(this.selectedConversationId === conversation.id ?
              $r('app.color.primary') : $r('app.color.surface_tint')).onClick(() => {
                this.selectConversation(conversation);
              })
          }, (conversation: SupportConversation) => conversation.id)
        }
      }.width('100%').scrollable(ScrollDirection.Horizontal).scrollBar(BarState.Off)
      if (this.selectedConversation() !== null) {
        Text(`${this.socketMessage} · provider=${this.selectedConversation()?.provider ?? 'unknown'}/` +
          `demo=${this.selectedConversation()?.is_demo ?? false}`).width('100%').fontSize(9)
          .fontColor(this.socketState === SupportSocketState.CONNECTED ?
            $r('app.color.success') : $r('app.color.warning'))
        ForEach(this.messages, (message: SupportMessage) => {
          Column({ space: 3 }) {
            Text(`${message.sender_name} · #${message.sequence}`).width('100%').fontSize(9)
              .fontColor($r('app.color.text_secondary'))
            Text(message.content).width('100%').fontColor($r('app.color.text_primary'))
            Text(`provider=${message.provider}/demo=${message.is_demo}`).width('100%').fontSize(8)
              .fontColor($r('app.color.warning'))
          }.width('100%').padding(10).borderRadius(12).backgroundColor(message.sender_type === 'TOURIST' ?
            $r('app.color.surface_tint') : $r('app.color.surface'))
        }, (message: SupportMessage) => message.id)
        if (this.selectedConversation()?.status === SupportConversationStatus.OPEN) {
          Row({ space: 7 }) {
            TextInput({ text: this.messageContent, placeholder: '输入客服消息' }).layoutWeight(1)
              .onChange((value: string) => { this.messageContent = value; })
            Button(this.operationBusy ? '发送中' : '发送').enabled(!this.operationBusy)
              .fontColor(Color.White).backgroundColor($r('app.color.primary')).onClick(() => { this.sendMessage(); })
          }.width('100%')
        }
      } else if (this.conversations.length === 0) {
        StatePanel({ state: ContentState.EMPTY, message: '暂无客服会话，可新建会话' })
      }
    }
  }

  build() {
    Column({ space: 11 }) {
      Text('游客服务中心').width('100%').fontSize(18).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.text_primary'))
      Text('反馈工单与客服消息由服务端持久化；自动回复明确标记 DemoSupportBot。').width('100%')
        .fontSize(9).fontColor($r('app.color.warning'))
      Row({ space: 6 }) {
        this.sectionButton('反馈/投诉', SupportSection.FEEDBACK)
        this.sectionButton('FAQ', SupportSection.FAQ)
        this.sectionButton('在线客服', SupportSection.CHAT)
      }.width('100%')
      if (this.contentState !== ContentState.CONTENT && this.loggedIn) {
        StatePanel({ state: this.contentState, message: this.operationMessage,
          onRetry: (): void => { this.loadPrivateData(); } })
      }
      if (this.section === SupportSection.FEEDBACK) {
        this.feedbackSectionContent()
      } else if (this.section === SupportSection.FAQ) {
        this.faqContent()
      } else {
        this.chatContent()
      }
      if (this.operationMessage.length > 0) {
        Text(this.operationMessage).width('100%').padding(9).fontSize(9).borderRadius(10)
          .fontColor($r('app.color.warning')).backgroundColor($r('app.color.surface_tint'))
      }
    }.width('100%')
  }
}
