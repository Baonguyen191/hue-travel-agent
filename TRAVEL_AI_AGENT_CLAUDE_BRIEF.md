# Travel AI Agent --- Project Implementation Brief for Claude Code

> **Mục tiêu:** Xây dựng một AI Travel Agent có trải nghiệm hội thoại tự
> nhiên như ChatGPT, có khả năng tư vấn du lịch, ghi nhớ ngữ cảnh và sở
> thích, truy xuất kiến thức, tìm địa điểm/dịch vụ có dữ liệu động, lập
> lịch trình và tối ưu tuyến đường bằng OR-Tools.
>
> **Vai trò của Claude Code:** Đọc repository hiện tại, đánh giá trạng
> thái dự án, đề xuất kế hoạch triển khai theo từng phase, sau đó thực
> hiện từng phase với code chạy được, test, tài liệu và báo cáo rõ ràng.
> Không tự ý viết lại toàn bộ hệ thống nếu chưa kiểm tra code hiện có.

------------------------------------------------------------------------

## 1. Nguyên tắc làm việc bắt buộc

1.  **Inspect before coding:** Trước tiên đọc cấu trúc repository,
    README, dependency, cấu hình, database schema, API và test hiện có.
2.  **Preserve existing work:** Tận dụng code tốt đang có. Không tạo
    thêm abstraction/framework không cần thiết và không làm codebase
    phình to.
3.  **Plan before implementation:** Viết implementation plan có thứ tự
    phụ thuộc, file dự kiến thay đổi, rủi ro và tiêu chí nghiệm thu.
4.  **Incremental delivery:** Triển khai từng phase nhỏ. Sau mỗi phase
    chạy formatter, linter, type checks (nếu có), unit tests và
    integration tests liên quan.
5.  **No fake integrations:** Không giả vờ API đã hoạt động. Nếu thiếu
    API key, tạo interface + mock/fake adapter dùng trong development,
    ghi rõ cách cấu hình adapter thật.
6.  **No fabricated travel facts:** Không tự bịa giờ mở cửa, giá vé,
    rating, tình trạng hoạt động, thời tiết hoặc thời gian di chuyển. Dữ
    liệu thiếu phải được đánh dấu unknown/estimated và nói rõ nguồn,
    thời điểm kiểm tra.
7.  **Respect provider policies and licenses:** Kiểm tra điều khoản API,
    attribution, giới hạn cache/lưu trữ và giấy phép dữ liệu trước khi
    persist. Không scrape trái phép.
8.  **Secrets:** Dùng environment variables hoặc secret manager; không
    commit API keys, tokens, credentials.
9.  **Keep interfaces testable:** Tách domain logic khỏi LLM provider,
    external APIs, database và framework.
10. **Explain decisions:** Khi chọn kiến trúc hoặc thư viện, giải thích
    ngắn gọn lý do và trade-off.

Nếu repository đã có quy ước khác, ưu tiên quy ước đang tồn tại trừ khi
có vấn đề rõ ràng.

------------------------------------------------------------------------

## 2. Product vision và phạm vi

Sản phẩm là một trợ lý du lịch hội thoại. Người dùng có thể bắt đầu bằng
câu tự nhiên, trao đổi nhiều lượt, thay đổi yêu cầu giữa chừng và yêu
cầu giải thích đề xuất.

### 2.1 Năng lực người dùng nhìn thấy

-   **Chit-chat:** Chào hỏi, cảm ơn, hỏi đáp thông thường; không gọi
    tool không cần thiết.
-   **Travel consultation:** Tư vấn điểm đến, mùa du lịch, hoạt động,
    đặc sản, kinh nghiệm.
-   **Travel Q&A:** Trả lời dựa trên nguồn dữ liệu có thể truy xuất và
    trích dẫn.
-   **Place discovery:** Tìm điểm tham quan, nhà hàng, cafe, khách sạn
    và dịch vụ.
-   **Trip planning:** Lập lịch trình nhiều ngày, có khung giờ và thứ tự
    di chuyển.
-   **Plan editing:** Thêm/bỏ/thay địa điểm, giảm mật độ lịch trình, đổi
    ngày, thay ngân sách.
-   **Personalization:** Cá nhân hóa theo sở thích như chụp ảnh, ẩm
    thực, thiên nhiên, lịch sử, mua sắm; nhịp độ du lịch, ngân sách và
    khả năng đi bộ.
-   **Context retention:** Hiểu "ở đó", "ngày thứ hai", "quán gần địa
    điểm vừa nói", "đổi chỗ này" dựa trên hội thoại trước.
-   **Explainability:** Giải thích vì sao chọn địa điểm, vì sao bỏ địa
    điểm và các đánh đổi trong lịch trình.
-   **Uncertainty handling:** Hỏi lại khi thiếu dữ liệu quan trọng;
    trình bày giả định khi người dùng không cung cấp đủ thông tin.

### 2.2 Không nằm trong MVP nếu chưa có yêu cầu

-   Booking/thanh toán thực tế.
-   Tự động đặt vé, phòng hoặc nhà hàng.
-   Social network, chia sẻ lịch trình công khai.
-   Huấn luyện LLM foundation model từ đầu.
-   Reinforcement learning/GRPO trong production.
-   Dự đoán rating hoặc tình trạng mở cửa nếu không có dữ liệu đáng tin
    cậy.

Ưu tiên một MVP end-to-end đáng tin cậy trước khi mở rộng.

------------------------------------------------------------------------

## 3. Kiến trúc logic mục tiêu

Thiết kế theo module, không bắt buộc phải tách thành microservices. Với
MVP, ưu tiên modular monolith để giảm độ phức tạp vận hành.

``` text
Client (Web / Mobile)
        |
        v
Conversation API
        |
        v
Conversation Orchestrator (LangGraph hoặc orchestration hiện có)
        |
        +--> Context & Memory
        |
        +--> Intent / Capability Router
        |       |
        |       +--> Chit-chat Handler
        |       +--> Travel Knowledge QA --> RAG Retriever
        |       +--> Place Discovery -----> Places Provider
        |       +--> Weather Query -------> Weather Provider
        |       +--> Trip Planning -------> Planning Service
        |       +--> Plan Modification ---> Replanning Service
        |       +--> Preference Update ---> User Profile Service
        |
        +--> Personalization / Ranking
        |
        +--> Response Composer
        |
        v
Persistence + Observability
```

### 3.1 Quy tắc routing

Router phải phân biệt tối thiểu:

-   `SMALL_TALK`
-   `TRAVEL_QA`
-   `PLACE_SEARCH`
-   `WEATHER_QUERY`
-   `TRIP_CREATE`
-   `TRIP_MODIFY`
-   `PREFERENCE_UPDATE`
-   `ITINERARY_EXPLANATION`
-   `GENERAL_HELP`
-   `NEED_CLARIFICATION`

Không cần tạo một LLM call riêng cho mọi nhánh nếu có thể dùng một bước
classification có schema rõ ràng. Các câu đơn giản như "cảm ơn", "xin
chào" nên trả lời trực tiếp. Chỉ gọi RAG/tools/optimizer khi intent cần
chúng.

Router cần giữ được context để hiểu follow-up. Ví dụ: - "Tôi muốn đi Huế
2 ngày" → tạo trip request. - "Tôi thích chụp ảnh" → cập nhật
preference/context của trip. - "Có quán cafe nào gần đó không?" → dùng
vị trí/POI đang được nhắc đến. - "Lịch trình hơi dày, giảm bớt đi" → sửa
itinerary hiện tại và kiểm tra lại constraints.

### 3.2 State hội thoại

Thiết kế state có kiểu dữ liệu rõ ràng, tối thiểu gồm:

``` python
class ConversationState:
    conversation_id: str
    user_id: str | None
    messages: list
    current_intent: str | None
    trip_request: dict | None
    current_itinerary: dict | None
    active_location: dict | None
    temporary_preferences: dict
    retrieved_context: list
    tool_results: dict
    pending_clarification: dict | None
```

Đây là schema minh họa, cần điều chỉnh theo codebase. Không lưu toàn bộ
lịch sử vào prompt vô hạn; cần giới hạn context, tóm tắt hội thoại cũ và
truy xuất phần liên quan.

------------------------------------------------------------------------

## 4. Data architecture: Static, Dynamic và Real-time

Không xem mọi dữ liệu du lịch là một loại dữ liệu. Phân chia theo tốc độ
thay đổi và quyền lưu trữ.

### 4.1 Static / slow-changing knowledge

Ví dụ: - Lịch sử, văn hóa, mô tả di tích. - Thông tin địa lý cơ bản. -
Loại hình hoạt động và chủ đề trải nghiệm. - Nội dung hướng dẫn du lịch
có nguồn.

Dùng cho RAG: - PostgreSQL hoặc document storage làm nguồn dữ liệu
chuẩn. - Vector database (ví dụ Qdrant) cho semantic retrieval nếu
repository đã chọn vector DB. - Embedding model có thể dùng BGE-M3 nếu
phù hợp với ngôn ngữ và hạ tầng hiện có.

Mỗi tài liệu/đoạn văn cần metadata: - `source_id` - `source_name` -
`source_url` - `license` - `published_at` (nếu có) - `collected_at` -
`last_verified_at` - `city` - `language` - `content_type`

Không đưa nội dung không rõ nguồn vào knowledge base production.

### 4.2 Dynamic place data

Ví dụ: - Cafe, nhà hàng, khách sạn. - Rating/review count. - Giờ mở
cửa. - Giá/price level. - Tình trạng hoạt động.

Ưu tiên truy vấn provider khi cần thay vì tự xây một snapshot lỗi thời.
Có thể tạo provider interface cho Google Places, Foursquare hoặc nguồn
khác sau khi kiểm tra điều khoản hiện hành.

Chỉ persist trường mà provider cho phép lưu. Không mặc định rằng có thể
lưu vĩnh viễn toàn bộ response, ảnh, review hoặc rating.

### 4.3 Real-time data

Ví dụ: - Thời tiết. - Giao thông/thời gian di chuyển. - Tình trạng đóng
cửa/tạm ngừng nếu provider cung cấp. - Sự kiện hoặc cảnh báo có thời
hạn.

Gọi API khi cần, có timeout, retry có giới hạn, cache theo policy
provider và hiển thị `fetched_at`/nguồn khi thích hợp.

### 4.4 Provider interfaces

Tạo abstraction, tránh để domain logic phụ thuộc trực tiếp vào SDK của
một nhà cung cấp:

``` python
class PlacesProvider:
    async def search_places(self, query, location, radius_m, filters):
        ...

    async def get_place_details(self, provider_place_id):
        ...

class WeatherProvider:
    async def get_forecast(self, coordinates, start_date, end_date):
        ...

class RoutingProvider:
    async def get_travel_matrix(self, locations, mode):
        ...
```

Tên và kiểu dữ liệu cần theo chuẩn codebase. Có adapter thật và adapter
mock cho test. Provider failure phải trả lỗi có cấu trúc, không trả dữ
liệu giả như dữ liệu thật.

### 4.5 Freshness và provenance

Mỗi dữ liệu động nên có: - nguồn/provider, - thời điểm lấy dữ liệu, -
thời điểm kiểm chứng (nếu có), - trạng thái freshness, - giới hạn sử
dụng/lưu trữ.

Không áp dụng một TTL chung cho tất cả dữ liệu. TTL phải dựa trên loại
dữ liệu và policy provider. Cache chỉ là tối ưu hiệu năng, không phải
bằng chứng dữ liệu còn đúng.

------------------------------------------------------------------------

## 5. Data model đề xuất

Đây là mô hình logic tham khảo; Claude cần đối chiếu schema hiện tại
trước khi tạo migration.

### 5.1 Place / POI

``` text
Place
- id
- name
- category
- description
- city_id
- latitude
- longitude
- source
- source_place_id
- created_at
- updated_at
```

Thông tin thay đổi theo thời gian nên tách thành snapshot/cache có
policy rõ ràng, không nhồi tất cả vào một bảng.

### 5.2 Experience Spot

Một POI lớn có thể chứa nhiều điểm trải nghiệm nhỏ. Ví dụ một quần thể
di tích có cổng, hồ, hành lang, sân hoặc góc ngắm cảnh.

``` text
ExperienceSpot
- id
- parent_place_id
- name
- description
- activities[]
- styles[]
- best_time
- estimated_duration_minutes
- latitude
- longitude
- source
- verified_at
- access_notes
- photo_permission_notes
```

Các thuộc tính về góc chụp, thời điểm đẹp, quyền tiếp cận/chụp ảnh phải
có nguồn hoặc được đánh dấu là gợi ý chưa xác minh. Không tự tạo tọa độ
hoặc khẳng định nơi đó được phép chụp.

### 5.3 User Profile / Preferences

``` json
{
  "activities": {
    "photography": 0.9,
    "food": 0.8,
    "nature": 0.7,
    "history": 0.5,
    "shopping": 0.2
  },
  "photography_styles": ["architecture", "nature"],
  "travel_style": "relaxed",
  "walking_tolerance": 0.7,
  "budget_preference": "moderate"
}
```

Điểm số chỉ là biểu diễn preference, không phải xác suất. Phải hỗ trợ
`unknown` và không tự suy luận chắc chắn từ một câu nói thoáng qua.

Nguồn preference: - Explicit: người dùng nói rõ. - Implicit: hành vi
chọn/lưu/bỏ gợi ý. - Contextual: chỉ đúng với chuyến đi hiện tại.

Tách: - Long-term user preference. - Trip-specific preference. -
Conversation-local temporary preference.

Cho phép người dùng xem, sửa và xóa preference. Không lưu thông tin nhạy
cảm không cần thiết.

### 5.4 Trip / Itinerary

Tối thiểu cần lưu: - Trip destination, dates/duration, party size nếu
cần. - Budget và currency. - Interests, travel pace, transportation
mode. - Constraints (opening hours, meal times, fixed appointments,
accessibility nếu người dùng cung cấp). - Danh sách itinerary days và
stops. - Travel legs, estimated duration, source và timestamp. -
Assumptions và unresolved warnings.

------------------------------------------------------------------------

## 6. RAG --- Travel Knowledge QA

RAG dùng để trả lời câu hỏi cần kiến thức có căn cứ, không dùng thay cho
API động.

### 6.1 Pipeline

``` text
Source documents
  -> ingestion
  -> cleaning / deduplication
  -> chunking
  -> metadata enrichment
  -> embedding
  -> vector index

User query
  -> query understanding
  -> retrieval (semantic + metadata filters)
  -> reranking (nếu cần)
  -> grounded answer
  -> citations / source links
```

### 6.2 Yêu cầu chất lượng

-   Chunking theo cấu trúc tài liệu, tránh cắt giữa câu/đoạn có quan hệ.
-   Lưu metadata đủ để lọc theo city, category, language, source.
-   Trả lời "không đủ nguồn" nếu retrieval không hỗ trợ kết luận.
-   Trích nguồn theo từng nhóm thông tin quan trọng.
-   Không dùng vector similarity score như xác suất đúng.
-   Phân biệt thông tin từ tài liệu tĩnh với dữ liệu API mới lấy.

### 6.3 Evaluation RAG

Tạo tập test có câu hỏi, expected evidence và expected answer. Đo: -
`Recall@K`: có lấy được tài liệu bằng chứng cần thiết không. -
`Precision@K`: top K có nhiều tài liệu liên quan không. - `MRR` /
`nDCG@K`: xếp hạng kết quả có tốt không. - `Faithfulness`: câu trả lời
có được hỗ trợ bởi context không. - `Answer relevancy`: có trả lời đúng
trọng tâm không. - Citation correctness: nguồn trích dẫn có thật sự hỗ
trợ câu trả lời không.

Không chỉ đánh giá bằng LLM-as-a-judge; cần có một tập kiểm thử được con
người gán nhãn.

------------------------------------------------------------------------

## 7. Personalization Engine

Mục tiêu: không chỉ đề xuất địa điểm nổi tiếng mà đề xuất trải nghiệm
phù hợp với người dùng và bối cảnh.

### 7.1 Ví dụ

Người dùng thích chụp ảnh kiến trúc và cafe. Nếu lịch trình có một quần
thể di tích, Agent có thể: 1. Tìm Experience Spots bên trong hoặc gần
POI. 2. Lọc theo khoảng cách, thời gian, khả năng tiếp cận, thời tiết và
quyền chụp ảnh. 3. Xếp hạng theo sở thích. 4. Đề xuất một vài điểm phù
hợp. 5. Nếu người dùng đồng ý, thêm vào itinerary. 6. Chạy kiểm tra
constraints/route lại.

### 7.2 Scoring ban đầu

Có thể bắt đầu bằng weighted ranking dễ giải thích:

``` text
score =
    w_preference * preference_match
  + w_context    * context_match
  + w_quality    * source_quality
  + w_convenience* convenience
  + w_freshness  * freshness
```

Đây chỉ là baseline. Chuẩn hóa feature, tune weights bằng validation set
và kiểm tra bias/diversity. Không để một sở thích lấn át hoàn toàn các
loại trải nghiệm khác.

### 7.3 Feedback loop

Thu thập hành vi có ý nghĩa: - View details. - Save. - Add to
itinerary. - Remove. - Mark as visited. - Rate / provide feedback.

Không coi click đơn thuần là sở thích mạnh. Dùng mức độ tín hiệu khác
nhau và cho phép user sửa profile.

### 7.4 Evaluation personalization

-   Precision@K, Recall@K, NDCG@K.
-   Preference match.
-   Diversity / category coverage.
-   Novelty (nếu phù hợp).
-   User acceptance / save / add rate.
-   Constraint satisfaction.
-   Không chỉ tối ưu click-through rate.

------------------------------------------------------------------------

## 8. Trip Planning và OR-Tools

OR-Tools là optimizer cho bài toán ràng buộc, không phải chatbot và
không tự biết dữ liệu du lịch đúng hay sai.

### 8.1 Input

-   Candidate places đã lọc theo sở thích và khu vực.
-   Coordinates.
-   Travel-time/distance matrix từ routing provider.
-   Estimated visit duration.
-   Opening hours (nếu đã xác minh).
-   Ticket/meal cost nếu có dữ liệu.
-   Ngày, giờ bắt đầu/kết thúc.
-   Ngân sách.
-   Các fixed stops hoặc constraints của người dùng.
-   Travel mode.

### 8.2 Bài toán phù hợp

Bắt đầu với một ngày có nhiều điểm: - Chọn tập địa điểm. - Sắp xếp thứ
tự. - Giới hạn tổng thời gian. - Tôn trọng time windows nếu có dữ
liệu. - Giảm thời gian di chuyển. - Tối đa hóa preference/relevance
score.

Có thể mô hình hóa bằng OR-Tools Routing Solver hoặc CP-SAT tùy cấu
trúc. Không ép mọi bài toán vào một solver.

### 8.3 Objective minh họa

``` text
maximize:
    preference_score
  + experience_quality
  + category_diversity
  - travel_time_penalty
  - budget_penalty
  - schedule_overload_penalty
```

Hard constraints (ví dụ điểm đóng cửa trước khi đến, fixed appointment)
phải tách khỏi soft preferences (ví dụ thích cafe hơn mua sắm). Không
được "thỏa hiệp" với hard constraints bằng cách chỉ trừ điểm.

### 8.4 Feasibility và fallback

-   Validate input trước khi solve.
-   Giới hạn candidate count.
-   Timeout solver.
-   Phân biệt `OPTIMAL`, `FEASIBLE`, `INFEASIBLE`, `UNKNOWN` hoặc trạng
    thái tương đương.
-   Nếu không có solution, giải thích constraint xung đột và đề xuất nới
    một constraint.
-   Nếu thiếu opening hours hoặc travel matrix, đánh dấu lịch trình là
    ước tính; không giả vờ đã kiểm chứng.
-   Sau khi thêm/bỏ stop, chạy validate và optimize lại.

### 8.5 Recommendation enrichment

Không để LLM tự ý thêm stop sau khi optimizer chạy xong mà không kiểm
tra lại. Flow đúng:

``` text
Base itinerary
  -> retrieve experience spots
  -> personalized ranking
  -> propose candidate additions
  -> user accepts / system policy selects
  -> re-run feasibility + optimization
  -> final itinerary
```

------------------------------------------------------------------------

## 9. Conversational Agent và LangGraph

### 9.1 Node gợi ý

``` text
START
  -> load_context
  -> understand_message
  -> route_intent
       -> chit_chat
       -> travel_qa
       -> place_search
       -> weather_query
       -> create_trip
       -> modify_trip
       -> update_preferences
       -> explain_itinerary
       -> ask_clarification
  -> compose_response
  -> persist_conversation
  -> END
```

Tên node có thể khác theo convention dự án. Không cần tạo một graph node
cho từng hàm nhỏ; chỉ tách khi có ranh giới logic, retry, state
transition hoặc khả năng test độc lập.

### 9.2 Tool design

Mỗi tool cần: - Tên cụ thể, mô tả rõ. - Docstring giải thích khi nào
dùng/không dùng. - Typed arguments và schema. - Validate đầu vào. -
Timeout, retry có giới hạn. - Structured output. - Error type rõ ràng. -
Không expose API key hoặc stack trace cho model/user.

Ví dụ tool: - `search_places` - `get_place_details` -
`get_weather_forecast` - `get_travel_time_matrix` -
`retrieve_travel_knowledge` - `create_itinerary` - `modify_itinerary` -
`get_user_preferences` - `update_user_preferences`

Không tạo tool trùng chức năng hoặc tool quá tổng quát kiểu
`do_anything`.

### 9.3 Memory

Phân biệt: 1. Conversation history: các lượt chat gần đây. 2.
Conversation summary: tóm tắt các lượt cũ để giữ context. 3. Trip state:
itinerary và constraints hiện hành. 4. Long-term user profile:
preference được phép lưu. 5. Retrieval memory: dữ liệu quá khứ cần tìm
lại theo truy vấn.

Không dùng vector DB thay thế toàn bộ relational state. Các dữ liệu có
cấu trúc và cần cập nhật chính xác nên nằm trong database phù hợp.

------------------------------------------------------------------------

## 10. API và frontend

Nếu repository đã có frontend/backend, tiếp tục theo stack hiện tại. Nếu
chưa có, có thể cân nhắc: - Backend: Python + FastAPI. - Orchestration:
LangGraph. - Database: PostgreSQL. - Geospatial: PostGIS. - Vector
store: Qdrant (chỉ khi RAG cần). - Cache/queue: Redis khi có nhu cầu
thực. - Optimizer: OR-Tools. - Frontend: Next.js + TypeScript.

### 10.1 API tối thiểu

``` text
POST /api/conversations
POST /api/conversations/{conversation_id}/messages
GET  /api/conversations/{conversation_id}
GET  /api/users/me/preferences
PATCH /api/users/me/preferences
POST /api/trips
GET  /api/trips/{trip_id}
PATCH /api/trips/{trip_id}
POST /api/trips/{trip_id}/optimize
```

Đây là đề xuất, không bắt buộc giữ nguyên endpoint nếu dự án đã có
convention.

### 10.2 UX yêu cầu

-   Chat UI hỗ trợ streaming nếu stack hiện tại làm được ổn định.
-   Hiển thị tool activity ở mức hữu ích, không lộ chain-of-thought hoặc
    thông tin nội bộ.
-   Itinerary nên có day grouping, timeline, duration, travel leg và
    warning.
-   Nguồn/độ mới dữ liệu cần hiển thị khi có ý nghĩa.
-   Người dùng sửa được itinerary; không bắt buộc phải chat để sửa.
-   Hỗ trợ loading, empty, error, retry và cancellation.
-   Không hiển thị thông tin chưa xác minh như sự thật chắc chắn.

------------------------------------------------------------------------

## 11. Security, privacy và reliability

-   Validate mọi input từ client và tool.
-   AuthN/AuthZ: user chỉ được đọc/sửa dữ liệu của chính họ.
-   Không để prompt injection trong retrieved documents/tool results
    điều khiển hệ thống.
-   Tool allowlist; không cho LLM thực thi SQL/shell tùy ý.
-   Rate limit và giới hạn chi phí LLM/API.
-   Timeout/circuit breaker cho external provider khi phù hợp.
-   Idempotency cho thao tác tạo/sửa trip nếu có retry.
-   Log có cấu trúc, không log secrets hoặc dữ liệu cá nhân không cần
    thiết.
-   Có cơ chế xóa conversation/profile theo yêu cầu.
-   Kiểm soát CORS, cookie/token và upload nếu ứng dụng có các chức năng
    này.

------------------------------------------------------------------------

## 12. Observability và evaluation toàn hệ thống

Mỗi request nên có correlation ID và trace các bước: - Intent
classification. - Retrieval. - LLM calls. - Tool calls. - Optimizer. -
Response generation.

Ghi nhận: - Latency theo stage và end-to-end. - Token usage / estimated
LLM cost. - External API latency/error rate. - Tool selection
accuracy. - Tool argument validity. - RAG metrics. - Planning
feasibility / constraint violations. - Personalization metrics. - Task
success / user feedback.

Không log chain-of-thought. Có thể log intent, tool name, sanitized
arguments, tool result summary và trạng thái để debug.

### 12.1 Test scenarios bắt buộc

1.  Chit-chat đơn giản không gọi external tool.
2.  Hỏi kiến thức về một di tích → RAG trả lời có nguồn.
3.  Hỏi cafe gần một POI → place search dùng đúng location context.
4.  Hỏi thời tiết → weather provider; nếu API lỗi phải báo rõ.
5.  Yêu cầu lịch trình 2 ngày → tạo itinerary hợp lệ.
6.  "Giảm bớt địa điểm" → sửa itinerary đang có, không tạo trip mới vô
    cớ.
7.  "Tôi thích chụp ảnh" → cập nhật preference đúng scope.
8.  "Có góc chụp đẹp gần đó không?" → dùng active POI và Experience
    Spots.
9.  Thêm một địa điểm → validate time windows và optimize lại.
10. Dữ liệu thiếu giờ mở cửa → không tự bịa giờ.
11. Routing API lỗi → graceful fallback và gắn nhãn ước tính.
12. User A không truy cập được trip/profile của User B.
13. Prompt injection nằm trong retrieved document không làm lộ secrets
    hoặc thay đổi system policy.
14. Solver không tìm được solution → trả lời có giải thích, không trả
    lịch trình giả.

------------------------------------------------------------------------

## 13. Implementation roadmap

Claude phải điều chỉnh roadmap sau khi inspect repository. Đề xuất thứ
tự:

### Phase 0 --- Repository audit

Deliverables: - Sơ đồ cấu trúc hiện tại. - Stack/dependency hiện tại. -
Các module đã có và còn thiếu. - Điểm yếu/rủi ro. - Implementation plan
theo file/module. - Không sửa code lớn trong phase này.

Acceptance: - Có thể giải thích request đi từ API đến response qua những
thành phần nào. - Xác định được test command và cách chạy local.

### Phase 1 --- Domain foundation

Implement: - Typed domain models cho Place, ExperienceSpot,
UserPreference, Trip, Itinerary. - Validation. - Persistence/migrations
theo DB hiện có. - Provider interfaces và mock adapters.

Acceptance: - Unit tests cho model/validation. - Migration chạy được. -
Không phá dữ liệu hoặc endpoint hiện có.

### Phase 2 --- Conversational foundation

Implement: - Conversation API. - Context/state management. - Intent
routing. - Chit-chat handler. - Clarification. - Follow-up và plan
modification context.

Acceptance: - Chit-chat không gọi tool thừa. - Follow-up hiểu được tham
chiếu hội thoại. - Context không tăng vô hạn.

### Phase 3 --- RAG và travel knowledge

Implement: - Ingestion pipeline. - Chunking/metadata. - Retrieval. -
Grounded response và citations. - Evaluation dataset cơ bản.

Acceptance: - Có test retrieval và citation. - Không trả lời chắc chắn
khi không có evidence. - Có thể thay embedding/vector provider qua
interface phù hợp.

### Phase 4 --- Dynamic tools

Implement: - Places provider. - Weather provider. - Routing provider. -
Cache có policy. - Error handling và source timestamps.

Acceptance: - Mock integration tests chạy offline. - Thiếu API key có
hướng dẫn rõ. - Không trả dữ liệu mock như dữ liệu production.

### Phase 5 --- Personalization

Implement: - Profile read/update. - Explicit preference extraction. -
Experience Spot retrieval/ranking. - Feedback events. - Preference
scope: long-term, trip-specific, temporary.

Acceptance: - Preference có evidence/source hoặc user confirmation. -
User có thể xem/sửa/xóa preference. - Recommendation giải thích được ở
mức feature.

### Phase 6 --- OR-Tools planning

Implement: - Candidate filtering. - Travel matrix integration. -
Objective và hard/soft constraints. - Solver timeout/status. -
Feasibility validation. - Plan modification/re-optimization.

Acceptance: - Có test case feasible và infeasible. - Không vi phạm hard
constraints trong solution được chấp nhận. - Có fallback khi thiếu dữ
liệu. - Có thể giải thích trade-off.

### Phase 7 --- Frontend integration

Implement: - Chat UX. - Streaming. - Itinerary timeline/map nếu project
hỗ trợ. - Preference controls. - Loading/error states. -
Source/freshness indicators.

Acceptance: - Hoàn thành các user journeys ở mục 12.1. - Không để UI
hiển thị dữ liệu chưa xác minh như dữ liệu chắc chắn.

### Phase 8 --- Hardening và evaluation

Implement: - Auth/privacy checks. - Observability. - Regression tests. -
Cost/latency measurement. - Documentation và deployment guide.

Acceptance: - Test suite chạy được. - Có báo cáo metric baseline. - Có
hướng dẫn setup, env vars, seed data, chạy local và deploy.

------------------------------------------------------------------------

## 14. Coding standards và Definition of Done

Một task chỉ được coi là hoàn thành khi: - Code có type hints ở public
interfaces. - Có validation và error handling phù hợp. - Có test cho
logic mới và regression quan trọng. - Không có secret hoặc dữ liệu nhạy
cảm trong log. - Không thêm dependency nếu chưa có lý do. -
README/config được cập nhật khi cần. - Linter/formatter/test hiện có
chạy thành công. - Báo cáo rõ file thay đổi, lệnh test, kết quả và việc
còn thiếu.

Không: - Tạo file/module chỉ để bọc một dòng code mà không tăng giá
trị. - Dùng global mutable state cho conversation/trip. - Nuốt exception
rồi trả câu trả lời thành công. - Hardcode dữ liệu thật vào business
logic. - Hardcode API key. - Tạo nhiều agent con khi một graph/tool đơn
giản đã đủ. - Dùng LLM để tính toán route/time/budget thay cho
code/optimizer. - Để LLM tự khẳng định dữ liệu động không có nguồn.

------------------------------------------------------------------------

## 15. Hướng dẫn Claude Code bắt đầu

Thực hiện đúng thứ tự:

1.  Đọc toàn bộ hướng dẫn này.
2.  Inspect repository hiện tại: tree, README, dependency manifests, env
    example, migrations, source code và tests.
3.  Tóm tắt kiến trúc hiện có bằng sơ đồ text.
4.  Đánh dấu từng năng lực trong mục 2 là `implemented`, `partial`,
    `missing` hoặc `unknown`.
5.  Đề xuất roadmap phù hợp với codebase thật; chỉ rõ file sẽ tạo/sửa và
    lý do.
6.  Nêu các câu hỏi/blocker thực sự cần người dùng quyết định. Không hỏi
    những điều có thể xác định từ repository.
7.  Sau khi có plan, bắt đầu với phase nhỏ nhất có thể nghiệm thu. Nếu
    cần approval theo quy trình dự án, dừng ở plan và chờ.
8.  Trước khi kết thúc mỗi phase, chạy tests và báo cáo:
    -   Summary.
    -   Files changed.
    -   Architecture/decision notes.
    -   Commands executed.
    -   Test results.
    -   Known limitations.
    -   Next phase.

**Ưu tiên:** Một hệ thống hội thoại + travel workflow chạy end-to-end,
có dữ liệu và nguồn đáng tin cậy, tốt hơn một kiến trúc nhiều agent phức
tạp nhưng không chạy được.
