# Data model

The deployed schema contains 76 persisted tables in the linear Alembic chain `20260901_0001` through `20260901_0007`; the SQLAlchemy declarations mirror it at runtime. Migration files are authoritative for an existing database, while models are the most convenient navigation index. All named constraints use the shared convention in [db/base.py](../server/app/db/base.py#L6).

Unless noted otherwise, entity identifiers are UUIDs, timestamps are timezone-aware, money is integer cents, percentages are basis points, and deleting a user cascades into user-owned records. Catalog/reference rows are seeded or managed server-side; API ownership checks are still required because a foreign key alone does not authorize access.

## Foundation, identity, and preferences

Source: [identity models](../server/app/db/models/user.py#L20), [roles](../server/app/db/models/role.py#L20), [preferences](../server/app/db/models/preference.py#L18), and [refresh sessions](../server/app/db/models/refresh_session.py#L18).

| Tables/entities | Ownership and relationships | Material uniqueness and checks |
|---|---|---|
| `seed_records` (`SeedRecord`) | Infrastructure ledger for idempotent seed operations; not user-owned. | String `key` is the primary key, so a seed unit is recorded once. |
| `users` (`User`) | Identity root. Owns preferences, role links, refresh sessions, and domain records. Public registration creates this row together with a `tourist` role link and refresh session before returning its token pair. | Unique normalized lowercase `username` closes concurrent registration races; active flag gates authentication. Passwords contain Argon2id hashes, never plaintext. |
| `roles`, `user_roles` (`Role`, `UserRole`) | Global role catalog plus many-to-many user assignment. Both foreign keys cascade. | Unique role `name`; composite primary key `(user_id, role_id)` prevents duplicate assignment. |
| `tourist_preferences` (`TouristPreference`) | Exactly zero or one row per user; language, interests, accessibility needs, and notification preference. | `user_id` is both primary key and cascading foreign key. |
| `refresh_sessions` (`RefreshSession`) | User-owned, self-referencing rotation chain grouped by `family_id`; parent deletion becomes `NULL`. | Unique `token_jti`; indexed family and user IDs. Consumed/revoked timestamps and replacement JTI support replay detection and family revocation. |

## Ticketing and admission

Source: [ticketing models](../server/app/db/models/ticketing.py#L37).

| Tables/entities | Ownership and relationships | Material uniqueness and checks |
|---|---|---|
| `ticket_types` (`TicketType`) | Global ticket catalog; owns time slots. | Unique `code`; `base_price_cents >= 0`; `admission_count > 0`. |
| `ticket_slots`, `ticket_inventories` (`TicketSlot`, `TicketInventory`) | A slot belongs to one type; its inventory is a one-to-one row keyed by `slot_id`. | Slot unique on `(ticket_type_id, visit_date, start_time)` and `end_time > start_time`. Inventory requires nonnegative `capacity/reserved/sold` and `reserved + sold <= capacity`; `version` supports conditional updates. |
| `dynamic_price_rules` (`DynamicPriceRule`) | Global rule, optionally scoped to a ticket type. | Unique `name`; adjustment must be greater than `-10000` bps; optional occupancy threshold is `0..10000`. |
| `ticket_orders`, `ticket_order_items` (`TicketOrder`, `TicketOrderItem`) | Order is user-owned; items cascade from the order but retain restricted slot/type references and immutable product/price snapshots. | Unique `order_no` and `(user_id, idempotency_key)`; payment reference is unique when present. Total and line amounts are nonnegative, quantity positive, and order status is `PENDING_PAYMENT`, `PAID`, `REFUNDED`, `EXPIRED`, or `CANCELLED`. |
| `electronic_tickets` (`ElectronicTicket`) | Issued from an order item for the owning user and slot; deleted with its order/item/user but slot deletion is restricted. | Unique `ticket_code`; status is `ISSUED`, `USED`, or `VOID`; version makes gate use a compare-and-swap transition. |
| `ticket_validations` (`TicketValidation`) | Immutable gate audit linking ticket and validator user; both deletions are constrained to retain meaningful history while the ticket exists. | Unique client `request_id`; only `ACCEPTED` is persisted. Duplicate scans resolve through request hash plus ticket state. |
| `refund_requests`, `reschedule_requests` (`RefundRequest`, `RescheduleRequest`) | User-owned audit/result rows tied to an order; reschedule also retains source and target slots. | Each is unique on `(user_id, idempotency_key)`; status is `SUCCEEDED` or `REJECTED`. |

## Guide graph, crowd, and itineraries

Source: [guide models](../server/app/db/models/guide.py#L28).

| Tables/entities | Ownership and relationships | Material uniqueness and checks |
|---|---|---|
| `attractions`, `narrations` (`Attraction`, `Narration`) | Global guide catalog. Narrations cascade with an attraction. | Unique attraction `code`; visit duration positive. Narration unique on `(attraction_id, language)` and duration positive. `audio_url` is optional and `provider_mode` records the source mode. |
| `route_nodes`, `route_edges` (`RouteNode`, `RouteEdge`) | Global schematic graph. Attraction links may be null; attraction deletion is restricted when referenced. Edges cascade with endpoint deletion. | Unique node `code` and at most one node per attraction. Directed edge unique on `(from_node_id, to_node_id)`; endpoints differ; distance and walk time are positive. |
| `crowd_snapshots` (`CrowdSnapshot`) | Append-style global observations per attraction. | Occupancy is `0..10000` bps; wait/people nonnegative; sequence positive. `(attraction_id, observed_at)` is indexed, but snapshots are not constrained to one row per sequence. |
| `itineraries`, `itinerary_items` (`Itinerary`, `ItineraryItem`) | Itinerary is user-owned. Items cascade from it while optional attraction/node deletion is restricted. `ref_type/ref_id` is an application-validated polymorphic reference. | Itinerary duration/revision positive and status `DRAFT` or `ACTIVE`. Item ordinal is positive and unique within itinerary; `end_at > start_at`; walking time nonnegative. |
| `plan_runs`, `conflict_checks` (`PlanRun`, `ConflictCheck`) | Plan runs are revision audit records; conflict checks link itinerary and requesting user. | One plan run per `(itinerary_id, revision)`. Conflict payloads and score/explanation detail are JSON snapshots. |

## Experiences, hospitality, shared inventory, and queues

Source: [marketplace models](../server/app/db/models/marketplace.py#L41).

| Tables/entities | Ownership and relationships | Material uniqueness and checks |
|---|---|---|
| `experiences`, `experience_sessions` (`Experience`, `ExperienceSession`) | Global rides/shows tied to a route node; sessions cascade with an experience. | Unique experience `code`; kind is `RIDE` or `SHOW`; duration positive and FastPass price nonnegative. Session unique on `(experience_id, starts_at)`, ends after start, and status is `OPEN`, `CLOSED`, or `CANCELLED`. |
| `hospitality_venues`, `hospitality_offers`, `bundle_components` (`HospitalityVenue`, `HospitalityOffer`, `BundleComponent`) | Global local merchant catalog. Venue is tied to a route node; offers cascade from venue; bundle components cascade from an offer and use an application-validated polymorphic resource ID. | Unique venue/offer codes. Offer price nonnegative, capacities/party size positive. Bundle resource unique on `(bundle_offer_id, component_type, component_resource_id)` and quantity positive. |
| `inventory_buckets` (`InventoryBucket`) | Shared capacity ledger for experience sessions, rooms, meals, and bundle components. `resource_type/resource_id` is intentionally polymorphic and validated by services. | Unique `(resource_type, resource_id, starts_at)`; end after start; all counts nonnegative; `held + confirmed <= capacity`; versioned. |
| `reservations`, `reservation_allocations`, `user_schedule_locks` (`Reservation`, `ReservationAllocation`, `UserScheduleLock`) | Reservation is user-owned and can allocate multiple buckets atomically. Allocations cascade from it but restrict bucket deletion. One lock row per user serializes cross-domain schedule checks. | Unique booking number and `(user_id, idempotency_key)`. Positive party/quantity, nonnegative total, finite reservation status set. Allocation unique per `(reservation_id, bucket_id)` and quantity positive. `user_schedule_locks.user_id` is the primary key. |
| `queue_entries`, `queue_counters`, `fast_passes` (`QueueEntry`, `QueueCounter`, `FastPass`) | Queue entry belongs to user and experience and may link an itinerary. Per-experience counter allocates join order. FastPass is one-to-one with a queue entry and consumes a shared inventory bucket. | Unique queue number, `(user_id, idempotency_key)`, and `(user_id, experience_id, active_key)`; positive party/sequence, nonnegative wait, finite queue statuses. FastPass has unique code, queue entry, payment reference and `(user_id, idempotency_key)`; price nonnegative and finite status set. |
| `reviews` (`Review`) | User-owned review tied to exactly one reservation; target is recorded polymorphically. | Unique `(user_id, reservation_id)`; rating `1..5`. |

`active_key` is populated only for an active queue row. Because SQL permits multiple `NULL` values, the composite unique constraint prevents a second active row without blocking a user's historical terminal rows.

## Shop, points, rewards, and sharing

Source: [commerce models](../server/app/db/models/commerce.py#L26).

| Tables/entities | Ownership and relationships | Material uniqueness and checks |
|---|---|---|
| `shop_categories`, `products`, `product_inventories`, `campaigns` (`ShopCategory`, `Product`, `ProductInventory`, `Campaign`) | Global catalog. Products belong to categories and have one inventory row keyed by product. Campaign targets a product and/or category. | Unique category code, SKU, and campaign code. Prices/stock nonnegative; optional points price positive. Discount is strictly between `0` and `10000` bps, campaign ends after start, and at least one target is present. Inventory is versioned. |
| `carts`, `cart_items` (`Cart`, `CartItem`) | Exactly one cart per user; items cascade with it and restrict product deletion. | Unique `carts.user_id` and `(cart_id, product_id)`; positive quantity and nonnegative captured add-price; cart is versioned. |
| `delivery_addresses` (`DeliveryAddress`) | User-owned checkout address. Shop orders retain a restricted reference to it. | No address deduplication constraint; API ownership is mandatory. |
| `shop_orders`, `shop_order_items` (`ShopOrder`, `ShopOrderItem`) | User-owned order with immutable product/campaign/price snapshots; items cascade from order. | Unique order number, optional payment reference, and `(user_id, idempotency_key)`. Monetary fields and points are nonnegative, total quantity positive, and status is `PENDING_PAYMENT`, `PAID`, `CANCELLED`, or `EXPIRED`. |
| `point_accounts`, `point_ledger_entries` (`PointAccount`, `PointLedgerEntry`) | One current balance per user plus immutable provenance entries. `source_type/source_id` is polymorphic and points to a business result by convention. | Account primary key is `user_id`, balance nonnegative, and versioned. Ledger unique on `(user_id, source_type, source_id, entry_type)`; delta is nonzero, resulting balance nonnegative, and type is `EARN`, `SPEND`, or `REFUND`. |
| `rewards`, `redemptions` (`Reward`, `Redemption`) | Global reward stock; redemption is user-owned and references a reward. | Unique reward code and redemption number; redemption unique on `(user_id, idempotency_key)`. Reward cost positive/stock nonnegative; redemption quantity/points positive and status `CONFIRMED` or `CANCELLED`. Both stock and account transitions are versioned. |
| `content_shares` (`ContentShare`) | User-owned verification and point-award receipt; social target is stored as type/reference text. | Unique `(user_id, share_key)` and `(user_id, idempotency_key)`; awarded points nonnegative. |

## Feedback, support, groups, and facilities

Source: [engagement models](../server/app/db/models/engagement.py#L25).

| Tables/entities | Ownership and relationships | Material uniqueness and checks |
|---|---|---|
| `feedback`, `feedback_events`, `feedback_followups` (`Feedback`, `FeedbackEvent`, `FeedbackFollowUp`) | Feedback is user-owned; events form a staff/user audit trail; optional assignee becomes null on deletion. One follow-up belongs to the submitting user. | Unique ticket number and follow-up `feedback_id`; category/status/priority are finite sets; follow-up rating `1..5`; feedback is versioned. |
| `faqs` (`FAQ`) | Global curated support catalog. | Unique `code`; active flag controls publication. |
| `support_conversations`, `support_messages` (`SupportConversation`, `SupportMessage`) | Conversation belongs to tourist, optionally assigned to support; messages cascade with it and may retain a nullable sender. | Unique conversation number. Conversation status is `OPEN/CLOSED`, mode `DEMO_BOT/LIVE`. Messages are unique on `(conversation_id, sequence)` and `(conversation_id, sender_key, idempotency_key)`; sequence positive; sender type `TOURIST/SUPPORT/BOT`. |
| `travel_groups`, `group_members`, `meeting_points`, `lost_alerts` (`TravelGroup`, `GroupMember`, `MeetingPoint`, `LostAlert`) | Group has one owner, optional shared itinerary, members, meeting points, and lost alerts. Route-node links become null; group/member children cascade. | Unique invite code and `(group_id, user_id)`; group revision positive. Member role/status are finite sets and latitude/longitude ranges are checked. Lost-alert status is `ACTIVE/RESOLVED`. |
| `facility_pois` (`FacilityPOI`) | Global accessible-facility reference data with optional route node. | Unique `code`; accessibility/open/source fields are descriptive and currently curated demo data. |

## Offline, emergency, passport, and green travel

Source: [journey models](../server/app/db/models/journey.py#L26).

| Tables/entities | Ownership and relationships | Material uniqueness and checks |
|---|---|---|
| `offline_packs`, `offline_assets` (`OfflinePack`, `OfflineAsset`) | Global versioned package manifest and child assets. | Unique pack version and ETag; version positive; expiry is null or after publication. Asset unique on `(pack_id, asset_key)` with nonnegative size; deletion cascades from pack. |
| `device_sync_states`, `user_sync_counters`, `offline_mutations` (`DeviceSyncState`, `UserSyncCounter`, `OfflineMutation`) | Per-user/per-device acknowledgement state; one user-wide cursor allocator; append-only user mutation log containing the originating device. | State unique on `(user_id, device_id)`, nonnegative cursor/client version, and optimistic version. Mutation unique on `(user_id, device_id, client_mutation_id)` and `(user_id, server_cursor)`; client/server versions positive; operation `UPSERT/DELETE`. |
| `emergency_resources`, `emergency_bulletins`, `sos_requests` (`EmergencyResource`, `EmergencyBulletin`, `SosRequest`) | Global curated resources/bulletins plus user-owned SOS audit rows; optional route-node links become null. | Unique resource/bulletin codes and SOS number; SOS unique on `(user_id, idempotency_key)`. Bulletin severity finite and end after start. SOS kind/status finite, coordinates bounded and both-null-or-both-present, and versioned. |
| `passport_stamp_definitions`, `passport_stamps` (`PassportStampDefinition`, `PassportStamp`) | Global location/stamp definition plus user-owned collection and point-award result. | Unique definition code, `(user_id, definition_id)`, and `(user_id, idempotency_key)`; configured and awarded points positive. |
| `green_tasks`, `green_task_completions` (`GreenTask`, `GreenTaskCompletion`) | Global task catalog plus user-owned evidence, verification, and point-award result. | Unique task code, `(user_id, task_id)`, and `(user_id, idempotency_key)`; task kind finite and points positive. |
| `journey_idempotency_receipts` (`JourneyIdempotencyReceipt`) | User-owned durable receipt for a duplicate passport/green attempt that targets an already completed item under a different key. | Unique `(user_id, scope, idempotency_key)`; scope is `PASSPORT_STAMP/GREEN_TASK`; outcome is `DUPLICATE_REJECTED`. |

## Transaction invariants

These are service-level guarantees backed by the constraints above:

1. **Idempotency is identity plus content.** Ticket/order, reservation, queue, shop, reward, share, SOS, passport, green, and support message operations persist an idempotency key and canonical request hash. Same key/same hash replays; same key/different hash conflicts. Unique constraints close concurrent preflight races.
2. **Schedule changes serialize per user.** Ticket orders/reschedules and marketplace reservations acquire the same `user_schedule_locks` row before checking overlaps. A conditional version increment works on SQLite and PostgreSQL and keeps the lock for the surrounding SQL transaction ([lock implementation](../server/app/services/reservations.py#L173)).
3. **Capacity is conserved.** Ticket sale is `available -> reserved -> sold`, and shared marketplace buckets are `available -> held -> confirmed`; expiry/cancel/refund reverses the appropriate quantity. Each transition is conditional and all related rows commit together. Database checks prevent negative or over-capacity terminal states.
4. **Multi-resource reservations are all-or-nothing.** A stay or bundle allocates every bucket, writes the reservation and allocation rows, and validates schedule conflicts in one transaction. Any unavailable component rolls the whole unit back.
5. **Shop checkout is all-or-nothing.** Every product stock decrement is conditional on sufficient stock, then order and line snapshots are written. A failed item restores all prior decrements through rollback ([checkout](../server/app/services/commerce.py#L480)).
6. **Points have one provenance entry.** The account row is version-locked; account balance and ledger entry commit in the same transaction. Unique business source/type prevents a completed shop payment, passport stamp, green task, share, or redemption from earning/spending twice ([point mutation](../server/app/services/points.py#L70)).
7. **Queue order is monotonic per experience.** `queue_counters.next_sequence` allocates join order, `queue_entries.sequence` orders state events, and the active-key unique constraint permits only one active queue for a user/experience. FastPass creation both transitions a versioned queue row and claims one confirmed shared-inventory unit; leaving/expiry releases it.
8. **Offline sync is user- and device-bound.** The server locks the device state, rejects stale client versions, atomically increments the user cursor for each new mutation, appends the mutation, and commits updated device state once. Signed cursors cannot be moved across users/devices ([sync push](../server/app/services/offline.py#L463)).
9. **Support ordering is durable.** Conversation `next_sequence`, message sequence uniqueness, and sender-scoped idempotency make persisted messages the source of truth; WebSocket fan-out happens after persistence.
10. **Refresh replay revokes a family.** Rotation consumes the current session and writes its child atomically. Attempted reuse revokes outstanding sessions in that family rather than issuing a second child.

## Sync, points, and queue relationships

- The offline mutation log is deliberately narrow: `NOTE`, `ITINERARY_ACK`, and `EMERGENCY_ACK` are validated in [offline.py](../server/app/services/offline.py#L297). It does not mutate point balances, queue position, passport stamps, green completions, payments, or inventory offline. Those operations require their online service invariants and provider checks.
- Passport stamps, green completions, verified content shares, and paid shop orders call the same points service. Their result row and the corresponding `point_ledger_entries` source are committed together; redemptions atomically couple reward stock, account debit, ledger entry, and redemption row.
- A `queue_entry` may reference an itinerary. Queue events can carry a recommendation and itinerary revision, while applying the recommendation updates the itinerary revision through the itinerary service. Queue persistence is independent of WebSocket delivery, so REST state remains recoverable.
- FastPass uses the same `inventory_buckets` abstraction as reservations, not queue position alone. That link is why queue, booking, and inventory locks share coordination namespaces while SQL constraints remain authoritative.

## Migration history

| Revision | Schema slice introduced |
|---|---|
| [`0001`](../server/alembic/versions/20260901_0001_foundation.py#L20) | `seed_records`. |
| [`0002`](../server/alembic/versions/20260901_0002_authentication.py#L20) | `roles`, `users`, `tourist_preferences`, `user_roles`, `refresh_sessions`. |
| [`0003`](../server/alembic/versions/20260901_0003_ticketing.py#L20) | Complete ticket catalog, slots/inventory, dynamic price rules, orders/items, electronic tickets, validations, refunds, and reschedules. |
| [`0004`](../server/alembic/versions/20260901_0004_guide_itineraries.py#L20) | Attractions/narrations, schematic graph, crowd snapshots, itineraries/items, plan runs, and conflict checks. |
| [`0005`](../server/alembic/versions/20260901_0005_marketplace_queues.py#L20) | Experiences/sessions, hospitality/offers/bundles, shared inventory, reservations/allocations/schedule locks, queues/counters, FastPass, and reviews. |
| [`0006`](../server/alembic/versions/20260901_0006_add_commerce_engagement_support_groups_.py#L21) | Shop/cart/order, products/campaigns/inventory, points/rewards/redemptions/shares, feedback/follow-up, FAQ/support, travel groups, lost alerts, and facilities. |
| [`0007`](../server/alembic/versions/20260901_0007_add_offline_emergency_passport_and_.py#L21) | Offline packs/assets and device sync log, emergency resources/bulletins/SOS, passport stamps, green tasks, and duplicate receipts. |

The revisions form one chain; do not create tables from ORM metadata in a deployed environment. Upgrade with Alembic, then run the idempotent seed path separately.
