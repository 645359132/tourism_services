import {
  FacilityListResponse,
  FaqListResponse,
  FeedbackKind,
  FeedbackListResponse,
  FeedbackRecord,
  LostAlertResponse,
  ServiceWsTicketResponse,
  SupportConversation,
  SupportConversationListResponse,
  SupportMessage,
  SupportMessageListResponse,
  TravelGroup
} from '../../models/ServiceModels';
import { ApiMethod, ApiRequest, HttpClient, NetworkResult } from '../HttpClient';

class FeedbackPayload {
  kind: FeedbackKind; title: string; content: string;
  constructor(kind: FeedbackKind, title: string, content: string) {
    this.kind = kind; this.title = title; this.content = content;
  }
}

class FollowUpPayload {
  rating: number; comment: string;
  constructor(rating: number, comment: string) { this.rating = rating; this.comment = comment; }
}

class ConversationPayload {
  subject: string;
  constructor(subject: string) { this.subject = subject; }
}

class MessagePayload {
  content: string; idempotency_key: string;
  constructor(content: string, key: string) { this.content = content; this.idempotency_key = key; }
}

class ServiceWsTicketPayload {
  conversation_id: string;
  constructor(conversationId: string) { this.conversation_id = conversationId; }
}

class CreateGroupPayload {
  name: string; itinerary_id: string | null;
  constructor(name: string, itineraryId: string | null) { this.name = name; this.itinerary_id = itineraryId; }
}

class JoinGroupPayload {
  invite_code: string;
  constructor(inviteCode: string) { this.invite_code = inviteCode; }
}

class GroupItineraryPayload {
  itinerary_id: string; expected_revision: number;
  constructor(itineraryId: string, revision: number) {
    this.itinerary_id = itineraryId; this.expected_revision = revision;
  }
}

class GroupPrivacyPayload {
  share_itinerary: boolean; share_location: boolean; share_member_status: boolean;
  constructor(itinerary: boolean, location: boolean, status: boolean) {
    this.share_itinerary = itinerary; this.share_location = location; this.share_member_status = status;
  }
}

class MeetingPointPayload {
  name: string; node_id: string | null; note: string;
  constructor(name: string, nodeId: string | null, note: string) {
    this.name = name; this.node_id = nodeId; this.note = note;
  }
}

class MemberStatusPayload {
  status: string; note: string; share_location: boolean; share_status: boolean;
  latitude: number | null; longitude: number | null;
  constructor(status: string, note: string, shareLocation: boolean, shareStatus: boolean,
    latitude: number | null, longitude: number | null) {
    this.status = status; this.note = note; this.share_location = shareLocation; this.share_status = shareStatus;
    this.latitude = latitude; this.longitude = longitude;
  }
}

class LostAlertPayload {
  message: string; last_seen_node_id: string | null;
  constructor(message: string, nodeId: string | null) { this.message = message; this.last_seen_node_id = nodeId; }
}

export class ServiceService {
  private client: HttpClient = new HttpClient();

  createFeedback(kind: FeedbackKind, title: string, content: string): Promise<NetworkResult<FeedbackRecord>> {
    return this.client.request<FeedbackRecord>(new ApiRequest('/feedback', ApiMethod.POST,
      JSON.stringify(new FeedbackPayload(kind, title, content)), true, 0));
  }

  listFeedback(): Promise<NetworkResult<FeedbackListResponse>> {
    return this.client.request<FeedbackListResponse>(new ApiRequest('/feedback', ApiMethod.GET));
  }

  getFeedback(id: string): Promise<NetworkResult<FeedbackRecord>> {
    return this.client.request<FeedbackRecord>(new ApiRequest(`/feedback/${encodeURIComponent(id)}`, ApiMethod.GET));
  }

  followUpFeedback(id: string, rating: number, comment: string): Promise<NetworkResult<FeedbackRecord>> {
    return this.client.request<FeedbackRecord>(new ApiRequest(`/feedback/${encodeURIComponent(id)}/follow-up`,
      ApiMethod.POST, JSON.stringify(new FollowUpPayload(rating, comment)), true, 0));
  }

  listFaqs(): Promise<NetworkResult<FaqListResponse>> {
    return this.client.request<FaqListResponse>(new ApiRequest('/faqs', ApiMethod.GET, '', false));
  }

  createConversation(subject: string): Promise<NetworkResult<SupportConversation>> {
    return this.client.request<SupportConversation>(new ApiRequest('/support/conversations', ApiMethod.POST,
      JSON.stringify(new ConversationPayload(subject)), true, 0));
  }

  listConversations(): Promise<NetworkResult<SupportConversationListResponse>> {
    return this.client.request<SupportConversationListResponse>(new ApiRequest('/support/conversations', ApiMethod.GET));
  }

  listMessages(conversationId: string): Promise<NetworkResult<SupportMessageListResponse>> {
    return this.client.request<SupportMessageListResponse>(new ApiRequest(
      `/support/conversations/${encodeURIComponent(conversationId)}/messages`, ApiMethod.GET));
  }

  sendMessage(conversationId: string, content: string, key: string): Promise<NetworkResult<SupportMessageListResponse>> {
    return this.client.request<SupportMessageListResponse>(new ApiRequest(
      `/support/conversations/${encodeURIComponent(conversationId)}/messages`, ApiMethod.POST,
      JSON.stringify(new MessagePayload(content, key)), true, 0));
  }

  createSupportWsTicket(conversationId: string): Promise<NetworkResult<ServiceWsTicketResponse>> {
    return this.client.request<ServiceWsTicketResponse>(new ApiRequest('/support/ws-tickets', ApiMethod.POST,
      JSON.stringify(new ServiceWsTicketPayload(conversationId)), true, 0));
  }

  createGroup(name: string, itineraryId: string | null): Promise<NetworkResult<TravelGroup>> {
    return this.client.request<TravelGroup>(new ApiRequest('/groups/create', ApiMethod.POST,
      JSON.stringify(new CreateGroupPayload(name, itineraryId)), true, 0));
  }

  joinGroup(inviteCode: string): Promise<NetworkResult<TravelGroup>> {
    return this.client.request<TravelGroup>(new ApiRequest('/groups/join', ApiMethod.POST,
      JSON.stringify(new JoinGroupPayload(inviteCode)), true, 0));
  }

  getGroup(groupId: string): Promise<NetworkResult<TravelGroup>> {
    return this.client.request<TravelGroup>(new ApiRequest(`/groups/${encodeURIComponent(groupId)}`, ApiMethod.GET));
  }

  linkGroupItinerary(groupId: string, itineraryId: string,
    revision: number): Promise<NetworkResult<TravelGroup>> {
    return this.client.request<TravelGroup>(new ApiRequest(`/groups/${encodeURIComponent(groupId)}/itinerary`,
      ApiMethod.PUT, JSON.stringify(new GroupItineraryPayload(itineraryId, revision)), true, 0));
  }

  updateGroupPrivacy(groupId: string, itinerary: boolean, location: boolean,
    memberStatus: boolean): Promise<NetworkResult<TravelGroup>> {
    return this.client.request<TravelGroup>(new ApiRequest(`/groups/${encodeURIComponent(groupId)}/privacy`,
      ApiMethod.PUT, JSON.stringify(new GroupPrivacyPayload(itinerary, location, memberStatus)), true, 0));
  }

  setMeetingPoint(groupId: string, name: string, nodeId: string,
    note: string): Promise<NetworkResult<TravelGroup>> {
    const normalizedNodeId: string | null = nodeId.trim().length === 0 ? null : nodeId.trim();
    return this.client.request<TravelGroup>(new ApiRequest(`/groups/${encodeURIComponent(groupId)}/meeting-points`,
      ApiMethod.POST, JSON.stringify(new MeetingPointPayload(name, normalizedNodeId, note)), true, 0));
  }

  updateMemberStatus(groupId: string, status: string, note: string, shareLocation: boolean,
    shareStatus: boolean, latitude: number | null, longitude: number | null): Promise<NetworkResult<TravelGroup>> {
    return this.client.request<TravelGroup>(new ApiRequest(`/groups/${encodeURIComponent(groupId)}/member-status`,
      ApiMethod.POST, JSON.stringify(new MemberStatusPayload(
        status, note, shareLocation, shareStatus, latitude, longitude)), true, 0));
  }

  createLostAlert(groupId: string, message: string, nodeId: string): Promise<NetworkResult<LostAlertResponse>> {
    const normalizedNodeId: string | null = nodeId.trim().length === 0 ? null : nodeId.trim();
    return this.client.request<LostAlertResponse>(new ApiRequest(`/groups/${encodeURIComponent(groupId)}/lost-alerts`,
      ApiMethod.POST, JSON.stringify(new LostAlertPayload(message, normalizedNodeId)), true, 0));
  }

  listFacilities(): Promise<NetworkResult<FacilityListResponse>> {
    return this.client.request<FacilityListResponse>(new ApiRequest('/guide/facilities', ApiMethod.GET, '', false));
  }
}
