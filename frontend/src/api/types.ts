// Mirrors the backend responses captured from the real API (see src/test/fixtures).
// Sources: backend/app/schemas/*.py, agents/orchestrator.py (start/resume/state),
// api/plans.py (get_plan), api/bookings.py. Keep field names exactly as the JSON sends them.

export type PlaceCategory =
  | "restaurant"
  | "cafe"
  | "historic"
  | "attraction"
  | "market"
  | "religious"
  | "park"
  | "museum";

export type OpeningHoursConfidence = "UNVERIFIED" | "PARTIAL" | "UNKNOWN";
export type PriceStatus = "REFERENCE_RANGE" | "FREE_CLAIM" | "UNKNOWN";

// ---- Places (/api/v1/places) ----

export interface Place {
  id: string;
  name: string;
  category: PlaceCategory;
  lat: number;
  lon: number;
  address: string | null;
  rating_value: number | null;
  rating_count: number | null;
  rating_source: string | null;
  opening_hours_raw: string | null;
  opening_hours_confidence: OpeningHoursConfidence;
  visit_minutes: number | null;
  price_min_vnd: number | null;
  price_max_vnd: number | null;
  /** Observed value "UNKNOWN" for Hue POIs: the source does not state a unit. */
  price_unit: string | null;
  price_status: PriceStatus;
  is_free_claim: boolean;
  summary: string | null;
  photo_url: string | null;
  source: string;
  source_url: string | null;
  source_place_id: string;
  collected_at: string;
  raw_attributes: Record<string, unknown>;
}

export interface PlacePage {
  items: Place[];
  total: number;
  limit: number;
  offset: number;
}

export interface PlaceSearchResult {
  place: Place;
  score: number;
  distance_km: number | null;
}

export interface PlaceSearchPage {
  items: PlaceSearchResult[];
  total: number;
  limit: number;
  offset: number;
}

// ---- Trip request and parsing (/api/v1/plans/parse) ----

export interface TripRequest {
  origin: string;
  destination: string;
  start_date: string;
  end_date: string;
  people: number;
  rooms: number;
  budget_vnd: number | null;
  categories: PlaceCategory[];
  keyword: string | null;
  preferences: string[];
  center_lat: number | null;
  center_lon: number | null;
  radius_km: number | null;
}

/** Observed: "RULES" and "FORM_FALLBACK" (no OpenAI key); "RULES+OPENAI" when OpenAI filled fields. */
export type ParseSource = "RULES" | "RULES+OPENAI" | "FORM_FALLBACK" | (string & {});

export interface ParsedTrip {
  request: TripRequest | null;
  missing_fields: string[];
  source: ParseSource;
  fields: Record<string, unknown>;
  notes: string[];
}

// ---- Workflow state (create/edit response, and `checkpoint` inside GET plan) ----

export type WorkflowStatus =
  | "RUNNING"
  | "EDITING"
  | "AWAITING_APPROVAL"
  | "APPROVED"
  | "FAILED_VALIDATION";

export interface CheckpointState {
  thread_id: string;
  status: WorkflowStatus | string;
  plan_id: string | null;
  version: number | null;
  /** Budget labels that exist on the plan (only labelled options can be approved). */
  options: string[];
  warnings: string[];
  trace: string[];
  retries: number;
  attempts: string[];
  approval: ApprovalResult | null;
  /** True while the graph waits at the approval interrupt. */
  waiting: boolean;
}

// ---- Search payload ----

export interface TransportOffer {
  id: string;
  provider: string;
  source: "MOCK" | "LIVE";
  origin: string;
  destination: string;
  departure_date: string;
  leg: "OUTBOUND" | "RETURN";
  price_vnd: number;
  price_unit: "VND_PER_PERSON_PER_LEG";
  seats_available: number;
  booking_url: string | null;
  mode: "BUS" | "TRAIN" | "FLIGHT" | null;
}

export interface HotelOffer {
  id: string;
  provider: string;
  source: "MOCK" | "LIVE";
  hotel_name: string;
  destination: string;
  check_in: string;
  check_out: string;
  rooms_available: number;
  price_per_room_night_vnd: number;
  price_unit: "VND_PER_ROOM_PER_NIGHT";
  booking_url: string | null;
  tier: "HOMESTAY" | "THREE_STAR" | "FOUR_STAR" | null;
}

export interface SearchResult {
  status: "READY" | "PARTIAL" | "UNSUPPORTED_DESTINATION";
  poi_candidates: PlaceSearchResult[];
  transport_offers: TransportOffer[];
  hotel_offers: HotelOffer[];
  warnings: string[];
}

// ---- Itinerary payload ----

export type ItineraryEventKind = "VISIT" | "MEAL" | "MEAL_BREAK" | "BUFFER";

export interface ItineraryEvent {
  kind: ItineraryEventKind;
  /** Naive local time, e.g. "2026-12-05T08:01:00". Read HH:mm by slicing, never via Date. */
  start_at: string;
  end_at: string;
  poi_id: string | null;
  name: string;
  category: string | null;
  meal: "LUNCH" | "DINNER" | "CAFE" | null;
  lat: number | null;
  lon: number | null;
  visit_minutes: number | null;
  travel_distance_km: number | null;
  travel_minutes_estimated: number | null;
  warnings: string[];
}

export interface ItineraryDay {
  date: string;
  events: ItineraryEvent[];
  warnings: string[];
}

export interface ItineraryResult {
  days: ItineraryDay[];
  unplanned_poi_ids: string[];
  excluded_poi_ids: string[];
  merged_poi_ids: string[];
  warnings: string[];
  validation: { valid: boolean; warnings: string[] };
}

// ---- Budget payload ----

/** Observed sources: "MOCK", "HUE_POI_SOURCE", "BUDGET_CONFIG". */
export type CostSource = "MOCK" | "HUE_POI_SOURCE" | "BUDGET_CONFIG" | (string & {});

export interface CostItem {
  code: string;
  label: string;
  amount_vnd: number | null;
  amount_max_vnd: number | null;
  quantity: number;
  price_unit: string;
  source: CostSource;
  price_kind: "QUOTED" | "ESTIMATED" | "UNKNOWN";
  note: string | null;
  poi_id: string | null;
}

export type BudgetStatus =
  | "WITHIN_BUDGET"
  | "WITHIN_BUDGET_EXCLUDING_UNKNOWN"
  | "OVER_BUDGET"
  | "UNKNOWN";

export type OptionLabel = "BUDGET" | "BALANCED" | "COMFORT";

export interface BudgetOption {
  transport_outbound: TransportOffer | null;
  transport_return: TransportOffer | null;
  hotel: HotelOffer | null;
  items: CostItem[];
  known_total_vnd: number;
  known_total_max_vnd: number;
  unknown_item_count: number;
  budget_status: BudgetStatus;
  budget_remaining_vnd: number | null;
  /** Only the labelled options can be approved; most options have label null. */
  label: OptionLabel | null;
  warnings: string[];
}

export interface BudgetResult {
  options: BudgetOption[];
  warnings: string[];
  shortfall_vnd: number | null;
}

// ---- Plan (GET /api/v1/plans/{thread_id}) ----

export interface PlanPayload {
  request: TripRequest;
  search: SearchResult;
  budget: BudgetResult;
  itinerary: ItineraryResult;
}

export interface PlanRecord {
  thread_id: string;
  trip_id: string;
  owner_id: string;
  plan_id: string;
  version: number;
  /** Trip status as stored (same vocabulary as the workflow status). */
  status: WorkflowStatus | string;
  payload: PlanPayload;
  checkpoint: CheckpointState | null;
}

// ---- Approval (POST /api/v1/plans/{thread_id}/approve) ----

export interface ApprovalRequest {
  version: number;
  option: OptionLabel;
}

export interface SelectedOffer {
  kind: "TRANSPORT" | "HOTEL";
  leg: "OUTBOUND" | "RETURN" | null;
  id: string;
  name: string;
  price: number;
  unit: string;
  dates: string;
}

export interface ApprovalResult {
  approval_id: string;
  plan_id: string;
  version: number;
  option: OptionLabel;
  quote_hash: string;
  selected_offers: SelectedOffer[];
  status: "APPROVED";
}

// ---- Booking (POST /api/v1/plans/{thread_id}/book) ----

export type BookingStatus =
  | "PENDING"
  | "BOOKED"
  | "FAILED"
  | "UNKNOWN"
  | "PARTIALLY_BOOKED"
  | "RECONFIRM_REQUIRED"
  | "NOT_SUPPORTED_BY_DATASET";

export interface BookingItem {
  offer_id: string | null;
  poi_id: string | null;
  kind: "TRANSPORT" | "HOTEL" | "POI";
  status: BookingStatus;
  source: "MOCK" | "HUE_POI_SOURCE";
  reference: string | null;
  price_vnd: number | null;
  contact_url: string | null;
  contact_address: string | null;
  contact_phone: string | null;
  message: string | null;
}

export interface BookingResult {
  intent_id: string;
  status: BookingStatus;
  items: BookingItem[];
  plan_version: number;
  approval_id: string;
  quote_hash: string;
  explanation: string[];
  source: "MOCK";
}

export interface BookingRequest {
  idempotency_key: string;
}

// ---- Errors ----

/** FastAPI validation errors (422) arrive as a list; domain errors as a string. */
export interface ValidationIssue {
  type: string;
  loc: (string | number)[];
  msg: string;
  input?: unknown;
}

export interface ErrorBody {
  detail: string | ValidationIssue[];
}

// ---- Chat (/api/v1/chat) ----
// Mirrors backend/app/chat/schemas.py (ChatReply, Card union) and the stored history payloads.

/** "OLLAMA" when the LLM read the message; "RULES" for the Vietnamese rules (Ollama off or unavailable). */
export type UnderstandingSource = "OLLAMA" | "RULES";

export interface UnderstandingInfo {
  intent: string;
  source: UnderstandingSource;
  notes: string[];
}

export interface ChatPlanItem {
  time: string;
  name: string;
  kind: string;
  meal: "LUNCH" | "DINNER" | "CAFE" | null;
  /** Null for breaks and stops without a source POI. */
  poi_id: string | null;
}

export interface ChatPlanDay {
  date: string;
  items: ChatPlanItem[];
}

export interface ChatBudgetOption {
  /** Option code (BUDGET, BALANCED, COMFORT); shown to users as Tiết kiệm, Cân bằng, Thoải mái. */
  label: OptionLabel;
  known_total_vnd: number;
  known_total_max_vnd: number;
  budget_status: string;
}

export interface ChatPlanCard {
  kind: "plan_summary";
  thread_id: string;
  status: WorkflowStatus | string;
  version: number;
  days: ChatPlanDay[];
  budget_options: ChatBudgetOption[];
}

export interface ChatPlaceCard {
  kind: "place";
  poi_id: string;
  name: string;
  category: PlaceCategory | string;
  address: string | null;
  opening_hours_raw: string | null;
  opening_hours_note: string;
  price_min_vnd: number | null;
  price_max_vnd: number | null;
  phone: string | null;
  source_url: string | null;
}

export interface ChatBookingCard {
  kind: "booking";
  result: BookingResult;
}

export type ChatCard = ChatPlanCard | ChatPlaceCard | ChatBookingCard;

/** Set while the bot waits for "đồng ý" (approve, book) or for an answer (defaults). */
export interface PendingConfirmation {
  kind: "approve" | "book" | "defaults" | (string & {});
  option?: OptionLabel;
  version?: number;
  quote_hash?: string;
}

export interface ChatReply {
  message_id: string;
  text: string;
  cards: ChatCard[];
  quick_replies: string[];
  pending_confirmation: PendingConfirmation | null;
  understanding: UnderstandingInfo;
}

export interface ChatMessageRecord {
  id: string;
  role: "user" | "assistant";
  text: string;
  created_at: string;
  /** The full ChatReply for assistant messages; null for user messages. */
  payload: ChatReply | null;
}

export interface ChatHistory {
  conversation_id: string;
  messages: ChatMessageRecord[];
}
