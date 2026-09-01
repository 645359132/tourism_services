import { ExperienceBookingView } from '../components/booking/ExperienceBookingView';
import { HospitalityBookingView } from '../components/booking/HospitalityBookingView';

enum BookingSection {
  EXPERIENCES = 0,
  HOSPITALITY = 1
}

@Component
export struct BookingPage {
  @Prop loggedIn: boolean = false;
  @Prop initialSection: number = 0;
  @State section: BookingSection = BookingSection.EXPERIENCES;
  onBack: () => void = (): void => {};
  onLoginTap: () => void = (): void => {};
  onTripTap: () => void = (): void => {};

  aboutToAppear(): void {
    this.section = this.initialSection === 1 ? BookingSection.HOSPITALITY : BookingSection.EXPERIENCES;
  }

  build() {
    Column() {
      Row({ space: 8 }) {
        Button('‹ 返回').fontSize(12).fontColor($r('app.color.text_secondary'))
          .backgroundColor(Color.Transparent).onClick(() => { this.onBack(); })
        Button('项目/演出与排队').layoutWeight(1)
          .fontColor(this.section === BookingSection.EXPERIENCES ? Color.White : $r('app.color.primary'))
          .backgroundColor(this.section === BookingSection.EXPERIENCES ? $r('app.color.primary') :
            $r('app.color.surface_tint')).onClick(() => { this.section = BookingSection.EXPERIENCES; })
        Button('餐住与组合').layoutWeight(1)
          .fontColor(this.section === BookingSection.HOSPITALITY ? Color.White : $r('app.color.primary'))
          .backgroundColor(this.section === BookingSection.HOSPITALITY ? $r('app.color.primary') :
            $r('app.color.surface_tint')).onClick(() => { this.section = BookingSection.HOSPITALITY; })
      }.width('100%').padding({ left: 10, right: 10, top: 8, bottom: 8 })
        .backgroundColor($r('app.color.surface'))
      if (this.section === BookingSection.EXPERIENCES) {
        ExperienceBookingView({ loggedIn: this.loggedIn, onLoginTap: this.onLoginTap, onTripTap: this.onTripTap })
      } else {
        HospitalityBookingView({ loggedIn: this.loggedIn, onLoginTap: this.onLoginTap })
      }
    }.width('100%').height('100%').backgroundColor($r('app.color.page_background'))
  }
}
