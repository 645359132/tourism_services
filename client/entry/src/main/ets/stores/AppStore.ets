import { ContentState, MainDestination } from '../models/AppModels';

export class AppStore {
  private static instance: AppStore = new AppStore();
  private destination: MainDestination = MainDestination.HOME;
  private contentState: ContentState = ContentState.CONTENT;
  private currentItineraryId: string = '';
  private currentItineraryRevision: number = 0;
  private currentGroupId: string = '';

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

  setCurrentItinerary(itineraryId: string, revision: number): void {
    this.currentItineraryId = itineraryId;
    this.currentItineraryRevision = revision;
  }

  clearCurrentItinerary(): void {
    this.currentItineraryId = '';
    this.currentItineraryRevision = 0;
  }

  hasCurrentItinerary(): boolean {
    return this.currentItineraryId.length > 0 && this.currentItineraryRevision > 0;
  }

  getCurrentItineraryId(): string {
    return this.currentItineraryId;
  }

  getCurrentItineraryRevision(): number {
    return this.currentItineraryRevision;
  }

  setCurrentGroupId(groupId: string): void {
    this.currentGroupId = groupId;
  }

  hasCurrentGroup(): boolean {
    return this.currentGroupId.length > 0;
  }

  getCurrentGroupId(): string {
    return this.currentGroupId;
  }
}
