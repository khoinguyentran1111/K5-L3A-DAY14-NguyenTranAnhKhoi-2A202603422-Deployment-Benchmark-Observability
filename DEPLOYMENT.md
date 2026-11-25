# Deployment Information

> Agent được deploy là agent Part 6 trong [`06-lab-complete/`](06-lab-complete/) (đạt `PASS 12/12`), theo CHECKPOINTS CP6.

## Public URL

`<<ĐIỀN URL SAU KHI DEPLOY, vd https://day14-agent-production.up.railway.app>>`

## Platform

**Railway** (Dockerfile build, config-as-code [`06-lab-complete/railway.toml`](06-lab-complete/railway.toml)), kèm một service **Redis** trong cùng project.
Có thể dùng Render thay thế bằng Blueprint [`06-lab-complete/render.yaml`](06-lab-complete/render.yaml) (web service + Key Value, Blueprint path `06-lab-complete/render.yaml`).

## Cách deploy (Railway)

```bash
npm i -g @railway/cli
railway login
cd 06-lab-complete
railway init                       # tạo project
railway add --database redis       # thêm Redis vào project
railway up                         # build Dockerfile + deploy service agent
# Đặt biến cho service agent (Dashboard → service → Variables, hoặc CLI):
railway variables --set "AGENT_API_KEY=<key ngẫu nhiên>" \
                  --set 'REDIS_URL=${{Redis.REDIS_URL}}' \
                  --set "ENVIRONMENT=production" \
                  --set "RATE_LIMIT_PER_MINUTE=10" \
                  --set "DAILY_BUDGET_USD=1.0" --set "MONTHLY_BUDGET_USD=10.0"
railway domain                     # sinh public URL
```

Tạo key ngẫu nhiên: `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Key chỉ nằm trên Railway, không commit.

## Test Commands

```bash
BASE=https://<your-domain>
AGENT_API_KEY=<key đã đặt trên Railway>

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200 (Redis kết nối được)
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

### Health Check

```bash
curl https://<your-domain>/health
# {"status":"ok","version":"1.0.0","environment":"production","uptime_s":...}
```

### API Test (with authentication)

```bash
curl -X POST https://<your-domain>/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
```

### Rate limit (10 req/phút) → 429

```bash
for i in $(seq 1 12); do
  curl -sS -o /dev/null -w '%{http_code} ' -X POST "$BASE/ask" -H 'Content-Type: application/json' \
       -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"test"}'
done; echo   # 200 ×10 rồi 429
```

Kết quả chạy thật (dán sau khi deploy):

```text
<<DÁN OUTPUT 4 LỆNH TỰ KIỂM Ở TRÊN>>
```

## Environment Variables Set

| Biến | Giá trị trên platform | Ghi chú |
|---|---|---|
| `PORT` | do Railway cấp | `CMD` của Dockerfile nghe `${PORT:-8000}` |
| `AGENT_API_KEY` | secret (không ghi ở đây) | Thiếu/sai → 401 |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` | Reference tới service Redis; `/ready` 503 nếu không kết nối được |
| `ENVIRONMENT` | `production` | Tắt `/docs`, `/openapi.json` |
| `RATE_LIMIT_PER_MINUTE` | `10` | |
| `DAILY_BUDGET_USD` / `MONTHLY_BUDGET_USD` | `1.0` / `10.0` | Vượt → 402 |
| `LOG_LEVEL` | `INFO` (mặc định) | |

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
