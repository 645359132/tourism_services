import { ContentState, MainDestination } from '../models/AppModels';

export class AppStore {
  private static instance: AppStore = new AppStore();
  private destination: MainDestination = MainDestination.HOME;
  private contentState: ContentState = ContentState.CONTENT;

  static getInstance(): AppStore {
    return AppStore.instance;
  }

  setDestination(destination: MainDestination): void {
    this.destination = destination;
  }

  getDestination(): MainDestination {
    return this.destination;
  }

  setContentState(contentState: ContentState): void {
    this.contentState = contentState;
  }

  getContentState(): ContentState {
    return this.contentState;
  }
}
