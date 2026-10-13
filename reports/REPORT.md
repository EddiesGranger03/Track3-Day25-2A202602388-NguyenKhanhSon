# Lab 25B — Report

**Họ tên / nhóm:** Nguyễn Khánh Sơn (MSV: 2A202602388)  **Commit:** `4cf5fec8f1ceb8da81d39adfe50a6bccd67fff57`  **Điểm tự động (`make grade`):** 84.0 / 88 (đạt tối đa điểm phần thi tự động công khai)

> Mọi nhận định dưới đây đều dựa trên số liệu thực nghiệm trích xuất từ `reports/gameday/*.json`, `reports/cache/*.json`, `reports/workflows.json`, `reports/slo.json` và file chuỗi thời gian CSV.

---

## 1. Kết quả Game Day (naive vs của bạn)

| Băng | Client | availability | p95 (s) | amplification | retry_ratio | cost/turn | recovery (s) | PASS? |
|---|---|---:|---:|---:|---:|---:|---:|:---:|
| G1 | naive | 0.7194 | 7.157 | 7.738 | 6.738 | 2.163 | 4.0 | FAIL |
| G1 | yours | 1.0000 | 4.776 | 1.062 | 0.002 | 2.101 | 0.0 | PASS |
| G2 | naive | 0.4560 | 15.034 | 9.904 | 8.904 | 4.627 | 155.0 | FAIL |
| G2 | yours | 1.0000 | 10.920 | 1.041 | 0.007 | 2.119 | 0.0 | PASS |
| G3 | naive | 1.0000 | 4.768 | 1.164 | 0.164 | 2.328 | 0.0 | FAIL |
| G3 | yours | 1.0000 | 4.660 | 1.060 | 0.034 | 2.145 | 0.0 | PASS |
| G4 | naive | 1.0000 | 13.764 | 1.004 | 0.004 | 2.008 | 0.0 | FAIL |
| G4 | yours | 1.0000 | 5.562 | 1.015 | 0.002 | 2.072 | 0.0 | PASS |
| G5 | naive | 0.3699 | 5.359 | 17.030 | 16.030 | 2.124 | None | FAIL |
| G5 | yours | 0.8179 | 5.477 | 1.003 | 0.002 | 2.504 | None | PASS |
| G6 | naive | 0.5170 | 4.836 | 12.344 | 11.344 | 2.009 | 0.0 | FAIL |
| G6 | yours | 1.0000 | 5.961 | 1.055 | 0.019 | 2.189 | 0.0 | PASS |

---

## 2. Cấu hình client và lý do

| Tham số | Giá trị | Vì sao (dựa trên băng nào, số liệu nào) |
|---|---:|---|
| `attempt_timeout_s` | 8.0 | Giới hạn thời gian chờ một attempt. Trong G6 và G2, nếu để timeout quá cao (như 30s), một request bị treo ở provider hỏng sẽ ngốn trọn deadline 30s của cả turn khiến không kịp failover. Giá trị 8.0s đủ lớn cho latency bình thường (~1.2 - 1.8s) nhưng đủ nhỏ để failover sang provider tiếp theo. |
| `max_attempts_per_provider` | 2 | Cho phép 1 lần retry trên cùng provider đối với lỗi tạm thời trước khi failover. Trong G1 và G2, hạn chế số lần retry giúp amplification duy trì ở mức 1.041 - 1.062 (thay vì 7.7 - 9.9 ở naive). |
| `backoff_base_s / cap_s` | 0.25 / 4.0 | Exponential backoff với full jitter. `base_s = 0.25s` giúp thử lại nhanh khi gặp trục trặc vi mô, và `cap_s = 4.0s` tránh retry dồn toa làm quá tải provider đang hồi phục. |
| `retry_budget_ratio` | 0.1 | Token bucket chỉ cho phép retries chiếm tối đa 10% lượng request mới. Ở G1, G2, G3, retry ratio thực tế được giữ ở mức 0.002 - 0.034, ngăn chặn hoàn toàn hiện tượng retry storm. |
| `breaker.window_size / min_calls` | 20 / 10 | Sliding window 20 calls với ngưỡng tối thiểu 10 calls. Tránh hiện tượng circuit breaker bị kích hoạt oan (false positive) do một vài lỗi ngẫu nhiên ban đêm lúc lưu lượng thấp. |
| `breaker.failure_rate_threshold` | 0.5 | Ngưỡng lỗi 50%. Khi provider trả về >= 50% lỗi (như G2, G6 khi sập hoàn toàn), breaker nhanh chóng chuyển sang trạng thái OPEN để cắt tải. |
| `breaker.slow_call_s` | 5.0 | Ngưỡng định nghĩa call chậm. Trong G4 (slow region), alpha chậm thêm 5s (bình thường 1.2s -> 6.2s). Ngưỡng 5.0s phát hiện chính xác tình trạng suy thoái hiệu năng trước khi gây timeout hàng loạt. |
| `breaker.open_duration_s` | 10.0 | Thời gian ngắt mạch 10s trước khi cho phép probe ở HALF_OPEN. Trong G2 và G6, 10s cho phép provider có thời gian giải tỏa hàng đợi nội bộ. |
| `breaker.half_open_max_probes` | 2 | Chỉ cho phép tối đa 2 request thăm dò đồng thời trong HALF_OPEN. Ngăn chặn hiện tượng thundering herd (đàn bò giẫm đạp) tái quá tải provider vừa mới ngóc dậy. |

### Sơ đồ quyết định của `on_error`

```
                                [Nhận ProviderError]
                                         │
                                [Phân loại ErrorKind]
                                         │
        ┌────────────────────────────────┴────────────────────────────────┐
        │                                                                 │
  [CLIENT_ERROR]                                            [Lỗi Provider / Hạ tầng]
  (400, 401, 403, 404, 422)                                               │
        │                                                                 │
  • Breaker: release()                                      ┌─────────────┴─────────────┐
  • Action: GiveUp("client_error")                          │                           │
  • Không bao giờ retry                               [QUOTA_EXHAUSTED]           [RATE_LIMITED]
  • Không bao giờ failover                                (429 quota)             (429 rps limit)
                                                            │                           │
                                                    • Breaker: release()        • Breaker: release()
                                                    • Cooldown: now + 300s      • Cooldown: now + retry_after
                                                    • Failover ngay lập tức     • Failover ngay lập tức
                                                            │                           │
                                                            └─────────────┬─────────────┘
                                                                          │
                                                      [OVERLOADED / SERVER_ERROR / TIMEOUT]
                                                      (529, 503, 500, 502, 0 client_timeout)
                                                                          │
                                                              • Breaker: on_failure()
                                                                          │
                                                         ┌────────────────┴────────────────┐
                                                         │                                 │
                                              [Thỏa mãn điều kiện retry?]         [Không thỏa mãn]
                                              - tries < max_attempts (2)                   │
                                              - budget.try_acquire_retry()                 │
                                              - fits deadline?                             │
                                                         │                                 │
                                                        YES                                NO
                                                         │                                 │
                                              • Gửi lại cùng provider             • Chuyển sang provider kế tiếp
                                                sau backoff.delay(tries)            trong ladder (failover ngay)
```

---

## 3. Ba thí nghiệm (mỗi cái 3–5 câu + số)

1. **Retry budget là lớp phòng thủ cuối:**
   - Khi giả lập breaker bị vô hiệu hóa (`min_calls = 1_000_000_000`) và cho phép retry nhiều lần (`max_attempts_per_provider = 5`):
     - Ở kịch bản **G2 (overload storm)**: Khi **có retry budget**, `amplification = 1.380`, `retry_ratio = 0.058`, `recovery_s = 0.0s`, `availability = 99.87%`. Khi **tắt budget**, `amplification = 1.675`, `retry_ratio = 0.495` (tăng gấp 8.5 lần), `recovery_s = 25.0s`, `availability = 96.66%`.
     - Ở kịch bản **G3 (brownout 30% lỗi 500)**: Khi có budget, `amplification = 1.136`, `retry_ratio = 0.068`. Khi tắt budget, `retry_ratio = 0.159` (tăng hơn gấp đôi).
   - *Kết luận cơ chế:* Khi breaker hoạt động đúng, nó cắt tải tập trung ở cấp độ provider khi tỷ lệ lỗi vượt ngưỡng. Tuy nhiên, retry budget vẫn tối quan trọng vì nó khống chế tổng lượng request tái sinh trên toàn hệ thống trong các đợt lỗi rải rác dưới ngưỡng breaker (như G3 brownout 30% < 50% threshold) hoặc trong thời gian breaker đang thu thập đủ `min_calls`. Cả hai cơ chế phối hợp tạo nên chiều sâu phòng thủ (defense-in-depth).

2. **`attempt_timeout_s: 30`:**
   - Khi tăng timeout attempt lên 30s bằng đúng turn deadline:
     - Ở **G4 (slow region)**: `availability = 1.0`, `p95 = 5.608s`, `amplification = 1.014` (nhờ slow call breaker phát hiện và chuyển mạch sang alpha-eu).
     - Ở **G6 (provider outage)**: `availability` tụt xuống **0.9488** (dưới ngưỡng yêu cầu 95%, FAIL check), với `give_up_reasons = {'deadline': 109, 'no_provider_available': 13}`.
   - *Nguyên nhân:* Khi provider chính sập hoặc treo hoàn toàn, attempt đầu tiên ngốn sạch 30s ngân sách của turn khiến client hết hạn deadline trước khi kịp chuyển vùng sang beta hoặc alpha-eu.
   - *Timeout đúng nên dựa vào đâu:* Timeout cho từng attempt phải dựa trên phân vị cao (p99 latency) trong trạng thái hoạt động bình thường của provider cộng thêm một biên độ an toàn nhỏ (thường 2x - 3x median latency, ~5s - 8s), và bắt buộc phải thỏa mãn: `(max_attempts * timeout) + failover_overhead < turn_deadline`.

3. **Bỏ lọc tool calling khỏi `ladder()`:**
   - Khi cho phép request cần tool calling gửi sang gamma-mini trong kịch bản **G6 (provider outage)**:
     - `availability` tụt mạnh xuống **0.9019** (90.19%), phát sinh `incompatible_routes = 234`, với `give_up_reasons = {'incompatible_model_output': 234}`.
   - *Góc nhìn Product Manager:* 
     "Việc định tuyến một tác vụ đòi hỏi khả năng thao tác nghiệp vụ (như kiểm tra trạng thái đơn và bấm nút hoàn tiền) sang một mô hình giá rẻ không hỗ trợ function calling (gamma-mini) khiến mô hình chỉ trả lời bằng văn bản chung chung mà không thực hiện được giao dịch. Hậu quả là 234 khách hàng (~9.8% lượt truy cập) nhận được câu trả lời vô nghĩa hoặc lỗi hệ thống, giao dịch hoàn tiền bị treo, gây sụt giảm nghiêm trọng điểm số hài lòng người dùng (CSAT) và trực tiếp gia tăng gánh nặng cho bộ phận hỗ trợ khách hàng."

---

## 4. Workflow hoàn tiền

| Executor | completion | crashes | duplicate refunds | duplicate emails | lost refunds | overpaid | wasted LLM / crash |
|---|---:|---:|---:|---:|---:|---:|---:|
| naive | 1.0 | 81 | 128 | 81 | 0 | 1,574,200 đ | 1.123 |
| yours | 1.0 | 66 | 0 | 0 | 0 | 0 đ | 0.303 |

**Vì sao chỉ idempotency key là chưa đủ, và chỉ checkpoint cũng chưa đủ?**
- *Chỉ có Idempotency key:* Nếu worker bị crash sau khi thanh toán thành công, worker mới khởi động lại từ đầu mà không có checkpoint sẽ phải chạy lại tất cả các bước trước đó (classify, lookup). Điều này làm lãng phí token LLM và thời gian xử lý (`wasted_llm_per_crash` sẽ rất cao). Hơn nữa, nếu worker crash liên tục, session có nguy cơ không bao giờ hoàn thành trước số lần restart tối đa.
- *Chỉ có Checkpoint:* Nếu worker gửi yêu cầu thanh toán sang ngân hàng, ngân hàng đã trừ tiền thành công nhưng phản hồi mạng bị mất (`ServiceTimeout`), worker sẽ retry bước đó. Nếu không có idempotency key ổn định, ngân hàng sẽ coi đây là giao dịch mới và trừ tiền lần 2, gây hoàn tiền trùng (duplicate refund) và thất thoát tài chính.
- *Nếu ghi checkpoint trước khi gọi payment:* Nếu worker ghi checkpoint "đã hoàn tiền" vào DB rồi mới gọi API thanh toán, nhưng worker bị crash ngay trước khi lệnh thanh toán kịp gửi đi, worker kế tiếp khi resume sẽ đọc thấy checkpoint và tin rằng bước này đã hoàn thành nên bỏ qua. Hậu quả là khách hàng không nhận được tiền nhưng hệ thống báo xong -> **Lost refund** (lỗi nghiêm trọng nhất). Do đó, nguyên tắc bất di bất dịch là: **Thực thi side-effect với Idempotency Key trước, lưu Checkpoint sau.**

---

## 5. Alerting & error budget

| Sự cố | Mong đợi | Naive alerter | Burn-rate alerter | Độ trễ phát hiện |
|---|---|---|---|---:|
| checkout_bug | page | page (phát hiện phút 1) | page | 27 phút |
| provider_outage | page | page (phát hiện phút 0) | page | 4 phút |
| deploy_blip | none | **page (false alarm)** | none (không page) | Không phát sinh |
| slow_leak | ticket | **không phát hiện (miss)** | ticket | 1337 phút (~22h) |
| degraded_evening | page | page (phát hiện phút 214) | page | 291 phút |
| night_spike | none | **page (false alarm)** | none (không page) | Không phát sinh |
| small_bump | none | **page (false alarm)** | none (không page) | Không phát sinh |

- **Error budget 30 ngày:**
  - Tổng số request: 25,901,755
  - Số request lỗi cho phép (SLO 99.5%): 129,508.8
  - Số request lỗi thực tế: 55,618
  - Availability đạt được: **99.7853%** (vượt chỉ tiêu SLO 99.5%)
  - Error budget đã tiêu: **42.95%**
  - Error budget còn lại: **57.05%**
  - Quyết định: **Không đóng băng release** (`freeze_releases = False`) vì ngân sách lỗi còn hơn 57%.
- **Vì sao `small_bump` (20 phút ở 12% lỗi) không nên đánh thức ai lúc 11 giờ trưa?**
  Mặc dù tỷ lệ lỗi 12% trong 20 phút nhìn có vẻ cao cục bộ, nhưng tổng số lỗi phát sinh trong 20 phút này chỉ tiêu tốn một phần rất nhỏ ngân sách lỗi của cả tháng (~0.05% error budget). Sự cố diễn ra ngắn và tự hết, hoàn toàn không đe dọa đến mục tiêu SLO 99.5% của tháng. Đánh thức kỹ sư on-call cho những sự cố thoáng qua gây ra hiện tượng "alert fatigue" (chai lì cảnh báo), làm suy giảm chất lượng ứng trực cho các sự cố thảm họa thực sự. Cơ chế multi-window burn rate (yêu cầu cả cửa sổ dài 1h và cửa sổ ngắn 5m cùng vượt ngưỡng 14.4x) đã lọc bỏ hoàn toàn các đợt sóng ngắn này.

---

## 6. Postmortem — Băng G2 với client naive (blameless)

*Hình ảnh phân tích: `reports/gameday/G2_overload_storm.png` và số liệu chuỗi thời gian từ `reports/gameday/naive_G2_overload_storm_timeseries.csv`.*

### Tóm tắt (3 câu)
Vào thời điểm t=120s, cụm máy chủ primary (alpha) chịu tổn thất 75% năng lực xử lý trong vòng 180 giây do sự cố hạ tầng GPU. Client phiên bản naive với cơ chế retry 3 tầng xếp chồng (36 lần thử/request), không có jitter, không có retry budget và không có circuit breaker đã kích hoạt một cơn bão retry storm dữ dội đạt đỉnh 254 attempts/s (gấp 14 lần mức tải thông thường). Sau khi năng lực của alpha được khôi phục hoàn toàn ở t=300s, hệ thống vẫn tiếp tục tê liệt thêm 155 giây do rơi vào trạng thái lỗi siêu bền (metastable failure), khiến độ khả dụng chung sụt giảm nghiêm trọng xuống còn 45.60%.

### Ảnh hưởng
- **1,285 lượt người dùng thất bại** (chỉ có 1,077 / 2,362 turns thành công, availability đạt 45.60%).
- Thời gian gián đoạn kéo dài **335 giây** (180s thời gian sự cố hạ tầng + 155s thời gian hệ thống tự kẹt cứng).
- Tiêu tốn **4,983 đơn vị chi phí** (chi phí trung bình 4.627 / good turn, gấp 2.2 lần bình thường).
- Nếu sự cố này xảy ra trên hệ thống thực tế quy mô tương tự trong tháng, riêng 1,285 lượt hỏng trong 5.5 phút này đã ngốn hơn **100% ngân sách lỗi** của nhiều ngày vận hành.

### Timeline (giây ảo — trích xuất chính xác từ CSV)

| t (giây) | Sự kiện | Bằng chứng định lượng từ CSV |
|---:|---|---|
| 0 – 119 | Vận hành bình thường | Lưu lượng ổn định ~7 - 10 attempts/s; `calls_ok` đạt 7 - 13 calls/s; 100% request xử lý thành công tại alpha. |
| 120 | Trigger: alpha mất 75% GPU | `calls_ok` sụt giảm đột ngột từ 7 calls/s xuống 2 calls/s tại t=121 và 0 calls/s tại t=122. |
| 136 | Bão retry bắt đầu bùng nổ | Tải dồn ứ khiến client timeout; số attempts gửi tới alpha tăng vọt lên 53 attempts/s; `calls_ok` chỉ đạt 3. |
| 143 | Đỉnh điểm bão retry (Retry storm peak) | Số attempts đạt đỉnh lịch sử **254 attempts/s**; `calls_ok = 0`. Hàng đợi của alpha tràn ngập 100% request lỗi (529/429). |
| 150 – 299 | Duy trì quá tải liên tục | Alpha liên tục bị dội 140 - 250 attempts/s; `calls_ok = 0`; 26,298 lỗi rate limit và 2,737 client timeouts tích lũy. |
| 300 | Hạ tầng phục hồi: alpha có lại 100% GPU | Năng lực phục hồi nhưng `calls_ok` tại t=300 vẫn bằng **0**; số attempts vẫn ở mức rất cao (115 attempts/s). |
| 301 – 454 | Vòng lặp lỗi siêu bền (Metastable failure) | Alpha xử lý các request tồn đọng trong hàng đợi nhưng client đã bỏ cuộc từ lâu (dead work); các client mới tiếp tục timeout và retry đẩy attempts lên lại 107 attempts/s ở t=363. `calls_ok` duy trì bằng 0 suốt 154 giây. |
| 455 | Hệ thống bắt đầu thoát khỏi metastable | Attempts giảm về dưới 15/s; hàng đợi xả hết; `calls_ok` hồi phục về 4 calls/s ở t=455 và 8 calls/s ở t=456 (`recovery_s = 155.0s`). |

### Trigger vs Root cause
- **Trigger (Ngòi nổ):** Cụm GPU của provider alpha bị mất 75% năng lực xử lý từ t=120s đến t=300s.
- **Root cause (Nguyên nhân gốc rễ):** Thiết kế kiến trúc client naive thiếu các cơ chế bảo vệ phân tán cơ bản:
  1. Retry xếp chồng 3 tầng không có exponential backoff và jitter khiến hàng loạt client dội request trùng lặp đồng thời.
  2. Không có **Retry Budget** để giới hạn tỷ lệ retry trên tổng lưu lượng.
  3. Không có **Circuit Breaker** để ngắt tải khỏi alpha và chuyển hướng (failover) sang `alpha-eu` hay `beta`.
- **Tại sao provider đã hồi phục ở t=300 mà hệ thống vẫn sập (Metastable Failure)?**
  Hàng đợi của alpha bị tắc nghẽn bởi hàng trăm request cũ mà phía client đã hết hạn chờ (user deadline 30s) và đã từ bỏ. Máy chủ vẫn tốn tài nguyên xử lý các "request thây ma" (wasted work), trong khi các request mới của người dùng vừa tới lại tiếp tục bị xếp sau hàng đợi thây ma, tiếp tục bị timeout và tiếp tục sinh thêm 36 attempts retry mới. Tải retry duy trì mức tiêu thụ tài nguyên lớn hơn nhiều so với năng lực phục vụ của máy chủ, tạo thành một **vòng lặp phản hồi dương (positive feedback loop)** tự duy trì ngay cả khi ngòi nổ ban đầu đã biến mất.

### Điều gì giúp / Điều gì làm tệ hơn
- **Làm tệ hơn:** Cơ chế timeout cố định 10s của provider giữ request trong hàng đợi quá lâu; client retry lặp lại ngay lập tức với delay cố định; 3 tầng retry nhân số lượng request lên gấp 36 lần.
- **Giúp hồi phục:** Simulator có giới hạn deadline 30s của user, đến một thời điểm các luồng request cũ bị drop triệt để kết hợp với lưu lượng Poisson ngẫu nhiên có khoảnh khắc chùng xuống nhẹ ở t=440s giúp hàng đợi xả cạn.

### Action items

| # | Hành động | Loại | Owner | Cách kiểm chứng |
|---|---|---|---|---|
| 1 | Triển khai `ResilientClient` với Circuit Breaker (sliding window), Retry Budget (ratio 0.1) và Full Jitter Backoff. | Prevent | Reliability Team | Chạy CI test tape G2 đạt `amplification <= 1.2` và `recovery_s = 0s`. |
| 2 | Cấu hình Failover Ladder tự động định tuyến sang `alpha-eu` và `beta` khi alpha gặp suy thoái sức khỏe hoặc ngắt mạch. | Mitigate | SRE Team | Kiểm tra tỷ lệ chia tải đạt >= 80% traffic chuyển hướng thành công khi primary lỗi. |
| 3 | Thiết lập hệ thống giám sát Multi-window Multi-burn-rate alerting theo chuẩn Google SRE. | Detect | Monitoring Team | Test trên dữ liệu 30 ngày cảnh báo chính xác sự cố nghiêm trọng trong vòng < 30 phút, 0 false alarm. |

---

## 7. Một điểm yếu còn lại

**Tình huống client vẫn xử lý kém:**
Khi provider chính `alpha` bị sự cố kéo dài và hệ thống phải chuyển tải sang `beta` (như trong kịch bản G6 hoặc G2), chi phí vận hành trên mỗi lượt (`cost/turn`) bị đội lên đáng kể từ 2.0 lên tới 2.504 - 2.189 đơn vị, do giá của model B-large trên `beta` đắt hơn 40% so với A-large trên `alpha` (1.4 vs 1.0). Ngoài ra, nếu `beta` cũng bị hạ rate limit (như ở G6), client có nguy cơ làm nghẽn luôn cả `beta`.

**Hướng cải tiến:**
1. **Load Shedding / Graceful Degradation theo độ ưu tiên:** Đối với các tác vụ chat đơn giản không cần suy luận phức tạp, ưu tiên failover sang `gamma-mini` (chi phí chỉ 0.2, rẻ hơn 7 lần) thay vì ép toàn bộ sang `beta`.
2. **Dynamic Cost-aware Routing:** Tích hợp trọng số chi phí và hạn ngạch tài chính vào thuật toán định tuyến; khi phát hiện chi phí trung bình vượt ngưỡng ngân sách cho phép, chủ động áp dụng giới hạn tần suất (rate limiting) cục bộ cho các tác vụ thứ yếu.
3. **Turn-level Deadline Partitioning:** Phân bổ ngân sách thời gian linh hoạt giữa các bước thay vì gán cứng timeout cho từng attempt đơn lẻ.

---

## 8. Cache (Part G)

*Số liệu thực nghiệm từ `reports/cache/*.json` khi chạy kịch bản C1:*

| Client | availability | faq_availability | cache_hit_ratio | stale_served | wrong_answers | outdated_answers | cost/turn | PASS? |
|---|---:|---:|---:|---:|---:|---:|---:|:---:|
| resilient (không cache) | 0.8373 | 0.8424 | 0.000 | 0 | 0 | 0 | 1.386 | FAIL |
| cached (của bạn) | **0.9117** | **0.9640** | **0.634** | **173** | **0** | **6** | **0.927** | **PASS** |

| Tham số `cache:` | Giá trị | Vì sao (số liệu nào) |
|---|---:|---|
| `similarity_threshold` | 0.90 | Ngưỡng 0.80 quá lỏng gây ra 138 - 181 câu trả lời sai (`other_question`). Ngưỡng 0.90 triệt tiêu hoàn toàn lỗi sai (`wrong_answers = 0`) mà vẫn duy trì tỷ lệ cache hit cao (63.4%). |
| `ttl_s` | 45 | Giữ độ tươi mới cho dữ liệu. Khi có thay đổi tài liệu không báo trước (t=480 bảng phí ship), TTL 45s đảm bảo câu trả lời cũ tự hết hạn nhanh, giữ `outdated_answers = 6` (thỏa mãn chỉ tiêu <= 15). |
| `max_stale_s` | 200 | Cửa sổ cho phép phục vụ câu trả lời cũ khi mọi provider sập (stale-if-error). Trong đợt outage 120s (t=240-360), cache đã phục vụ 173 câu stale giúp `faq_availability` đạt 96.4% (thay vì tụt xuống 86.3% nếu để max_stale=0). |

### Thí nghiệm

1. **Ngưỡng tương đồng cosine:**
   - Với `similarity_threshold = 0.80`: `hit_ratio = 0.647`, `wrong_answers = 138` (`wrong_answers_by_reason = {'other_question': 138}`), `cost/turn = 0.972`. Các câu hỏi có ngữ cảnh khác nhau nhưng chứa từ khóa tương đồng (ví dụ: "chính sách hoàn tiền" vs "thời hạn hoàn tiền", hoặc "đổi size áo" vs "đổi địa chỉ giao hàng") bị map nhầm vào cùng một cache entry, trả về nội dung sai lệch cho khách hàng.
   - Với `similarity_threshold = 0.90`: `hit_ratio = 0.634`, `wrong_answers = 0`, `cost/turn = 0.927`.
   - Với `similarity_threshold = 0.97`: `hit_ratio = 0.552`, `wrong_answers = 0`, `cost/turn = 0.984`. Ngưỡng quá chặt khiến các câu diễn đạt lại (paraphrase) tự nhiên của người dùng bị cache miss, làm tăng chi phí gọi LLM thêm 6.1%.
2. **TTL:**
   - Khi chạy với `ttl_s = 30`: `outdated_answers = 2`, `hit_ratio = 0.592`.
   - Khi chạy với `ttl_s = 60`: `outdated_answers = 3`, `hit_ratio = 0.652`.
   - Khi chạy với `ttl_s = 300`: `outdated_answers = 95` (vượt xa trần cho phép 15), `hit_ratio = 0.731`.
   - *Vì sao webhook không giúp được:* Webhook chỉ kích hoạt khi hệ thống CMS gửi sự kiện thông báo (như đổi chính sách hoàn tiền ở t=150). Nhưng đối với các thay đổi ngoài dự kiến hoặc không phát sự kiện (như bảng phí vận chuyển đổi âm thầm ở t=480), cache không nhận được tín hiệu invalidate. Do đó, TTL chính là cơ chế bảo vệ chủ động duy nhất để loại bỏ dữ liệu lỗi thời khi thiếu vắng webhook.
3. **Stale-if-error:**
   - Khi đặt `max_stale_s: 0`: `faq_availability` sụt từ 96.40% xuống còn **86.34%** (không đạt yêu cầu >= 93%), và `stale_served = 0`.
   - Khi có `max_stale_s: 200`: Trong khoảng t=240 - 360 khi toàn bộ nhà cung cấp LLM ngừng hoạt động, hệ thống đã tận dụng thành công các bản ghi trong bộ nhớ đệm để phục vụ 173 lượt truy vấn FAQ, duy trì trải nghiệm liền mạch cho phần lớn người dùng.

### Trả lời câu hỏi tư duy

- **Vì sao câu hỏi cá nhân ("Đơn #48213 của tôi đang ở đâu?") không được cache, kể cả khi cache theo từng user?**
  1. *Rủi ro rò rỉ dữ liệu cá nhân (PII / Privacy Leakage):* Câu hỏi cá nhân gắn liền với thông tin nhạy cảm của khách hàng (địa chỉ, số điện thoại, giá trị đơn hàng, tài khoản ngân hàng). Bất kỳ sơ suất nào trong việc mapping user identity đều có thể làm lộ dữ liệu của người này cho người khác xem.
  2. *Dữ liệu mang tính thời điểm cao (High Volatility):* Trạng thái đơn hàng, số dư điểm thưởng thay đổi liên tục theo thời gian thực (đang đóng gói -> đang giao -> đã giao). Cache câu trả lời cá nhân sẽ dẫn đến việc trả lời thông tin cũ sai lệch gây bức xúc cho khách hàng, trong khi tỷ lệ tái sử dụng (cache hit) của cùng một câu hỏi cá nhân là cực kỳ thấp.
- **Trong lúc mọi provider sập, dashboard vẫn xanh nhờ cache. Bạn sẽ alert dựa trên số nào để on-call vẫn biết có sự cố?**
  Không được chỉ nhìn vào `overall availability` ở tầng biên (edge availability). Cần phải thiết lập metric và alert chuyên biệt dựa trên:
  1. **Tỷ lệ phục vụ dữ liệu cũ (`stale_served_ratio` hoặc `stale_answers_per_min`):** Khi chỉ số này vượt quá ngưỡng bình thường (vd > 5% lượng FAQ), kích hoạt alert ngay lập tức vì điều này chứng tỏ backend LLM đang bất lực trong việc tạo câu trả lời mới và hệ thống đang phải dùng phao cứu sinh stale.
  2. **Tỷ lệ lỗi tại tầng Provider (`provider_error_ratio` hoặc `upstream_5xx_rate`):** Giám sát trực tiếp mã lỗi (503, 529, timeout) và trạng thái mở mạch của Circuit Breaker (`breaker_state == OPEN`) ở tầng kết nối upstream tới nhà cung cấp LLM.
