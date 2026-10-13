# Lab 25B — Report

**Họ tên / nhóm:** Nguyễn Khánh Sơn (MSV: 2A202602388)  **Mã được kiểm thử:** commit gốc `76138b4` + các thay đổi chưa commit.  **Điểm tự động công khai:** 84.0 / 88; 4 điểm SLO trên dữ liệu ẩn do giảng viên chấm.

> Các bảng chính dùng scenario seed 25 và factory client seed 1, được tái tạo từ working tree đã sửa. Nguồn: `reports/gameday/*.json`, `reports/cache/*.json`, `reports/workflows.json`, `reports/slo.json`, CSV, `reports/review_experiments.json`, `reports/cache_validation.json` và `reports/scoreboard.json`. Thí nghiệm chỉ đổi tham số trong bộ nhớ; không sửa simulator hoặc băng sự cố.

---

## 1. Kết quả Game Day (naive vs của bạn)

| Băng | Client | availability | p95 (s) | amplification | retry_ratio | cost/good turn | recovery (s) | PASS? |
|---|---|---:|---:|---:|---:|---:|---:|:---:|
| G1 | naive | 0.7194 | 7.157 | 7.738 | 6.738 | 2.163 | 4.0 | FAIL |
| G1 | yours | 1.0000 | 4.780 | 1.063 | 0.001 | 2.104 | 0.0 | PASS |
| G2 | naive | 0.4560 | 15.034 | 9.904 | 8.904 | 4.627 | 155.0 | FAIL |
| G2 | yours | 1.0000 | 10.362 | 1.037 | 0.005 | 2.112 | 0.0 | PASS |
| G3 | naive | 1.0000 | 4.768 | 1.164 | 0.164 | 2.328 | 0.0 | FAIL |
| G3 | yours | 1.0000 | 4.569 | 1.083 | 0.049 | 2.177 | 0.0 | PASS |
| G4 | naive | 1.0000 | 13.764 | 1.004 | 0.004 | 2.008 | 0.0 | FAIL |
| G4 | yours | 1.0000 | 5.626 | 1.014 | 0.002 | 2.072 | 0.0 | PASS |
| G5 | naive | 0.3699 | 5.359 | 17.030 | 16.030 | 2.124 | — | FAIL |
| G5 | yours | 0.8179 | 5.477 | 1.003 | 0.002 | 2.504 | — | PASS |
| G6 | naive | 0.5170 | 4.836 | 12.344 | 11.344 | 2.009 | 0.0 | FAIL |
| G6 | yours | 1.0000 | 5.961 | 1.055 | 0.018 | 2.196 | 0.0 | PASS |

`availability` đo lượt user; `p95` chỉ tính lượt thành công. `recovery_s` là thời gian đến đầu cửa sổ 30s có ≥ 95% logical call hoàn tất thành công, không phải thời gian đến call thành công đầu tiên. G1–G6 của resilient đều PASS trên 7 seed trong mục 9.

---

## 2. Cấu hình client và lý do

| Tham số | Giá trị | Vì sao (dựa trên băng và số liệu) |
|---|---:|---|
| `attempt_timeout_s` | 8.0 | G6 đạt availability 1.0000; tăng timeout lên 30s làm giảm còn 0.9488. Mỗi Send còn được giới hạn bởi thời gian còn lại đến deadline, tránh attempt vượt ngân sách của turn. |
| `max_attempts_per_provider` | 2 | Cho phép một retry thông thường trên provider khi lỗi transient và budget cho phép. Với các cơ chế bảo vệ cùng hoạt động, G1/G2 amplification là 1.063/1.037, so với naive 7.738/9.904. |
| `min_time_left_s` | 1.0 | Không đặt attempt nếu thời gian chờ còn lại dưới 1s. Các regression kiểm tra timeout bị giới hạn theo deadline và permit được trả lại khi không thể gửi. |
| `backoff_base_s / cap_s` | 0.25 / 4.0 | Full jitter phân tán retry; backoff có `retry_after` luôn chờ ít nhất giá trị header. G1 có 0 vi phạm `retry-after`; đây là kết quả của cả backoff và cooldown chung theo provider. |
| `retry_budget_ratio / min_per_s / max_tokens` | 0.1 / 0.5 / 20 | Request mới nạp 0.1 token, bucket bổ sung 0.5 token/s và chứa tối đa 20 token. Do có refill theo thời gian, 0.1 không phải trần cứng 10% trong mọi cửa sổ. G3 retry_ratio = 0.049; lần gửi lại provider sau cooldown cũng phải tiêu token, còn provider mới trong ladder chưa tính là retry. |
| `quota_cooldown_s` | 300 | Hết quota không làm trip breaker nhưng provider được nghỉ 300s. G5 có 0 retry lỗi client, 0 failover không cần thiết và availability 0.8179. |
| `breaker.window_size / min_calls` | 20 / 10 | Chỉ đánh giá sau ít nhất 10 kết quả, trong 20 kết quả gần nhất; tránh trip từ một lỗi đơn lẻ. G2 có amplification 1.037 và recovery 0s; mục 3 kiểm tra vai trò của budget khi breaker không trip. |
| `breaker.failure_rate_threshold` | 0.5 | Trip khi ≥ 50% kết quả thuộc lỗi sức khỏe provider. Lỗi 400, quota và rate limit không tính vào tỷ lệ này; G5 không bị retry/failover sai vì malformed request. |
| `breaker.slow_call_s / slow_rate_threshold` | 5.0 / 0.6 | Thành công nhưng ≥ 5s vẫn được ghi là chậm; tỷ lệ chậm ≥ 60% làm trip. G4 p95 giảm từ 13.764s ở naive xuống 5.626s. |
| `breaker.open_duration_s` | 10.0 | Cho phép probe sau 10s OPEN, thay vì tiếp tục gửi tải bình thường. G2 recovery = 0s và `primary_share_after_restore = 1.0`; không đo trực tiếp thời điểm hàng đợi xả hết. |
| `breaker.half_open_max_probes / successes` | 2 / 2 | Tối đa 2 probe đang bay; 2 probe tốt đóng breaker. Permit cũ bị bỏ qua và probe bị hủy được giải phóng; unit test breaker và regression client kiểm tra các điều kiện này. |

### Quyết định của `on_error`

| Loại lỗi | Ghi vào breaker | Retry / failover / cooldown |
|---|---|---|
| Client error (400/401/403/404/422) | Release permit, không ghi lỗi sức khỏe | GiveUp; không retry và không failover. |
| Quota exhausted | Release permit | Cooldown provider 300s, chuyển provider kế tiếp ngay. |
| Rate limited | Release permit | Cooldown chung đến `now + retry_after`, chuyển provider kế tiếp ngay. |
| Overloaded / server error / timeout | Ghi failure | Retry cùng provider nếu còn attempts, permit, token budget và đủ deadline; nếu không thì chuyển provider kế tiếp. |
| Tất cả provider không dùng được | Không tự tạo lỗi sức khỏe | Có thể chờ cooldown rate limit ngắn ≤ 5s nếu đủ deadline; provider đã thử vẫn phải qua retry budget. Nếu không có đường hợp lệ thì GiveUp. |

Mọi đường tạo Send đều đi qua kiểm tra permit, timeout/deadline và budget. HALF-OPEN permit không bị giữ lại khi budget hoặc deadline từ chối Send.

---

## 3. Ba thí nghiệm

Các kết quả dưới đây được chạy lại với code đã sửa, scenario seed 25 và factory client seed 1. Tham số đầy đủ và JSON kết quả nằm trong `reports/review_experiments.json`.

### 1. Retry budget là lớp phòng thủ cuối

Để tách ảnh hưởng của budget, cả hai biến thể đổi `breaker.min_calls` từ **10 → 1,000,000,000** và `max_attempts_per_provider` từ **2 → 5**. Biến thể có budget giữ ratio/refill/cap = **0.1 / 0.5 / 20**; biến thể coi như tắt budget dùng giá trị hữu hạn rất lớn **100 / 1,000,000 / 1,000,000,000**, không dùng vô cực.

| Băng | Budget | availability | amplification | retry_ratio | recovery (s) |
|---|---|---:|---:|---:|---:|
| G2 | Có | 0.9983 | 1.378 | 0.058 | 0.0 |
| G2 | Gần như tắt | 0.9754 | 1.580 | 0.378 | 24.0 |
| G3 | Có | 1.0000 | 1.136 | 0.068 | 0.0 |
| G3 | Gần như tắt | 1.0000 | 1.162 | 0.158 | 0.0 |

Ở G2, bỏ giới hạn budget làm retry_ratio tăng khoảng **6.5 lần**, recovery từ 0 lên 24s; cả hai vẫn PASS public G2 tại seed này. Ở G3, biến thể gần như tắt budget FAIL vì retry_ratio 0.158 vượt 0.10. Cấu hình mặc định (`breaker.min_calls = 10`, `max_attempts_per_provider = 2`) đạt G2 amplification 1.037 và G3 retry_ratio 0.049; breaker cắt tải khi provider vượt ngưỡng sức khỏe, còn budget kiểm soát lỗi rải rác dưới ngưỡng hoặc trong giai đoạn chưa đủ `min_calls`.

### 2. `attempt_timeout_s: 30`

| Băng | Timeout cấu hình | availability | p95 của lượt thành công (s) | amplification |
|---|---:|---:|---:|---:|
| G4 | 8s, mặc định | 1.0000 | 5.626 | 1.014 |
| G4 | 30s | 1.0000 | 5.608 | 1.014 |
| G6 | 8s, mặc định | 1.0000 | 5.961 | 1.055 |
| G6 | 30s | 0.9488 | 5.440 | 1.035 |

G4 vẫn được slow-call breaker bảo vệ, nhưng G6 FAIL availability với **107 GiveUp deadline** và **15 GiveUp no_provider_available**. Attempt ở provider treo được giới hạn theo deadline còn lại, song timeout cấu hình 30s vẫn có thể dùng hết thời gian để failover; p95 G6 giảm không chứng minh trải nghiệm tốt hơn vì 5.12% lượt thất bại bị loại khỏi metric này. Timeout nên dựa trên phân vị latency khỏe mạnh, đủ chỗ cho bước tiếp theo và failover, thay vì dùng trọn deadline 30s của turn; trước mỗi Send phải kiểm tra lại deadline thực tế.

### 3. Bỏ lọc tool calling khỏi `ladder()`

Thí nghiệm thay `client.ladder` trên instance để trả toàn bộ `client.order` cho cả tool và chat; không sửa file nguồn hoặc simulator. G6 availability giảm từ **1.0000 xuống 0.8922**, phát sinh **257 incompatible routes** và `give_up_reasons = {'incompatible_model_output': 257}`. Với góc nhìn sản phẩm, khoảng **10.78% của 2,385 lượt** thất bại vì bước nghiệp vụ được gửi sang model không hỗ trợ tool calling; trả lời văn bản không thay thế được thao tác nghiệp vụ. Đây là thiệt hại đo được trong mô phỏng; thí nghiệm không đo CSAT hay số ticket hỗ trợ ngoài thực tế.

---

## 4. Workflow hoàn tiền

| Executor | completion | crashes | duplicate refunds | duplicate emails | lost refunds | `overpaid_cents` (đơn vị mô phỏng) | wasted LLM / crash |
|---|---:|---:|---:|---:|---:|---:|---:|
| naive | 1.0 | 81 | 128 | 81 | 0 | 1,574,200 | 1.123 |
| yours | 1.0 | 66 | 0 | 0 | 0 | 0 | 0.303 |

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
  Trong 20 phút này, CSV ghi nhận **1,794 request lỗi / 15,211 request**, tương đương **1.385% ngân sách lỗi tháng** (`1,794 / 129,508.775 × 100`). Sự cố tự hết và không đạt đồng thời các điều kiện page của luật burn-rate đa cửa sổ; alerter không phát page, còn naive alerter phát false page. Đây là cách cân bằng tốc độ phát hiện với mức tiêu hao ngân sách lỗi, giảm số lần đánh thức on-call cho các đợt lỗi ngắn.

---

## 6. Postmortem — Băng G2 với client naive (blameless)

*Hình ảnh phân tích: `reports/gameday/G2_overload_storm.png` và số liệu chuỗi thời gian từ `reports/gameday/naive_G2_overload_storm_timeseries.csv`.*

### Tóm tắt (3 câu)
Vào thời điểm t=120s, alpha mất 75% năng lực xử lý trong 180 giây theo cấu hình băng G2. Client naive retry 3 tầng xếp chồng, tối đa 36 attempts/call, không có jitter, retry budget hay circuit breaker; tải đạt đỉnh **254 attempts/s tại t=143**. Alpha khôi phục năng lực ở t=300 nhưng cửa sổ 30 giây đạt tỷ lệ call thành công ≥ 95% chỉ bắt đầu tại t=455 (`recovery_s = 155`); availability toàn băng là **45.60%**.

### Ảnh hưởng
- **1,285 lượt người dùng thất bại** (chỉ có 1,077 / 2,362 turns thành công, availability đạt 45.60%).
- Từ lúc trigger t=120 đến đầu cửa sổ phục hồi t=455 là **335 giây**; đây không phải 335 giây mất toàn bộ call thành công liên tục.
- JSON ghi nhận tổng chi phí **4,983 đơn vị mô phỏng**, tức **4.627 / good turn** (`4,983 / 1,077`). So với mức tối thiểu 2 đơn vị cho hai call alpha thành công, chi phí trên good turn cao gấp **2.313 lần**.
- Nếu SLI tháng đo **lượt user thành công**, lưu lượng cố định **4 turns/s** trong **30 ngày** và SLO **99.5%**, ngân sách lỗi là `4 × 30 × 24 × 3,600 × 0.005 = 51,840` lượt. Khi tháng chỉ có sự cố này, **1,285 lượt hỏng tiêu 2.479% ngân sách tháng**. Phép tính này dùng turn SLI, tách biệt với request SLI trong dữ liệu alerting mục 5.

### Timeline (giây ảo — trích xuất chính xác từ CSV)

| t (giây) | Sự kiện | Bằng chứng định lượng từ CSV |
|---:|---|---|
| 0 – 119 | Trước sự cố | Alpha nhận 1 – 16 attempts/s, trung bình 7.542; `calls_ok` từ 1 – 15/s. CSV ghi nhận 895/895 logical call hoàn tất thành công trong khoảng này; metric này không khẳng định mọi physical attempt đều thành công. |
| 120 | Trigger: alpha mất 75% GPU | `calls_ok` sụt giảm đột ngột từ 7 calls/s xuống 2 calls/s tại t=121 và 0 calls/s tại t=122. |
| 136 | Bão retry bắt đầu bùng nổ | Tải dồn ứ khiến client timeout; số attempts gửi tới alpha tăng vọt lên 53 attempts/s; `calls_ok` chỉ đạt 3. |
| 143 | Đỉnh tải retry | Alpha nhận **254 attempts/s**; `calls_ok = 0`, `calls_done = 0`. CSV không phân loại lỗi theo từng giây. |
| 150 – 299 | Duy trì tải cao | Alpha nhận **80 – 203 attempts/s**, trung bình 146.527; 0/631 logical call hoàn tất thành công. JSON toàn băng ghi nhận 26,298 lỗi rate limit và 2,737 client timeouts; không quy hai tổng này riêng cho khoảng 150 – 299. |
| 300 | Hạ tầng phục hồi: alpha có lại 100% GPU | Năng lực phục hồi nhưng `calls_ok` tại t=300 vẫn bằng **0**; số attempts vẫn ở mức rất cao (115 attempts/s). |
| 301 – 452 | Năng lực đã phục hồi nhưng logical call chưa thành công | CSV ghi nhận 0/534 logical call hoàn tất thành công trong 152 giây; riêng t=363 vẫn có 107 attempts/s. |
| 453 – 454 | Call thành công bắt đầu trở lại | `calls_ok = 4/s` ở cả t=453 và t=454; `calls_done` lần lượt là 8 và 7. Cửa sổ [454, 484) chỉ đạt 342/361 = 94.737%, chưa thỏa tiêu chí phục hồi. |
| 455 | Đầu cửa sổ đạt tiêu chí phục hồi | Có 13 attempts và 4/5 call thành công tại t=455; cửa sổ **[455, 485)** đạt **352/368 = 95.652%**, nên `recovery_s = 455 − 300 = 155`. CSV không trực tiếp chứng minh hàng đợi đã xả hết. |

### Trigger vs Root cause
- **Trigger (Ngòi nổ):** Cụm GPU của provider alpha bị mất 75% năng lực xử lý từ t=120s đến t=300s.
- **Root cause (Nguyên nhân gốc rễ):** Thiết kế kiến trúc client naive thiếu các cơ chế bảo vệ phân tán cơ bản:
  1. Retry xếp chồng 3 tầng không có exponential backoff và jitter khiến hàng loạt client dội request trùng lặp đồng thời.
  2. Không có **Retry Budget** để giới hạn tỷ lệ retry trên tổng lưu lượng.
  3. Không có **Circuit Breaker** để ngắt tải khỏi alpha và chuyển hướng (failover) sang `alpha-eu` hay `beta`.
- **Tại sao provider đã hồi phục ở t=300 mà hệ thống vẫn sập (Metastable Failure)?**
  Theo contract của simulator, server vẫn xử lý request khi client timeout; những request này tiếp tục chiếm năng lực trong khi client gửi thêm retry. Request mới phải chờ lâu hơn, lại timeout hoặc gặp 529/429, và naive client tiếp tục retry với delay cố định, tạo vòng lặp **timeout/lỗi → retry → thêm tải → timeout/lỗi**. CSV xác nhận tải retry cao và tỷ lệ call thành công thấp sau t=300, nhưng không có cột độ dài hàng đợi để xác định chính xác số request còn tồn đọng tại từng thời điểm; giới hạn 36 là số attempts tối đa/call, không phải mọi lỗi đều sinh thêm đúng 36 attempts.

### Điều gì giúp / Điều gì làm tệ hơn
- **Làm tệ hơn:** Client naive chờ tối đa 8s/attempt rồi retry sau delay cố định 0.2s, không tôn trọng `retry-after` và có tối đa 36 attempts/call. Giới hạn chờ hàng đợi 10s của provider là ngưỡng trả 529, không phải timeout cố định của client.
- **Giới hạn tác động / điều quan sát được:** Deadline 30s chặn các attempt được gửi sau khi user hết thời gian chờ. CSV cho thấy 11 attempts ở t=440, rồi call thành công trở lại tại t=453; không đủ bằng chứng để quy nguyên nhân hồi phục cho một lần giảm lưu lượng hoặc kết luận hàng đợi xả cạn tại t=440.

### Action items

| # | Hành động | Loại | Owner | Cách kiểm chứng |
|---|---|---|---|---|
| 1 | Triển khai `ResilientClient` với Circuit Breaker, Retry Budget (ratio 0.1) và Full Jitter Backoff. | Prevent | Reliability Team | Chạy G2 qua nhiều seed: availability ≥ 95%, amplification ≤ 1.6, recovery ≤ 30s. |
| 2 | Failover sang deployment tương thích khi alpha suy thoái; đưa traffic về primary khi phục hồi. | Mitigate | SRE Team | G2 có `primary_share_after_restore ≥ 0.8`; G6 có `incompatible_routes = 0` và availability ≥ 95%. |
| 3 | Giám sát burn-rate đa cửa sổ và kiểm thử các biên thiếu dữ liệu/lưu lượng thấp. | Detect | Monitoring Team | Mọi sự cố page/ticket trong dữ liệu 30 ngày được phát hiện trước `max_delay_min` của nhãn, 0 false page trên các blip. |

---

## 7. Một điểm yếu còn lại

G2 vẫn có **p95 = 10.362s**, dù availability 100% và recovery 0s: breaker chỉ phản ứng sau khi đã nhận đủ kết quả lỗi/chậm, nên một số lượt còn phải chờ alpha trước khi chuyển provider. Chi phí trên good turn cũng tăng từ mức tối thiểu 2 đơn vị lên **2.196 ở G6**, nơi beta nhận 2,124 attempts với giá 1.4/call; **2.504 là số của G5**, không phải G2/G6. Các số này phản ánh kết quả toàn băng, không chứng minh mọi chi phí tăng đều do beta.

Hướng cải tiến là phân bổ deadline theo bước để dành chỗ cho failover và giảm chờ ở provider đang chậm. Có thể ưu tiên `gamma-mini` cho chat đủ điều kiện để giảm chi phí, nhưng tool vẫn phải lọc theo khả năng; cần đo lại availability, latency và cost trên nhiều seed trước khi thay đổi thứ tự ladder. Tình huống mọi provider cùng chậm hoặc có outage dài hơn cửa sổ stale vẫn có thể làm giảm availability; kiểm thử public hiện tại chưa chứng minh client chịu được mọi dạng sự cố.

---

## 8. Cache (Part G)

Bảng C1 dùng config cuối: similarity 0.90, TTL 30s, max stale 200s, tối đa 500 entries; scenario seed 25, factory client seed 1.

| Client | availability | faq_availability | cache_hit_ratio | stale_served | wrong_answers | outdated_answers | cost/good turn | PASS? |
|---|---:|---:|---:|---:|---:|---:|---:|:---:|
| resilient (không cache) | 0.8373 | 0.8424 | 0.000 | 0 | 0 | 0 | 1.386 | FAIL |
| cached (của bạn) | **0.9120** | **0.9640** | **0.592** | **191** | **0** | **2** | **0.956** | **PASS** |

| Tham số `cache:` | Giá trị | Vì sao |
|---|---:|---|
| `similarity_threshold` | 0.90 | Ở TTL 30s, threshold 0.80 gây 181 lỗi `other_question`; 0.90 có 0 câu sai và hit 59.2%. Threshold 0.97 chỉ đạt hit 49.9%, thấp hơn yêu cầu 50%. |
| `ttl_s` | 30 | Seed 25 chỉ có 2 câu outdated. Quan trọng hơn, kiểm tra 100 seed đạt tối đa 14 câu outdated ≤ 15; chọn TTL từ nhiều seed thay vì chỉ nhìn seed 25. |
| `max_stale_s` | 200 | Cửa sổ stale sau TTL hỗ trợ outage 120s; FAQ availability 96.40%, 191 câu stale. Bỏ stale làm FAQ availability còn 85.29%. |
| `max_entries` | 500 | Dung lượng hữu hạn, evict LRU; unit test kiểm tra không vượt giới hạn và entry ít được dùng nhất bị loại. Không suy ra 500 là dung lượng tối ưu cho traffic production. |

### Thí nghiệm ngưỡng cosine

Giữ TTL 30s và max stale 200s, chỉ đổi similarity threshold:

| Threshold | cache_hit_ratio | wrong_answers | cost/good turn | C1 |
|---:|---:|---:|---:|:---:|
| 0.80 | 0.610 | 181 (`other_question`) | 1.016 | FAIL |
| 0.90 | 0.592 | 0 | 0.956 | PASS |
| 0.97 | 0.499 | 0 | 1.018 | FAIL |

Catalog có các cặp gần nhau nhưng khác ý định, như chính sách hoàn tiền/thời gian nhận tiền và phí ship nội thành/ngoại tỉnh. Metric `other_question` xác nhận trả nhầm ý định, nhưng JSON tổng hợp không xác định từng câu cụ thể trong 181 lần sai. Ngưỡng 0.97 tránh false hit song bỏ lỡ nhiều paraphrase, tăng cost/good turn khoảng **6.5%** so với 0.90 và không đạt yêu cầu hit ratio.

### Thí nghiệm TTL

Giữ similarity 0.90 và max stale 200s:

| TTL (s) | outdated_answers | cache_hit_ratio | cost/good turn | C1 seed 25 |
|---:|---:|---:|---:|:---:|
| 30 | 2 | 0.592 | 0.956 | PASS |
| 45 | 6 | 0.634 | 0.927 | PASS |
| 60 | 3 | 0.652 | 0.916 | PASS |
| 300 | 95 | 0.731 | 0.863 | FAIL |

Webhook invalidate các answer dựa trên tài liệu được thông báo thay đổi ở t=150; thay đổi shipping âm thầm ở t=480 không có webhook, nên thời gian sống cache là giới hạn chính cho dữ liệu cũ. Số outdated của một seed không tăng đơn điệu theo TTL vì thời điểm refresh thay đổi; TTL 45 PASS seed 25 nhưng FAIL các regression seed 3/4/58/85, còn TTL 30 PASS cả 100 seed. TTL giới hạn thời gian tươi, nhưng stale-if-error vẫn có thể giữ nội dung quá TTL trong cửa sổ stale; vì vậy không coi TTL 30 là bảo đảm tuyệt đối cho mọi thay đổi âm thầm xảy ra trong outage.

### Thí nghiệm stale-if-error

Với max stale **0**, FAQ availability giảm từ **0.9640 xuống 0.8529**, hit ratio từ **0.592 xuống 0.481**, và stale_served = 0; C1 FAIL. Với max stale **200s**, cache phục vụ **191 lượt stale** sau khi provider bỏ cuộc và C1 PASS. Fresh hit không gọi provider; entry stale vẫn thử provider trước, chỉ Serve sau GiveUp, và webhook invalidate cả entry tươi lẫn cũ.

### Câu hỏi tư duy

**Vì sao câu hỏi cá nhân không được cache, kể cả theo từng user?** Allowlist của lab loại mọi `request.personal`; trạng thái đơn hàng, hoàn tiền hoặc điểm thay đổi theo thời gian và có rủi ro trả thông tin cũ hoặc sai user. Key theo user chưa giải quyết độ tươi và kiểm soát quyền truy cập, nên câu hỏi cá nhân luôn đi qua provider trong implementation này.

**Khi cache giữ FAQ availability cao trong outage, alert theo số nào?** Giám sát cả lỗi/timeout ở upstream, trạng thái breaker và tỷ lệ stale trên FAQ, bên cạnh SLI thành công ở tầng user. Cần điều kiện cửa sổ và ngưỡng phù hợp lưu lượng; không coi mỗi stale hit hay mỗi breaker OPEN là đủ để page ngay. Chỉ số stale cho thấy phụ thuộc đang suy giảm ngay cả khi cache vẫn giúp nhiều lượt thành công.

---

## 9. Kiểm chứng sau chỉnh sửa

- Cài đặt trong `.venv` mới, không dùng package hệ thống, với Python **3.14.7**: `pip install --no-cache-dir -e ".[dev]"` thành công; **117 test PASS**. `python scripts/grade.py --out reports/clean_scoreboard.json` đạt **84/88** trên seed 25; mọi kiểm tra công khai PASS. Scoreboard 7 seed bên dưới được giữ riêng.
- `python -m pytest -q`: **117 PASS**, gồm 82 test được cung cấp và 35 regression mới (13 client, 18 alerting, 4 cache). Regression client kiểm tra cooldown đồng thời, token budget khi quay lại provider và permit khi deadline/budget từ chối; alerting kiểm tra burn đúng ngưỡng/gần ngưỡng, lưu lượng bằng 0, ngân sách rất nhỏ và quyết định freeze trước khi làm tròn.
- Ruff PASS trên **7 module implementation** và **3 file regression mới**. Không sửa các file test có sẵn, simulator, service, runner hoặc scenario bị bảo vệ.
- Grader với seed **25, 26, 27, 3, 4, 58, 85**: cả **6 băng Game Day, C1 và workflow** PASS trên mọi seed; public SLO PASS, 0 false page. `reports/scoreboard.json` ghi **84/88**, còn 4 điểm SLO dữ liệu ẩn chưa chấm và 12 điểm report chấm tay.
- C1 seed **1–100**, factory client seed cố định **1**, TTL **30s**: **100/100 PASS**; wrong_answers tối đa **0**, outdated tối đa **14**, FAQ availability tối thiểu **0.9488**, cache hit tối thiểu **0.554** (`reports/cache_validation.json`). Đây là kiểm chứng trên băng public nhiều seed, chưa thay thế băng ẩn thay đổi thời điểm/cường độ sự cố.
- Ba nhóm thí nghiệm client và ba nhóm cache được chạy lại với code/config cuối; tham số và kết quả lưu ở `reports/review_experiments.json`. Plot G2 được tái tạo và kiểm tra trực quan sau thay đổi.

Các kết quả gắn với working tree đã kiểm thử trên commit gốc `76138b4`; đợt chỉnh sửa này chưa tạo commit mới và báo cáo không gán SHA của commit gốc cho các thay đổi chưa commit.
