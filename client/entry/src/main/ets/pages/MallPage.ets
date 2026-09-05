import { StatePanel } from '../components/StatePanel';
import { ContentState } from '../models/AppModels';
import {
  CartItem,
  PointsAccount,
  PointsLedgerEntry,
  PointsLedgerResponse,
  PointsRedemption,
  PointsReward,
  PointsRewardListResponse,
  ShareRecord,
  ShopCampaign,
  ShopCampaignListResponse,
  ShopCategory,
  ShopCategoryListResponse,
  ShopOrder,
  ShopOrderListResponse,
  ShopOrderStatus,
  ShopProduct,
  ShopProductListResponse,
  ShoppingCart
} from '../models/ShopModels';
import { ApiErrorCode, ApiErrorInfo } from '../network/ApiError';
import { NetworkResult } from '../network/HttpClient';
import { ShopService } from '../network/services/ShopService';
import {
  ShopRuleResult,
  canPayShopOrder,
  effectiveProductPrice,
  validateCartQuantity,
  validateCheckout,
  validateRewardRedemption,
  validateShare
} from '../utils/ShopRules';
import { PendingIdempotentOperation, formatMoney } from '../utils/TicketRules';
import { formatShanghaiDateTime } from '../utils/DateTimeRules';
import { AuthStore } from '../stores/AuthStore';
import { TravelPersistenceStore } from '../stores/TravelPersistenceStore';
import { isWideWindow } from '../utils/ResponsiveRules';

enum MallSection {
  CATALOG = 0,
  CART = 1,
  ORDERS = 2,
  POINTS = 3
}

@Component
export struct MallPage {
  @Prop loggedIn: boolean = false;
  onLoginTap: () => void = (): void => {};
  @State section: MallSection = MallSection.CATALOG;
  @State catalogState: ContentState = ContentState.LOADING;
  @State privateState: ContentState = ContentState.CONTENT;
  @State categories: ShopCategory[] = [];
  @State products: ShopProduct[] = [];
  @State campaigns: ShopCampaign[] = [];
  @State selectedCategoryId: string = '';
  @State cart: ShoppingCart | null = null;
  @State orders: ShopOrder[] = [];
  @State pointsAccount: PointsAccount | null = null;
  @State ledger: PointsLedgerEntry[] = [];
  @State rewards: PointsReward[] = [];
  @State selectedRewardId: string = '';
  @State shareRefId: string = '';
  @State shareCaption: string = '分享我的景区好物发现';
  @State sharePlatform: string = 'demo_moments';
  @State deliveryName: string = '演示游客';
  @State deliveryPhone: string = '13800138000';
  @State deliveryProvince: string = '浙江省';
  @State deliveryCity: string = '杭州市';
  @State deliveryAddress: string = '智慧景区游客中心自提点';
  @State deliveryPostalCode: string = '';
  @State operationMessage: string = '';
  @State operationBusy: boolean = false;
  @State errorMessage: string = '';
  @State isWide: boolean = false;
  private service: ShopService = new ShopService();
  private checkoutPending: PendingIdempotentOperation = new PendingIdempotentOperation();
  private payPending: PendingIdempotentOperation = new PendingIdempotentOperation();
  private redeemPending: PendingIdempotentOperation = new PendingIdempotentOperation();
  private sharePending: PendingIdempotentOperation = new PendingIdempotentOperation();

  aboutToAppear(): void {
    this.loadCatalog();
    if (this.loggedIn) {
      this.loadPrivateData();
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
    return error === null ? '商城服务请求失败，请稍后重试' : error.userMessage;
  }

  private resolveFailure(pending: PendingIdempotentOperation, error: ApiErrorInfo | null): void {
    if (error !== null) {
      pending.resolveFailure(error.statusCode, error.retriable);
    }
  }

  private requireLogin(message: string): boolean {
    if (this.loggedIn) {
      return true;
    }
    this.privateState = ContentState.NO_PERMISSION;
    this.operationMessage = message;
    return false;
  }

  private async loadCatalog(): Promise<void> {
    this.catalogState = ContentState.LOADING;
    const categoryResult: NetworkResult<ShopCategoryListResponse> = await this.service.listCategories();
    if (!categoryResult.successful || categoryResult.data === null) {
      this.catalogState = this.stateForError(categoryResult.error);
      this.errorMessage = this.errorText(categoryResult.error);
      return;
    }
    this.categories = categoryResult.data.items;
    const campaignResult: NetworkResult<ShopCampaignListResponse> = await this.service.listCampaigns();
    if (!campaignResult.successful || campaignResult.data === null) {
      this.catalogState = this.stateForError(campaignResult.error);
      this.errorMessage = this.errorText(campaignResult.error);
      return;
    }
    this.campaigns = campaignResult.data.items;
    await this.loadProducts();
  }

  private async loadProducts(): Promise<void> {
    this.catalogState = ContentState.LOADING;
    const result: NetworkResult<ShopProductListResponse> = await this.service.listProducts(this.selectedCategoryId);
    if (!result.successful || result.data === null) {
      this.catalogState = this.stateForError(result.error);
      this.errorMessage = this.errorText(result.error);
      return;
    }
    this.products = result.data.items;
    if (this.shareRefId.length === 0 && this.products.length > 0) {
      this.shareRefId = this.products[0].id;
    }
    this.catalogState = this.products.length === 0 ? ContentState.EMPTY : ContentState.CONTENT;
  }

  private async loadPrivateData(): Promise<void> {
    if (!this.loggedIn) {
      this.privateState = ContentState.NO_PERMISSION;
      return;
    }
    this.privateState = ContentState.LOADING;
    const cartResult: NetworkResult<ShoppingCart> = await this.service.getCart();
    if (!cartResult.successful || cartResult.data === null) {
      this.privateState = this.stateForError(cartResult.error);
      this.operationMessage = this.errorText(cartResult.error);
      return;
    }
    this.cart = cartResult.data;
    const orderResult: NetworkResult<ShopOrderListResponse> = await this.service.listOrders();
    if (!orderResult.successful || orderResult.data === null) {
      this.privateState = this.stateForError(orderResult.error);
      this.operationMessage = this.errorText(orderResult.error);
      return;
    }
    this.orders = orderResult.data.items;
    TravelPersistenceStore.getInstance().saveShopOrders(AuthStore.getInstance().getUserId(), this.orders);
    const accountResult: NetworkResult<PointsAccount> = await this.service.getPointsAccount();
    if (!accountResult.successful || accountResult.data === null) {
      this.privateState = this.stateForError(accountResult.error);
      this.operationMessage = this.errorText(accountResult.error);
      return;
    }
    this.pointsAccount = accountResult.data;
    const ledgerResult: NetworkResult<PointsLedgerResponse> = await this.service.listPointsLedger();
    if (ledgerResult.successful && ledgerResult.data !== null) {
      this.ledger = ledgerResult.data.items;
    }
    const rewardsResult: NetworkResult<PointsRewardListResponse> = await this.service.listRewards();
    if (rewardsResult.successful && rewardsResult.data !== null) {
      this.rewards = rewardsResult.data.items;
      if (this.selectedRewardId.length === 0 && this.rewards.length > 0) {
        this.selectedRewardId = this.rewards[0].id;
      }
    }
    this.privateState = ContentState.CONTENT;
  }

  private selectedReward(): PointsReward | null {
    for (let index: number = 0; index < this.rewards.length; index++) {
      if (this.rewards[index].id === this.selectedRewardId) {
        return this.rewards[index];
      }
    }
    return null;
  }

  private replaceOrder(value: ShopOrder): void {
    const updated: ShopOrder[] = this.orders.slice();
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
    this.orders = updated;
    TravelPersistenceStore.getInstance().saveShopOrders(AuthStore.getInstance().getUserId(), this.orders);
  }

  private async addToCart(product: ShopProduct): Promise<void> {
    if (!this.requireLogin('登录后才能同步购物车') || this.operationBusy) {
      return;
    }
    const validation: ShopRuleResult = validateCartQuantity(1, product.stock);
    if (!validation.valid) {
      this.operationMessage = validation.message;
      return;
    }
    this.operationBusy = true;
    const result: NetworkResult<ShoppingCart> = await this.service.addCartItem(product.id, 1);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.cart = result.data;
      this.operationMessage = `${product.name} 已加入服务端购物车`;
    } else {
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async updateCartItem(item: CartItem, quantity: number): Promise<void> {
    if (this.operationBusy) {
      return;
    }
    if (quantity <= 0) {
      await this.removeCartItem(item);
      return;
    }
    const validation: ShopRuleResult = validateCartQuantity(quantity, item.stock);
    if (!validation.valid) {
      this.operationMessage = validation.message;
      return;
    }
    this.operationBusy = true;
    const result: NetworkResult<ShoppingCart> = await this.service.updateCartItem(item.id, quantity);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.cart = result.data;
      this.operationMessage = '购物车数量已同步';
    } else {
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async removeCartItem(item: CartItem): Promise<void> {
    if (this.operationBusy) {
      return;
    }
    this.operationBusy = true;
    const result: NetworkResult<ShoppingCart> = await this.service.removeCartItem(item.id);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.cart = result.data;
      this.operationMessage = `${item.product_name} 已移出购物车`;
    } else {
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async checkout(): Promise<void> {
    if (this.cart === null || this.operationBusy || !this.requireLogin('登录后才能结算')) {
      return;
    }
    const validation: ShopRuleResult = validateCheckout(this.cart.items, this.deliveryName, this.deliveryPhone,
      this.deliveryProvince, this.deliveryCity, this.deliveryAddress);
    if (!validation.valid) {
      this.operationMessage = validation.message;
      return;
    }
    const operationId: string = `${this.cart.id}:${this.cart.total_quantity}:${this.cart.total_cents}:` +
      `${this.deliveryName.trim()}:${this.deliveryPhone.trim()}:${this.deliveryAddress.trim()}`;
    const key: string = this.checkoutPending.getOrCreate(operationId, 'shop-checkout');
    this.operationBusy = true;
    const result: NetworkResult<ShopOrder> = await this.service.checkout(
      this.deliveryName.trim(), this.deliveryPhone.trim(), this.deliveryProvince.trim(), this.deliveryCity.trim(),
      this.deliveryAddress.trim(), this.deliveryPostalCode.trim(), key);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.checkoutPending.resolveSuccess();
      this.replaceOrder(result.data);
      this.operationMessage = `订单 ${result.data.order_no} 已创建，等待演示支付`;
      await this.loadPrivateData();
      this.section = MallSection.ORDERS;
    } else {
      this.resolveFailure(this.checkoutPending, result.error);
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async payOrder(value: ShopOrder): Promise<void> {
    if (this.operationBusy || !canPayShopOrder(value.status)) {
      return;
    }
    const key: string = this.payPending.getOrCreate(value.id, 'shop-demo-pay');
    this.operationBusy = true;
    const result: NetworkResult<ShopOrder> = await this.service.payOrder(value.id, key);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.payPending.resolveSuccess();
      this.replaceOrder(result.data);
      this.operationMessage = `演示支付完成，到账 ${result.data.points_awarded} 积分；未接真实支付`;
      await this.loadPrivateData();
    } else {
      this.resolveFailure(this.payPending, result.error);
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async redeem(): Promise<void> {
    if (this.operationBusy || !this.requireLogin('登录后才能兑换积分奖励')) {
      return;
    }
    const reward: PointsReward | null = this.selectedReward();
    const balance: number = this.pointsAccount === null ? 0 : this.pointsAccount.balance;
    const validation: ShopRuleResult = validateRewardRedemption(balance, reward);
    if (!validation.valid || reward === null) {
      this.operationMessage = validation.message;
      return;
    }
    const key: string = this.redeemPending.getOrCreate(reward.id, 'points-redeem');
    this.operationBusy = true;
    const result: NetworkResult<PointsRedemption> = await this.service.redeemReward(reward.id, key);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.redeemPending.resolveSuccess();
      this.operationMessage = `兑换 ${result.data.reward_name} 成功，扣除 ${result.data.points_spent} 积分`;
      await this.loadPrivateData();
    } else {
      this.resolveFailure(this.redeemPending, result.error);
      this.operationMessage = this.errorText(result.error);
    }
  }

  private async shareContent(): Promise<void> {
    if (this.operationBusy || !this.requireLogin('登录后才能记录内容分享并获得积分')) {
      return;
    }
    const validation: ShopRuleResult = validateShare('PRODUCT', this.shareRefId, this.shareCaption);
    if (!validation.valid) {
      this.operationMessage = validation.message;
      return;
    }
    const operationId: string = `PRODUCT:${this.shareRefId}:${this.sharePlatform}:${this.shareCaption.trim()}`;
    const key: string = this.sharePending.getOrCreate(operationId, 'content-share');
    this.operationBusy = true;
    const result: NetworkResult<ShareRecord> = await this.service.shareContent(
      'PRODUCT', this.shareRefId, this.sharePlatform, this.shareCaption.trim(), key);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.sharePending.resolveSuccess();
      this.operationMessage = `分享记录已验证并奖励 ${result.data.points_awarded} 分；` +
        `provider=${result.data.provider}/demo=${result.data.is_demo}`;
      await this.loadPrivateData();
    } else {
      this.resolveFailure(this.sharePending, result.error);
      this.operationMessage = this.errorText(result.error);
    }
  }

  @Builder
  private sectionButton(label: string, value: MallSection) {
    Button(label).layoutWeight(1).fontSize(12)
      .fontColor(this.section === value ? Color.White : $r('app.color.primary'))
      .backgroundColor(this.section === value ? $r('app.color.primary') : $r('app.color.surface_tint'))
      .onClick(() => {
        this.section = value;
        if (value !== MallSection.CATALOG && this.loggedIn && this.cart === null) {
          this.loadPrivateData();
        }
      })
  }

  @Builder
  private productCard(product: ShopProduct) {
    Column({ space: 7 }) {
      Text(product.name).width('100%').fontSize(15).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.text_primary')).maxLines(2)
      Text(product.description).width('100%').fontSize(10).fontColor($r('app.color.text_secondary')).maxLines(2)
      Text(product.tags.join(' · ')).width('100%').fontSize(9).fontColor($r('app.color.primary')).maxLines(1)
      if ((product.campaign_name ?? '').length > 0) {
        Text(`限时：${product.campaign_name ?? ''}`).width('100%').fontSize(10).fontColor($r('app.color.warning'))
      }
      Row() {
        Column({ space: 2 }) {
          Text(formatMoney(effectiveProductPrice(product))).fontSize(16).fontWeight(FontWeight.Bold)
            .fontColor($r('app.color.error'))
          if (effectiveProductPrice(product) < product.price_cents) {
            Text(`原价 ${formatMoney(product.price_cents)}`).fontSize(9).fontColor($r('app.color.text_secondary'))
          }
        }.alignItems(HorizontalAlign.Start).layoutWeight(1)
        Text(`库存 ${product.stock}`).fontSize(10).fontColor(product.stock > 0 ?
          $r('app.color.success') : $r('app.color.error'))
      }.width('100%')
      Row({ space: 6 }) {
        Button(this.operationBusy ? '处理中' : '加入购物车').enabled(!this.operationBusy && product.stock > 0)
          .layoutWeight(1).fontSize(11).fontColor(Color.White).backgroundColor($r('app.color.primary'))
          .onClick(() => { this.addToCart(product); })
        Button('设为分享').layoutWeight(1).fontSize(11).fontColor($r('app.color.primary'))
          .backgroundColor($r('app.color.surface_tint')).onClick(() => {
            this.shareRefId = product.id; this.section = MallSection.POINTS;
          })
      }.width('100%')
      Text(`provider=${product.provider} · demo=${product.is_demo}`).width('100%').fontSize(8)
        .fontColor($r('app.color.warning'))
    }.width(this.isWide ? '31%' : '48%').height(205).padding(12).borderRadius(18)
      .backgroundColor($r('app.color.surface'))
  }

  @Builder
  private privateStatePanel() {
    if (!this.loggedIn) {
      StatePanel({ state: ContentState.NO_PERMISSION, message: '登录后查看购物车、订单和积分数据' })
      Button('立即登录').width('100%').fontColor(Color.White).backgroundColor($r('app.color.primary'))
        .onClick(() => { this.onLoginTap(); })
    } else if (this.privateState !== ContentState.CONTENT) {
      StatePanel({ state: this.privateState, message: this.operationMessage,
        onRetry: (): void => { this.loadPrivateData(); } })
    }
  }

  @Builder
  private catalogContent() {
    if (this.campaigns.length > 0) {
      Scroll() {
        Row({ space: 10 }) {
          ForEach(this.campaigns, (campaign: ShopCampaign) => {
            Column({ space: 4 }) {
              Text(campaign.name).fontWeight(FontWeight.Bold).fontColor(Color.White)
              Text(`${campaign.discount_bps / 100}% 优惠 · ${campaign.description}`).fontSize(10)
                .fontColor('#E8F2FF').maxLines(2)
              Text(`demo=${campaign.is_demo}`).fontSize(8).fontColor('#E8F2FF')
            }.width(230).height(82).padding(12).alignItems(HorizontalAlign.Start).borderRadius(15)
              .backgroundColor($r('app.color.primary'))
          }, (campaign: ShopCampaign) => campaign.id)
        }
      }.width('100%').scrollable(ScrollDirection.Horizontal).scrollBar(BarState.Off)
    }
    Scroll() {
      Row({ space: 8 }) {
        Button('全部').fontSize(11).fontColor(this.selectedCategoryId.length === 0 ? Color.White :
          $r('app.color.primary')).backgroundColor(this.selectedCategoryId.length === 0 ? $r('app.color.primary') :
          $r('app.color.surface_tint')).onClick(() => { this.selectedCategoryId = ''; this.loadProducts(); })
        ForEach(this.categories, (category: ShopCategory) => {
          Button(category.name).fontSize(11).fontColor(this.selectedCategoryId === category.id ? Color.White :
            $r('app.color.primary')).backgroundColor(this.selectedCategoryId === category.id ?
            $r('app.color.primary') : $r('app.color.surface_tint')).onClick(() => {
              this.selectedCategoryId = category.id; this.loadProducts();
            })
        }, (category: ShopCategory) => category.id)
      }
    }.width('100%').scrollable(ScrollDirection.Horizontal).scrollBar(BarState.Off)
    if (this.catalogState !== ContentState.CONTENT) {
      StatePanel({ state: this.catalogState, message: this.errorMessage,
        onRetry: (): void => { this.loadCatalog(); } })
    } else {
      Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.SpaceBetween }) {
        ForEach(this.products, (product: ShopProduct) => { this.productCard(product) },
          (product: ShopProduct) => product.id)
      }.width('100%')
    }
  }

  @Builder
  private cartContent() {
    this.privateStatePanel()
    if (this.loggedIn && this.privateState === ContentState.CONTENT && this.cart !== null) {
      if (this.cart.items.length === 0) {
        StatePanel({ state: ContentState.EMPTY, message: '购物车为空，可返回商品页添加' })
      } else {
        ForEach(this.cart.items, (item: CartItem) => {
          Row({ space: 8 }) {
            Column({ space: 3 }) {
              Text(item.product_name).fontWeight(FontWeight.Medium).fontColor($r('app.color.text_primary'))
              Text(`${formatMoney(item.unit_price_cents)} × ${item.quantity} = ${formatMoney(item.subtotal_cents)}`)
                .fontSize(10).fontColor($r('app.color.text_secondary'))
            }.alignItems(HorizontalAlign.Start).layoutWeight(1)
            Button('−').enabled(!this.operationBusy).onClick(() => { this.updateCartItem(item, item.quantity - 1); })
            Text(item.quantity.toString()).fontColor($r('app.color.primary'))
            Button('+').enabled(!this.operationBusy && item.quantity < item.stock)
              .onClick(() => { this.updateCartItem(item, item.quantity + 1); })
            Button('移除').enabled(!this.operationBusy).fontSize(10).fontColor($r('app.color.error'))
              .onClick(() => { this.removeCartItem(item); })
          }.width('100%').padding(12).borderRadius(14).backgroundColor($r('app.color.surface'))
        }, (item: CartItem) => item.id)
        Column({ space: 7 }) {
          Text(`商品 ${this.cart.total_quantity} 件 · 小计 ${formatMoney(this.cart.subtotal_cents)} · ` +
            `优惠 ${formatMoney(this.cart.discount_cents)} · 应付 ${formatMoney(this.cart.total_cents)}`)
            .width('100%').fontWeight(FontWeight.Bold).fontColor($r('app.color.error'))
          Row({ space: 7 }) {
            TextInput({ text: this.deliveryName, placeholder: '收货人' }).layoutWeight(1)
              .onChange((value: string) => { this.deliveryName = value; })
            TextInput({ text: this.deliveryPhone, placeholder: '联系电话' }).layoutWeight(1)
              .onChange((value: string) => { this.deliveryPhone = value; })
          }.width('100%')
          Row({ space: 7 }) {
            TextInput({ text: this.deliveryProvince, placeholder: '省份' }).layoutWeight(1)
              .onChange((value: string) => { this.deliveryProvince = value; })
            TextInput({ text: this.deliveryCity, placeholder: '城市' }).layoutWeight(1)
              .onChange((value: string) => { this.deliveryCity = value; })
            TextInput({ text: this.deliveryPostalCode, placeholder: '邮编（选填）' }).layoutWeight(1)
              .onChange((value: string) => { this.deliveryPostalCode = value; })
          }.width('100%')
          TextInput({ text: this.deliveryAddress, placeholder: '详细配送地址' }).width('100%')
            .onChange((value: string) => { this.deliveryAddress = value; })
          Button(this.operationBusy ? '结算中…' : '确认配送并结算').enabled(!this.operationBusy).width('100%')
            .fontColor(Color.White).backgroundColor($r('app.color.primary')).onClick(() => { this.checkout(); })
          Text('价格、优惠和库存均由服务端重算；客户端不提交金额。').width('100%').fontSize(9)
            .fontColor($r('app.color.warning'))
        }.width('100%').padding(14).borderRadius(16).backgroundColor($r('app.color.surface'))
      }
    }
  }

  @Builder
  private ordersContent() {
    this.privateStatePanel()
    if (this.loggedIn && this.privateState === ContentState.CONTENT) {
      if (this.orders.length === 0) {
        StatePanel({ state: ContentState.EMPTY, message: '暂无商城订单' })
      } else {
        ForEach(this.orders, (order: ShopOrder) => {
          Column({ space: 6 }) {
            Row() {
              Text(order.order_no).fontWeight(FontWeight.Bold).fontColor($r('app.color.text_primary')).layoutWeight(1)
              Text(order.status).fontSize(11).fontColor(order.status === ShopOrderStatus.PAID ?
                $r('app.color.success') : $r('app.color.warning'))
            }.width('100%')
            Text(`${order.total_quantity} 件 · ${formatMoney(order.total_cents)} · 配送至 ${order.delivery_address}`)
              .width('100%').fontSize(10).fontColor($r('app.color.text_secondary'))
            Text(`provider=${order.provider}/demo=${order.is_demo} · 未接真实支付/物流`).width('100%')
              .fontSize(9).fontColor($r('app.color.warning'))
            if (order.status === ShopOrderStatus.EXPIRED) {
              Text(`订单保留已过期${order.expires_at === null ? '' :
                ` · ${formatShanghaiDateTime(order.expires_at)}`}`)
                .width('100%').fontSize(10).fontColor($r('app.color.error'))
            }
            if (canPayShopOrder(order.status)) {
              Button(this.operationBusy ? '支付处理中…' : '演示支付').enabled(!this.operationBusy).width('100%')
                .fontColor(Color.White).backgroundColor($r('app.color.primary')).onClick(() => { this.payOrder(order); })
            }
          }.width('100%').padding(14).borderRadius(16).backgroundColor($r('app.color.surface'))
        }, (order: ShopOrder) => order.id)
      }
    }
  }

  @Builder
  private pointsContent() {
    this.privateStatePanel()
    if (this.loggedIn && this.privateState === ContentState.CONTENT) {
      Column({ space: 5 }) {
        Text(`${this.pointsAccount?.balance ?? 0} 分`).fontSize(28).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.primary'))
        Text('绿色出行、商城订单和演示内容分享可获得积分').fontSize(10)
          .fontColor($r('app.color.text_secondary'))
      }.width('100%').padding(16).borderRadius(17).backgroundColor($r('app.color.surface'))
      Text('积分奖励').width('100%').fontSize(17).fontWeight(FontWeight.Bold).fontColor($r('app.color.text_primary'))
      Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.SpaceBetween }) {
        ForEach(this.rewards, (reward: PointsReward) => {
          Column({ space: 5 }) {
            Text(reward.name).width('100%').fontWeight(FontWeight.Bold).fontColor(this.selectedRewardId === reward.id ?
              Color.White : $r('app.color.text_primary'))
            Text(`${reward.points_cost} 分 · 库存 ${reward.stock}`).width('100%').fontSize(11)
              .fontColor(this.selectedRewardId === reward.id ? Color.White : $r('app.color.warning'))
            Text(`provider=${reward.provider}/demo=${reward.is_demo}`).width('100%').fontSize(8)
              .fontColor(this.selectedRewardId === reward.id ? '#E8F2FF' : $r('app.color.text_secondary'))
          }.width(this.isWide ? '31%' : '48%').padding(12).borderRadius(14)
            .backgroundColor(this.selectedRewardId === reward.id ? $r('app.color.primary') : $r('app.color.surface'))
            .onClick(() => { this.selectedRewardId = reward.id; })
        }, (reward: PointsReward) => reward.id)
      }.width('100%')
      Button(this.operationBusy ? '兑换中…' : '兑换所选奖励').enabled(!this.operationBusy && this.rewards.length > 0)
        .width('100%').fontColor(Color.White).backgroundColor($r('app.color.primary')).onClick(() => { this.redeem(); })
      Column({ space: 7 }) {
        Text('内容分享积分（DemoShareVerifier）').width('100%').fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.text_primary'))
        Text(`已选商品 ${this.shareRefId.length > 0 ? this.shareRefId : '无'}`).width('100%').fontSize(9)
          .fontColor($r('app.color.text_secondary'))
        TextInput({ text: this.shareCaption, placeholder: '分享文案' }).width('100%')
          .onChange((value: string) => { this.shareCaption = value; })
        Row({ space: 7 }) {
          Button('演示朋友圈').layoutWeight(1).fontColor(this.sharePlatform === 'demo_moments' ? Color.White :
            $r('app.color.primary')).backgroundColor(this.sharePlatform === 'demo_moments' ? $r('app.color.primary') :
            $r('app.color.surface_tint')).onClick(() => { this.sharePlatform = 'demo_moments'; })
          Button('演示群聊').layoutWeight(1).fontColor(this.sharePlatform === 'demo_group' ? Color.White :
            $r('app.color.primary')).backgroundColor(this.sharePlatform === 'demo_group' ? $r('app.color.primary') :
            $r('app.color.surface_tint')).onClick(() => { this.sharePlatform = 'demo_group'; })
        }.width('100%')
        Button(this.operationBusy ? '记录中…' : '记录演示分享并领取积分').enabled(!this.operationBusy)
          .width('100%').fontColor(Color.White).backgroundColor($r('app.color.primary'))
          .onClick(() => { this.shareContent(); })
        Text('仅记录经 DemoShareVerifier 验证的演示分享，不代表已接入真实社交平台。').width('100%')
          .fontSize(9).fontColor($r('app.color.warning'))
      }.width('100%').padding(14).borderRadius(16).backgroundColor($r('app.color.surface'))
      Text('积分流水').width('100%').fontSize(17).fontWeight(FontWeight.Bold).fontColor($r('app.color.text_primary'))
      ForEach(this.ledger, (entry: PointsLedgerEntry) => {
        Row() {
          Column({ space: 2 }) {
            Text(entry.reason).fontColor($r('app.color.text_primary'))
            Text(`${entry.kind} · ${entry.reference_type}`).fontSize(9).fontColor($r('app.color.text_secondary'))
          }.alignItems(HorizontalAlign.Start).layoutWeight(1)
          Text(`${entry.amount >= 0 ? '+' : ''}${entry.amount}`).fontWeight(FontWeight.Bold)
            .fontColor(entry.amount >= 0 ? $r('app.color.success') : $r('app.color.error'))
          Text(` 余额 ${entry.balance_after}`).fontSize(9).fontColor($r('app.color.text_secondary'))
        }.width('100%').padding(11).borderRadius(12).backgroundColor($r('app.color.surface'))
      }, (entry: PointsLedgerEntry) => entry.id)
    }
  }

  build() {
    Scroll() {
      Column({ space: 13 }) {
        Row() {
          Column({ space: 3 }) {
            Text('景区好物与绿色积分').fontSize(22).fontWeight(FontWeight.Bold)
              .fontColor($r('app.color.text_primary'))
            Text('目录、活动、购物车、订单与积分均来自真实 API').fontSize(11)
              .fontColor($r('app.color.text_secondary'))
          }.alignItems(HorizontalAlign.Start).layoutWeight(1)
          Text(`购物车 ${this.cart?.total_quantity ?? 0}`).fontSize(11).fontColor($r('app.color.primary'))
        }.width('100%')
        Row({ space: 6 }) {
          this.sectionButton('商品', MallSection.CATALOG)
          this.sectionButton('购物车', MallSection.CART)
          this.sectionButton('订单', MallSection.ORDERS)
          this.sectionButton('积分', MallSection.POINTS)
        }.width('100%')
        if (this.section === MallSection.CATALOG) {
          this.catalogContent()
        } else if (this.section === MallSection.CART) {
          this.cartContent()
        } else if (this.section === MallSection.ORDERS) {
          this.ordersContent()
        } else {
          this.pointsContent()
        }
        if (this.operationMessage.length > 0) {
          Text(this.operationMessage).width('100%').padding(10).borderRadius(11).fontSize(10)
            .fontColor($r('app.color.warning')).backgroundColor($r('app.color.surface_tint'))
        }
      }.width('100%').constraintSize({ maxWidth: 960 })
        .padding({ left: 16, right: 16, top: 16, bottom: 30 })
    }.width('100%').height('100%').scrollBar(BarState.Off).backgroundColor($r('app.color.page_background'))
      .onAreaChange((_oldArea: Area, newArea: Area) => { this.isWide = isWideWindow(Number(newArea.width)); })
  }
}
