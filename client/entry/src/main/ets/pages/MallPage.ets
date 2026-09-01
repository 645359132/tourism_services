import { TourismProduct } from '../models/AppModels';

const PRODUCTS: TourismProduct[] = [
  new TourismProduct('passport', '文化数字护照纪念册', '¥39', '绿色积分可抵扣'),
  new TourismProduct('tea', '云山限定茶礼', '¥88', '限时 8 折'),
  new TourismProduct('family', '亲子探索任务包', '¥29', '完成任务返积分'),
  new TourismProduct('postcard', '镜湖风光明信片', '200 积分', '积分兑换')
];

@Component
export struct MallPage {
  @State cartCount: number = 0;

  @Builder
  private productCard(product: TourismProduct) {
    Column({ space: 10 }) {
      Column() {
        Text(product.id === 'tea' ? '茶' : product.id === 'passport' ? '印' : product.id === 'family' ? '趣' : '景')
          .fontSize(28)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.primary'))
      }
      .width('100%')
      .height(92)
      .justifyContent(FlexAlign.Center)
      .borderRadius(16)
      .backgroundColor($r('app.color.surface_tint'))
      Text(product.name)
        .width('100%')
        .fontSize(14)
        .fontWeight(FontWeight.Medium)
        .fontColor($r('app.color.text_primary'))
        .maxLines(2)
      Text(product.tag)
        .width('100%')
        .fontSize(10)
        .fontColor($r('app.color.warning'))
        .maxLines(1)
      Row() {
        Text(product.priceText)
          .fontSize(16)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.error'))
          .layoutWeight(1)
        Button('+')
          .width(34)
          .height(34)
          .fontSize(20)
          .fontColor(Color.White)
          .backgroundColor($r('app.color.primary'))
          .onClick(() => {
            this.cartCount += 1;
          })
      }
      .width('100%')
    }
    .width('48%')
    .padding(12)
    .borderRadius(20)
    .backgroundColor($r('app.color.surface'))
  }

  build() {
    Scroll() {
      Column({ space: 16 }) {
        Row() {
          Column({ space: 4 }) {
            Text('景区好物')
              .fontSize(22)
              .fontWeight(FontWeight.Bold)
              .fontColor($r('app.color.text_primary'))
            Text('文创 · 特产 · 团购 · 积分兑换')
              .fontSize(12)
              .fontColor($r('app.color.text_secondary'))
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
          Button(`购物车 ${this.cartCount}`)
            .fontSize(12)
            .fontColor($r('app.color.primary'))
            .backgroundColor($r('app.color.surface_tint'))
        }
        .width('100%')

        Row({ space: 10 }) {
          Text('限时折扣').fontColor(Color.White).fontSize(13)
          Text('团购专区').fontColor(Color.White).fontSize(13)
          Text('绿色积分').fontColor(Color.White).fontSize(13)
          Text('内容分享').fontColor(Color.White).fontSize(13)
        }
        .width('100%')
        .padding(16)
        .borderRadius(18)
        .justifyContent(FlexAlign.SpaceBetween)
        .backgroundColor($r('app.color.primary'))

        Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.SpaceBetween, alignContent: FlexAlign.SpaceBetween }) {
          ForEach(PRODUCTS, (product: TourismProduct) => {
            this.productCard(product)
          }, (product: TourismProduct) => product.id)
        }
        .width('100%')
        .height(520)
      }
      .width('100%')
      .padding({ left: 18, right: 18, top: 18, bottom: 28 })
    }
    .width('100%')
    .height('100%')
    .scrollBar(BarState.Off)
    .backgroundColor($r('app.color.page_background'))
  }
}
