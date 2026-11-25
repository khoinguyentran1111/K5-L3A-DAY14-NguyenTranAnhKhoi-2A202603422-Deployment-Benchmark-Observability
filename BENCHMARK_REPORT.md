# Benchmark & Observability Report — Day 14

**Họ tên:** Nguyễn Trần Anh Khôi — 2A202603422
**Ngày chạy:** 2026-11-25 (giờ ghi trong bài là UTC)
**Môi trường:** Laptop Intel Core i5-11400H (6 nhân / 12 luồng), 16 GB RAM, Windows 11 + Docker Desktop 29.9.3 (VM 12 CPU / 7.6 GB).
Bước 1 (develop) chạy agent và `load_test.py` / `run_eval.py` bằng Python 3.11 trong WSL2 Ubuntu 22.04 (load generator và agent chung một máy).
Bước 2 (production) chạy Docker Compose với `-p k5-day14-observability`, mỗi agent bị giới hạn `cpus: 0.5`, `memory: 256M`.

Bằng chứng: [`reports/`](reports/) (JSON load test và eval), [`benchmark-results/`](benchmark-results/) (CSV Locust), [`screenshots/`](screenshots/).

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < **500 ms** | Mock LLM mất ~150–250 ms/call (p95 đo được ~220 ms ở tải thường), nên 500 ms chừa ~2× headroom cho retrieval + mạng. Đặt theo p95 thay vì avg vì avg che mất tail (xem 2.2). Alert p95 > 1 s trong 2 phút được đặt lỏng hơn SLO để tránh báo động vì spike |
| Error rate `/ask` | < **2 %** | Upstream mock tự lỗi ~1% (`MOCK_ERROR_RATE=0.01`), nên 2% là error budget cho phép gấp đôi mức nền. Alert ở 5% trong 1 phút để chỉ báo khi vi phạm rõ rệt |
| Accuracy trên golden dataset | ≥ **85 %** và **0 regression** | Gate trong CI (job [`.github/workflows/eval.yml`](.github/workflows/eval.yml)). Mức 85% chặn được bản tệ như v1 (4.3%). Điều kiện "không regression" so với baseline đảm bảo không câu nào đang đúng bị sai đi. Bản phát hành hiện tại đạt 100% |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, 300 request mỗi mức)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.21 | 189.7 | 220.0 | 1687.8 | 2.00% | ✅ PASS |
| 10 | 37.73 | 189.0 | 219.9 | 1697.5 | 0.67% | ✅ PASS |
| 50 | 141.3 | 195.5 | 253.7 | 1684.3 | 2.00% | ✅ PASS |
| 100 | 62.37 | 393.7 | 3102.2 | 3699.2 | 0.67% | ❌ FAIL (p95) |

Nguồn: `reports/load_v2_c{1,10,50,100}.json`.

**Nhận xét:** Từ 1 → 10 → 50, RPS tăng **gần tuyến tính** (4.2 → 37.7 → 141.3, tức ×9 rồi ×3.7) trong khi p50/p95 gần như không đổi. Lý do: mock LLM là `asyncio.sleep` nên agent chỉ chờ chứ không tốn CPU, một event loop xử lý song song được nhiều request; theo định luật Little, RPS ≈ concurrency / latency ≈ 50 / 0.23 s. Tới **c=100 thì gãy**: RPS giảm còn 62 req/s, p50 tăng gấp đôi (394 ms), p95 lên 3.1 s, và min latency 190 ms cho thấy *mọi* request đều phải xếp hàng. Agent develop chỉ có **1 process uvicorn** (1 event loop, 1 nhân CPU), mỗi request vẫn tốn CPU thật cho FastAPI/pydantic, ghi log JSON và cập nhật metrics, lại thêm 100 kết nối TCP mở cùng lúc, trong khi load generator chạy chung máy. CPU của process đó trở thành nút thắt nên RPS không tăng nữa, request phải chờ và latency vọt lên. Đây là một lần chạy ngắn (4.8 s), nên con số c=100 nhạy với nhiễu, nhưng xu hướng "bão hoà rồi gãy" là rõ. Muốn chịu c=100 cần scale ngang (nhiều worker/instance, xem mục 5) chứ không thể tăng concurrency trên một process.

p99 ~1.7 s ở mọi mức (kể cả c=1) không phải do tải mà do ~3% request bị mock làm chậm thêm 1.5 s (`MOCK_SLOW_RATE=0.03`).

### 2.2 Tail latency (agent v2, `--requests 300 --concurrency 20`)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 189.6 | 217.2 | 226.5 |
| 0.03 (mặc định) | 230.8 | 221.7 | 1691.4 |
| 0.1 | 358.0 | 1693.5 | 1715.0 |

Nguồn: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`.

**Nhận xét:** **p99 nhạy nhất**: chỉ 3% request chậm đã đẩy p99 từ 227 ms lên 1691 ms (×7.5) trong khi avg chỉ tăng 22% (190 → 231 ms) và p95 gần như không đổi (217 → 222 ms, vì 3% < 5% nên chưa chạm tới p95). Khi tăng lên 10%, request chậm vượt ngưỡng 5% nên **p95 nhảy lên 1694 ms** (vi phạm SLO 500 ms), còn avg vẫn chỉ 358 ms, trông "chấp nhận được". Average trộn chung số ít request rất chậm với số đông request nhanh nên che mất trải nghiệm của nhóm bị chậm. Ở mức 3%, cứ 100 người thì 3 người chờ gần 2 giây mà avg không phản ánh điều đó. SLO đặt theo p95/p99 nói thẳng "x% người dùng được phục vụ dưới ngưỡng", nên mới bắt được tail.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 57.1 | 109.1 | 116.1 |
| Tổng cost (USD) | 0.000404 | 0.000762 | 0.000812 |
| Cost / câu đúng (USD) | 0.00040395 | 0.00003627 | 0.00003530 |
| Quality gate | ❌ FAIL (exit 1) | ✅ PASS (≥80%, 0 regression so với v1) | ✅ PASS (`--min-accuracy 1.0`, 0 regression so với v2) |

Nguồn: `reports/eval_v1.json`, `eval_v2.json`, `eval_v2_fixed.json`.

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Đã sửa gì |
|---|---|---|
| `scaling-03` ("Kubernetes HPA scale dựa trên những chỉ số nào?") | `cpu`, `memory`, `custom metrics` | Thêm entry KB, trigger `["hpa", "kubernetes", "autoscal"]`: "Kubernetes HPA (Horizontal Pod Autoscaler) tự tăng/giảm số pod dựa trên mức dùng CPU, memory hoặc custom metrics như RPS hay độ dài hàng đợi…" |
| `security-02` ("JWT khác gì API key trong xác thực?") | `token`, `hết hạn`, `chữ ký` | Thêm entry KB, trigger `["jwt", "json web token"]`: "API key là chuỗi bí mật cố định, không tự hết hạn… JWT là token có chữ ký số (HMAC/RSA), chứa thông tin user và thời điểm hết hạn (exp)…" |

Trước khi thêm, mình kiểm tra các trigger keyword chỉ xuất hiện trong đúng 2 câu này của golden dataset (`grep -i "jwt|hpa|kubernetes|autoscal"`), nên retrieval của 21 câu còn lại không bị "cướp" tài liệu. Kết quả: cải thiện 2 câu, **0 regression**. Phần sửa cũng được chép sang `production/utils/mock_llm.py`.

**Quality gate trong CI:** chạy v1 với `--baseline reports/eval_v2.json` thì in `Câu bị regression : 20`, `Quality gate … ❌ FAIL` và **exit code 1**. Job [`.github/workflows/eval.yml`](.github/workflows/eval.yml) khởi động agent v2 (`MOCK_ERROR_RATE=0`), chạy `run_eval.py --min-accuracy 0.85 --baseline reports/eval_v2_fixed.json`. Exit code ≠ 0 làm step fail; bật branch protection "Require status checks" cho job này là PR không merge được.

**Trade-off chất lượng / chi phí / latency giữa v1 và v2:** v2 thêm retrieval nên prompt dài hơn: **tokens/câu ×1.9** (57 → 109), **tổng cost ×1.9**, **latency p95 +37 ms** (189.6 → 226.6 ms trong eval: 20 ms retrieval + prompt dài làm mock LLM chậm hơn). Đổi lại accuracy tăng từ 4.3% lên 91.3%. Tính theo **cost / câu đúng** thì v2 rẻ hơn **~11 lần** ($0.00040 → $0.000036), vì tiền v1 bỏ ra phần lớn là cho câu trả lời sai. Sửa KB tăng thêm 7 token/câu (+6.6% cost) nhưng cost/câu đúng còn giảm tiếp. Rõ ràng nên chọn v2.

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải: [screenshots/grafana-dashboard.png](screenshots/grafana-dashboard.png) (Locust 30 user, 2 instance, chụp 10:00 UTC)
- [x] Trace chậm trong Jaeger: [screenshots/jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)
- [x] Trace lỗi trong Jaeger: [screenshots/jaeger-error-trace.png](screenshots/jaeger-error-trace.png) (span `agent.run` và `chat mock-llm-small` có trạng thái lỗi, event `exception`, xem 4.3)
- [x] Trang Alerts của Prometheus với 2 alert cùng **firing**: [screenshots/prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png) (`AgentHighErrorRate` + `AgentHighLatencyP95`)

Ảnh được chụp tự động bằng Chrome headless trên chính các UI đang chạy (Grafana anonymous viewer, Jaeger, Prometheus).

**Trả lời Exercise 7.4** (Locust 30 user, ramp 5, 2 instance; query Prometheus lúc 10:00:03 UTC, cửa sổ 1 phút):

1. **p95 = 293 ms, avg = 231 ms** (p99 = 1824 ms). p95 chỉ cao hơn avg ~60 ms nên phần lớn request đồng đều, nhưng p99 gấp ~8 lần avg: có một nhóm nhỏ (~3%) request rất chậm (tail latency do LLM chậm), avg không cho thấy điều này.
2. **Có chia đều:** 9.33 req/s (`172.21.0.7`) và 9.24 req/s (`172.21.0.8`). Nginx round-robin qua DNS `agent` (re-resolve 10 s).
3. **Input 1440 tokens/s > output 762 tokens/s** vì input = system prompt + tài liệu retrieve được (RAG) + câu hỏi, còn output chỉ là câu trả lời. RAG làm prompt dài hơn đáng kể so với câu trả lời.
4. `curl http://localhost:8080/metrics` → **404** (Nginx có `location = /metrics { return 404; }`). Metrics chỉ dành cho Prometheus scrape trực tiếp agent trong mạng nội bộ; public ra ngoài sẽ lộ route, lưu lượng, model, chi phí.

Hai sự cố gặp khi dựng stack, đã sửa (chi tiết trong AI log của `MISSION_ANSWERS.md`):
- Dockerfile production crash `ModuleNotFoundError: uvicorn` vì user `agent` có `HOME=/app` → thêm `ENV PYTHONUSERBASE=/home/agent/.local`.
- `docker compose run locust` tự khởi động lại dependency theo `replicas: 2` nên làm sai số instance khi benchmark scaling → chạy Locust với `--no-deps` (xem mục 5).

`promtool test rules /p/alert_rules_test.yml` → `SUCCESS`.

### 4.2 Thí nghiệm "phá hệ thống"

Tải nền: Locust headless 30 user (container `k5-load`), 2 instance. Mỗi thí nghiệm đổi `.env` rồi `docker compose up -d --scale agent=2 agent` (t0 = lúc chạy lệnh). Thời gian đo bằng cách poll `/api/v1/alerts` mỗi 5 s.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` (chạy cùng lúc với B) | `AgentHighErrorRate` (giá trị 21.5%) | **93 s** (t0 10:01:48 → pending 10:02:21 → firing 10:03:21) | Error rate (stat chuyển đỏ), "LLM calls theo kết quả" (đường `error` tăng), Requests/s theo status (503) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (p95 = 1.90 s) | **148 s** (t0 10:01:48 → pending 10:02:16 → firing 10:04:16) | Latency p50/p95/p99: p95 nhảy lên ~1.9 s, avg tăng ít hơn |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | **144 s** (t0 10:04:40 → pending 10:05:03 → firing 10:07:04) | Cost burn rate (USD/giờ): $34.5/giờ (cửa sổ 1 phút); LLM latency p95 0.50 s (tăng ~2.5×) |
| D | `docker pause k5-day14-observability-agent-1` | `AgentInstanceDown` (`up{instance="172.21.0.7:8000"} = 0`) | **36 s** (t0 10:07:19 → pending 10:07:25 → firing 10:07:55) | Instances up (2 → 1); Requests/s theo instance (traffic dồn sang instance còn lại). Error rate của agent vẫn xanh (0.4%) |
| E | `AGENT_VERSION=v1` | **Không có alert SLO nào** trong 3 phút theo dõi (10:08:07 → 10:11:11). `LLMCostBurnRateHigh` vẫn firing nhưng là "đuôi" của thí nghiệm C (cửa sổ `rate[5m]` còn chứa dữ liệu model large), không do v1 | — | Tokens/s giảm (input 1440 → 708, output 762 → 383 /s), Retrieval hit ratio mất, bảng "Phiên bản đang chạy" đổi sang v1. Latency còn *tốt hơn* (p95 198 ms) |

Hai phát hiện ngoài dự kiến:
- **`LLMCostBurnRateHigh` firing ngay ở tải nền** (active từ 09:55:12; đo được $5.20/giờ lúc 10:00:03 và $4.42/giờ lúc 10:01:32, đều > ngưỡng $2/giờ): ~18.6 req/s × ~$4×10⁻⁵/request của model small đã vượt ngưỡng. Ngưỡng $2/giờ trong `alert_rules.yml` thấp hơn mức chi bình thường ở tải này, nên alert sẽ kêu liên tục (alert fatigue). Ngưỡng nên tính từ budget thật, ví dụ ngân sách ngày / 24 × hệ số an toàn, hoặc dùng *burn rate* so với mức chi bình thường.
- A và B chạy đồng thời để có được ảnh 2 alert cùng firing. Mỗi alert vẫn được tính giờ riêng, nhưng error rate cao cũng làm số request thành công giảm nên hai thí nghiệm có ảnh hưởng nhẹ lên nhau.

Thời gian tới lúc firing ≈ thời gian để `rate(...[1m])` phản ánh thay đổi (~30 s, có thêm vài giây agent khởi động lại) + `for` của rule (A: 1 phút, B/C: 2 phút, D: 30 s) + chu kỳ đánh giá rule.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Đây là lỗi **chất lượng** chứ không phải lỗi hạ tầng: request vẫn 200, nhanh, rẻ hơn, nên mọi metric hạ tầng đều xanh. Cách phát hiện:
1. **Chặn trước khi deploy:** quality gate eval trên golden dataset trong CI/CD (job `eval.yml`). v1 cho exit code 1 (accuracy 4.3%, 20 regression), nên không lên được production.
2. **Giám sát sau deploy:** chạy eval định kỳ (synthetic) trên endpoint production / canary và xuất accuracy thành metric (vd `agent_eval_accuracy`) có alert; online eval trên một mẫu traffic thật (LLM-as-judge / so khớp keyword).
3. **Metric gián tiếp:** alert khi retrieval hit ratio giảm đột ngột, khi tokens/request lệch xa baseline, hoặc khi `agent_info{version}` đổi ngoài quy trình release; theo dõi tín hiệu người dùng (thumbs down, hỏi lại, tỉ lệ rời bỏ).

### 4.3 Debug bằng trace

Trace chậm nhất trong 30 phút (lấy qua Jaeger API `/api/v3/traces`, 1500 trace gần nhất, chọn trace `POST /ask` dài nhất):

- `trace_id`: `89712eb4c2ae2d9ec1a5bcf71181ca93` (instance `a45af22fa496`, bắt đầu 10:00:12.889 UTC)
- Tổng thời gian: **1725.7 ms**
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** (**1695.8 ms, 98.3%**; `gen_ai.usage.input_tokens=81`, `output_tokens=46`). Các span khác: `agent.run` 1720.8 ms (span cha), `agent.retrieve_context` 24.5 ms (1.4%). Thời gian nằm ở **LLM upstream**, không phải ở code hay retrieval của agent.
- Dòng log tương ứng (`docker compose -p k5-day14-observability logs --no-log-prefix agent | grep 89712eb4c2ae2d9ec1a5bcf71181ca93`):

```json
{"ts": "2026-11-25T10:00:14.612834+00:00", "level": "INFO", "service": "observable-agent", "instance": "a45af22fa496", "event": "llm_call", "trace_id": "89712eb4c2ae2d9ec1a5bcf71181ca93", "span_id": "f4ff359e73bf0cd6", "request_id": "06f6c5bccb1d", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 81, "output_tokens": 46, "cost_usd": 4e-05, "llm_ms": 1694.7}
{"ts": "2026-11-25T10:00:14.613952+00:00", "level": "INFO", "service": "observable-agent", "instance": "a45af22fa496", "event": "http_request", "trace_id": "89712eb4c2ae2d9ec1a5bcf71181ca93", "span_id": "f4ff359e73bf0cd6", "request_id": "06f6c5bccb1d", "method": "POST", "route": "/ask", "status": 200, "ms": 1724.3}
```

Trace lỗi: `563556d32847e8c08ff36c9a76d9c8b6` (113.7 ms, HTTP 503). Span `chat mock-llm-small` (89.9 ms) có status ERROR, `error.type=upstream_unavailable`, event `exception` (`utils.mock_llm.LLMError: Upstream LLM error: 503 Service Unavailable (mock)`). Lỗi được propagate lên `agent.run` và `POST /ask`. Log cùng `trace_id`:

```json
{"ts": "2026-11-25T10:01:04.662928+00:00", "level": "INFO", "service": "observable-agent", "instance": "3bff64553a5e", "event": "llm_error", "trace_id": "563556d32847e8c08ff36c9a76d9c8b6", "span_id": "5917aa49048f1fbb", "request_id": "56d4d018683e", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, ramp 10/s, 2 phút)

Số liệu dòng `POST /ask` trong `benchmark-results/scale_{1,3}_stats.csv`:

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 59.68 | 200 | 390 | 1700 | 65 / 7146 (0.91%) |
| 3 | 59.90 | 190 | 230 | 1700 | 60 / 7112 (0.84%) |

Số instance được xác nhận trước và sau mỗi lần chạy bằng `docker ps` và `count(up{job="agent"}==1)` trên Prometheus (scale_1: 1/1, chạy 09:53:51–09:55:53; scale_3: 3/3, 09:56:22–09:58:23). Locust chạy với `docker compose run --rm --no-deps ...`. Lệnh trong CHECKPOINTS (không có `--no-deps`) làm Compose đưa agent về `replicas: 2` khi khởi động Locust; lần chạy đầu bị lỗi này nên mình đã bỏ kết quả đó và chạy lại.

**Giải thích kết quả:** Scale 1 → 3 **cải thiện p95 rõ rệt (390 → 230 ms, −41%)**, p50 giảm nhẹ (200 → 190 ms). Với 1 instance (giới hạn 0.5 CPU), phần CPU cho mỗi request (FastAPI, metrics, tracing export, log JSON) ở ~60 req/s làm container gần bão hoà, request phải xếp hàng nên p95 đội lên. Chia ra 3 instance thì hết xếp hàng.
Nhưng **RPS không đổi (~60 req/s)** vì Locust là tải *closed-loop*: 100 user, mỗi user nghỉ 0.5–2 s (trung bình 1.25 s) giữa 2 lần gọi, nên tải tối đa ≈ 100 / (1.25 + ~0.24) ≈ 67 req/s (gồm cả `/health`). Hệ thống phục vụ hết lượng tải mà user tạo ra, scale thêm không tạo thêm request.
**p99 vẫn 1700 ms ở cả hai** vì đó là ~3% call LLM chậm thêm 1.5 s (panel "LLM latency p95" và trace ở 4.3 cho thấy 98% thời gian nằm trong span LLM). **Nút thắt của tail latency là LLM upstream**, thêm instance agent không sửa được. Muốn giảm cần timeout + retry/hedging, cache câu trả lời, streaming, hoặc model/provider nhanh hơn. Failures (~0.9%) là lỗi 503 do mock upstream (`MOCK_ERROR_RATE=0.01`), không phụ thuộc số instance.

---

## 6. Kết luận

- 3 điều học được về benchmark & observability:
  1. **Average nói dối, percentile thì không:** 3% request chậm làm p99 tăng 7.5× trong khi avg chỉ tăng 22%. SLO và alert phải đặt theo p95/p99, và phải biết p95 chỉ "nhìn thấy" tail khi tail vượt 5%.
  2. **Đo thì phải kiểm lại điều kiện đo:** RPS bất thường ở lần chạy đầu dẫn tới phát hiện `docker compose run` đã âm thầm đổi số instance. Mọi benchmark cần ghi lại và kiểm tra cấu hình thật lúc chạy (số instance, version, model), không chỉ cấu hình định chạy. Tương tự, load generator closed-loop giới hạn RPS, nên "RPS không tăng" chưa chắc là do server.
  3. **Metric hạ tầng xanh ≠ agent tốt:** đổi sang v1 làm chất lượng tụt từ 100% xuống 4.3% mà không alert nào kêu, còn latency lại đẹp hơn. Với agent LLM phải có eval/quality gate. Ngược lại, metric lại cần được nối với trace và log (`trace_id`) để đi từ "p95 tăng" tới "span LLM chiếm 98%" chỉ trong vài phút.
- Nếu đưa agent này lên production thật, sẽ thêm:
  - **Alert theo SLO burn rate** (multi-window: 5m + 1h) thay cho ngưỡng tĩnh, và chỉnh lại `LLMCostBurnRateHigh` theo budget thật (hiện đang kêu ở tải bình thường).
  - **Giám sát từ bên ngoài / tầng LB:** synthetic check gọi `/ask` qua URL public, cùng metric 5xx/504 của Nginx. Thí nghiệm D cho thấy lỗi ở LB không hiện trên metric của agent.
  - **Metric chất lượng:** eval định kỳ trên production xuất `agent_eval_accuracy`, retrieval hit ratio có alert, tỉ lệ feedback tiêu cực.
  - **Metric & alert cho LLM upstream:** tỉ lệ 429/503 theo provider, timeout, số lần retry, tokens/request p95 (phát hiện prompt phình to), cost theo user/tenant (log/trace chứ không làm label).
  - **Saturation:** CPU/memory theo container và độ dài hàng đợi, kèm autoscale theo in-flight requests.
