import { AppHeader } from '../components/AppHeader';
import { BottomNavigation, SideNavigation } from '../components/AppNavigation';
import { LoginPanel } from '../components/LoginPanel';
import { ContentState, MainDestination } from '../models/AppModels';
import { AuthStore } from '../stores/AuthStore';
import { GuidePage } from './GuidePage';
import { HomePage } from './HomePage';
import { MallPage } from './MallPage';
import { ProfilePage } from './ProfilePage';
import { TripPage } from './TripPage';
import { TicketPage } from './TicketPage';
import { BookingPage } from './BookingPage';
import { AccessibilitySettings, AccessibilityStore } from '../stores/AccessibilityStore';
import { globalContentExtent, globalContentScale } from '../utils/AccessibilityRules';
import { isWideWindow } from '../utils/ResponsiveRules';

@Entry
@Component
struct Index {
  @State selected: MainDestination = MainDestination.HOME;
  @State contentState: ContentState = ContentState.CONTENT;
  @State showLogin: boolean = false;
  @State loggedIn: boolean = false;
  @State displayName: string = '游客';
  @State isTablet: boolean = false;
  @State showTicketing: boolean = false;
  @State showBooking: boolean = false;
  @State bookingInitialSection: number = 0;
  @State largeText: boolean = false;
  @State highContrast: boolean = false;

  aboutToAppear(): void {
    const authStore: AuthStore = AuthStore.getInstance();
    this.loggedIn = authStore.isLoggedIn();
    this.displayName = authStore.getDisplayName();
    const accessibility: AccessibilitySettings = AccessibilityStore.getInstance().getSettings();
    this.largeText = accessibility.largeText;
    this.highContrast = accessibility.highContrast;
  }

  private currentTitle(): string {
    if (this.showTicketing) {
      return '门票预约';
    }
    if (this.showBooking) {
      return '项目排队与餐住';
    }
    if (this.selected === MainDestination.GUIDE) {
      return '智慧导览';
    }
    if (this.selected === MainDestination.TRIP) {
      return '行程管家';
    }
    if (this.selected === MainDestination.MALL) {
      return '文旅商城';
    }
    if (this.selected === MainDestination.PROFILE) {
      return '个人服务';
    }
    return '云游智景';
  }

  @Builder
  private pageContent() {
    if (this.showTicketing) {
      TicketPage({
        loggedIn: this.loggedIn,
        onBack: (): void => {
          this.showTicketing = false;
        },
        onLoginTap: (): void => {
          this.showLogin = true;
        }
      })
    } else if (this.showBooking) {
      BookingPage({
        loggedIn: this.loggedIn,
        initialSection: this.bookingInitialSection,
        onBack: (): void => {
          this.showBooking = false;
        },
        onLoginTap: (): void => {
          this.showLogin = true;
        },
        onTripTap: (): void => {
          this.showBooking = false;
          this.selected = MainDestination.TRIP;
        }
      })
    } else if (this.selected === MainDestination.GUIDE) {
      GuidePage()
    } else if (this.selected === MainDestination.TRIP) {
      TripPage({
        loggedIn: this.loggedIn,
        onLoginTap: (): void => {
          this.showLogin = true;
        }
      })
    } else if (this.selected === MainDestination.MALL) {
      MallPage({
        loggedIn: this.loggedIn,
        onLoginTap: (): void => { this.showLogin = true; }
      })
    } else if (this.selected === MainDestination.PROFILE) {
      ProfilePage({
        loggedIn: $loggedIn,
        displayName: $displayName,
        onLoginTap: (): void => {
          this.showLogin = true;
        },
        onAccessibilityChanged: (largeText: boolean, highContrast: boolean): void => {
          this.largeText = largeText;
          this.highContrast = highContrast;
        }
      })
    } else {
      HomePage({
        contentState: $contentState,
        onTicketTap: (): void => {
          this.showTicketing = true;
        },
        onQueueTap: (): void => {
          this.bookingInitialSection = 0;
          this.showBooking = true;
        },
        onHospitalityTap: (): void => {
          this.bookingInitialSection = 1;
          this.showBooking = true;
        }
      })
    }
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Row() {
        if (this.isTablet && !this.showTicketing && !this.showBooking) {
          SideNavigation({ selected: $selected, largeText: this.largeText })
        }
        Column() {
          AppHeader({
            title: this.currentTitle(),
            loggedIn: this.loggedIn,
            displayName: this.displayName,
            largeText: this.largeText,
            onLoginTap: (): void => {
              this.showLogin = true;
            }
          })
          Column() {
            this.pageContent()
          }
          .layoutWeight(1)
          .width('100%')
          if (!this.isTablet && !this.showTicketing && !this.showBooking) {
            BottomNavigation({ selected: $selected, largeText: this.largeText })
          }
        }
        .layoutWeight(1)
        .height('100%')
      }
      .width(globalContentExtent(this.largeText))
      .height(globalContentExtent(this.largeText))
      .scale({ x: globalContentScale(this.largeText), y: globalContentScale(this.largeText) })

      if (this.showLogin) {
        Column() {
          LoginPanel({
            visible: $showLogin,
            loggedIn: $loggedIn,
            displayName: $displayName
          })
        }
        .width('100%')
        .height('100%')
        .justifyContent(FlexAlign.Center)
        .backgroundColor('#66000000')
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor($r('app.color.page_background'))
    .contrast(this.highContrast ? 1.25 : 1)
    .onAreaChange((_oldArea: Area, newArea: Area) => {
      this.isTablet = isWideWindow(Number(newArea.width));
    })
  }
}
