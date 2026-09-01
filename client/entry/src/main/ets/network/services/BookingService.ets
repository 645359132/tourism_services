import {
  AvailabilityResponse,
  ExperienceListResponse,
  ExperienceSessionListResponse,
  FastPass,
  HospitalityOfferListResponse,
  QueueEntry,
  Reservation,
  ReservationListResponse,
  ReviewResponse,
  VenueListResponse,
  WsTicketResponse
} from '../../models/BookingModels';
import { ApiMethod, ApiRequest, HttpClient, NetworkResult } from '../HttpClient';

class ReservationPayload {
  session_id: string;
  party_size: number;
  idempotency_key: string;
  constructor(sessionId: string, partySize: number, key: string) {
    this.session_id = sessionId;
    this.party_size = partySize;
    this.idempotency_key = key;
  }
}

class IdempotencyPayload {
  idempotency_key: string;
  constructor(key: string) { this.idempotency_key = key; }
}

class CancelPayload {
  reason: string;
  idempotency_key: string;
  constructor(reason: string, key: string) { this.reason = reason; this.idempotency_key = key; }
}

class QueueJoinPayload {
  experience_id: string;
  party_size: number;
  itinerary_id: string | null;
  idempotency_key: string;
  constructor(experienceId: string, partySize: number, itineraryId: string | null, key: string) {
    this.experience_id = experienceId;
    this.party_size = partySize;
    this.itinerary_id = itineraryId;
    this.idempotency_key = key;
  }
}

class StayPayload {
  offer_id: string; check_in: string; check_out: string; quantity: number; party_size: number; idempotency_key: string;
  constructor(offerId: string, checkIn: string, checkOut: string, quantity: number, partySize: number, key: string) {
    this.offer_id = offerId; this.check_in = checkIn; this.check_out = checkOut; this.quantity = quantity;
    this.party_size = partySize; this.idempotency_key = key;
  }
}

class DiningPayload {
  offer_id: string; starts_at: string; party_size: number; idempotency_key: string;
  constructor(offerId: string, startsAt: string, partySize: number, key: string) {
    this.offer_id = offerId; this.starts_at = startsAt; this.party_size = partySize; this.idempotency_key = key;
  }
}

class BundlePayload {
  offer_id: string; visit_date: string; party_size: number; idempotency_key: string;
  constructor(offerId: string, visitDate: string, partySize: number, key: string) {
    this.offer_id = offerId; this.visit_date = visitDate; this.party_size = partySize; this.idempotency_key = key;
  }
}

class ReviewPayload {
  reservation_id: string; rating: number; content: string;
  constructor(reservationId: string, rating: number, content: string) {
    this.reservation_id = reservationId; this.rating = rating; this.content = content;
  }
}

class WsTicketPayload {
  channel_type: string = 'queue';
  channel_id: string;
  constructor(queueId: string) { this.channel_id = queueId; }
}

export class BookingService {
  private client: HttpClient = new HttpClient();

  listExperiences(): Promise<NetworkResult<ExperienceListResponse>> {
    return this.client.request<ExperienceListResponse>(new ApiRequest('/experiences', ApiMethod.GET, '', false));
  }

  listSessions(experienceId: string, visitDate: string): Promise<NetworkResult<ExperienceSessionListResponse>> {
    const path: string = `/experiences/${encodeURIComponent(experienceId)}/sessions` +
      `?date=${encodeURIComponent(visitDate)}`;
    return this.client.request<ExperienceSessionListResponse>(new ApiRequest(path, ApiMethod.GET, '', false));
  }

  createReservation(sessionId: string, partySize: number, key: string): Promise<NetworkResult<Reservation>> {
    return this.client.request<Reservation>(new ApiRequest('/reservations', ApiMethod.POST,
      JSON.stringify(new ReservationPayload(sessionId, partySize, key)), true, 0));
  }

  listReservations(): Promise<NetworkResult<ReservationListResponse>> {
    return this.client.request<ReservationListResponse>(new ApiRequest('/reservations', ApiMethod.GET));
  }

  confirmReservation(id: string, key: string): Promise<NetworkResult<Reservation>> {
    return this.client.request<Reservation>(new ApiRequest(`/reservations/${encodeURIComponent(id)}/confirm`,
      ApiMethod.POST, JSON.stringify(new IdempotencyPayload(key)), true, 0));
  }

  cancelReservation(id: string, reason: string, key: string): Promise<NetworkResult<Reservation>> {
    return this.client.request<Reservation>(new ApiRequest(`/reservations/${encodeURIComponent(id)}/cancel`,
      ApiMethod.POST, JSON.stringify(new CancelPayload(reason, key)), true, 0));
  }

  joinQueue(experienceId: string, partySize: number, itineraryId: string | null,
    key: string): Promise<NetworkResult<QueueEntry>> {
    return this.client.request<QueueEntry>(new ApiRequest('/queues', ApiMethod.POST,
      JSON.stringify(new QueueJoinPayload(experienceId, partySize, itineraryId, key)), true, 0));
  }

  getQueue(queueId: string): Promise<NetworkResult<QueueEntry>> {
    return this.client.request<QueueEntry>(new ApiRequest(`/queues/${encodeURIComponent(queueId)}`, ApiMethod.GET));
  }

  leaveQueue(queueId: string, key: string): Promise<NetworkResult<QueueEntry>> {
    return this.client.request<QueueEntry>(new ApiRequest(`/queues/${encodeURIComponent(queueId)}`,
      ApiMethod.DELETE, JSON.stringify(new IdempotencyPayload(key)), true, 0));
  }

  buyFastPass(queueId: string, key: string): Promise<NetworkResult<FastPass>> {
    return this.client.request<FastPass>(new ApiRequest(`/queues/${encodeURIComponent(queueId)}/fast-pass`,
      ApiMethod.POST, JSON.stringify(new IdempotencyPayload(key)), true, 0));
  }

  createWsTicket(queueId: string): Promise<NetworkResult<WsTicketResponse>> {
    return this.client.request<WsTicketResponse>(new ApiRequest('/ws-tickets', ApiMethod.POST,
      JSON.stringify(new WsTicketPayload(queueId)), true, 0));
  }

  listVenues(): Promise<NetworkResult<VenueListResponse>> {
    return this.client.request<VenueListResponse>(new ApiRequest('/hospitality/venues', ApiMethod.GET, '', false));
  }

  listOffers(): Promise<NetworkResult<HospitalityOfferListResponse>> {
    return this.client.request<HospitalityOfferListResponse>(new ApiRequest('/hospitality/offers', ApiMethod.GET, '', false));
  }

  getAvailability(resourceId: string, dateFrom: string, dateTo: string): Promise<NetworkResult<AvailabilityResponse>> {
    const path: string = `/hospitality/availability?resource_id=${encodeURIComponent(resourceId)}` +
      `&date_from=${encodeURIComponent(dateFrom)}&date_to=${encodeURIComponent(dateTo)}`;
    return this.client.request<AvailabilityResponse>(new ApiRequest(path, ApiMethod.GET, '', false));
  }

  bookStay(offerId: string, checkIn: string, checkOut: string, quantity: number,
    partySize: number, key: string): Promise<NetworkResult<Reservation>> {
    return this.client.request<Reservation>(new ApiRequest('/hospitality/bookings/stay', ApiMethod.POST,
      JSON.stringify(new StayPayload(offerId, checkIn, checkOut, quantity, partySize, key)), true, 0));
  }

  bookDining(offerId: string, startsAt: string, partySize: number,
    key: string): Promise<NetworkResult<Reservation>> {
    return this.client.request<Reservation>(new ApiRequest('/hospitality/bookings/dining', ApiMethod.POST,
      JSON.stringify(new DiningPayload(offerId, startsAt, partySize, key)), true, 0));
  }

  bookBundle(offerId: string, visitDate: string, partySize: number,
    key: string): Promise<NetworkResult<Reservation>> {
    return this.client.request<Reservation>(new ApiRequest('/hospitality/bookings/bundle', ApiMethod.POST,
      JSON.stringify(new BundlePayload(offerId, visitDate, partySize, key)), true, 0));
  }

  createReview(reservationId: string, rating: number, content: string): Promise<NetworkResult<ReviewResponse>> {
    return this.client.request<ReviewResponse>(new ApiRequest('/reviews', ApiMethod.POST,
      JSON.stringify(new ReviewPayload(reservationId, rating, content)), true, 0));
  }
}
