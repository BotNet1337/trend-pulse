# Phase 0 research — proxy-as-a-service for the account-factory (2026-06-20)

**Use-case:** low volume (a few accounts), each account holds **ONE sticky residential/mobile
IP for days–weeks**, **country-matched** to the SMS number, allocated/released via a
**programmatic HTTP API**, returning a **SOCKS5** endpoint usable by Telethon/MTProto.

**Two load-bearing facts:**
1. Telethon/Pyrogram support **SOCKS5, not MTProto-proxy** → we need plain SOCKS5 over TCP;
   no native MTProto secret needed. ([proxycove.com](https://proxycove.com/en/blog/mtproto-proxy-telegram-guide))
2. MTProto is **TCP-only**. Density guidance: mobile = 1 proxy / 1–2 accounts, residential =
   1 account; warm new accounts 3–7 days; avoid mid-session IP changes (sticky).
   ([saasultra.com](https://www.saasultra.com/best-telegram-proxy-providers/))

**Decisive filter:** rotating-residential pools cap sticky at minutes–hours, or 7 days
(IPRoyal). "Same IP for **days/weeks**" (our 1–2 week probation) is satisfied only by a
**dedicated/rented per-port IP** (mobile dedicated, or ISP/static residential).

## Comparison table

| Provider | Prog. API (alloc/rotate/release) | SOCKS5 | Sticky max | Geo | Price (resi $/GB) | Price (mobile/dedicated) | Min top-up | API auth | TG-fit |
|---|---|---|---|---|---|---|---|---|---|
| **Mobileproxy.space** ★ | **YES** `buyProxy`/`changeIp`/`refundProxy`/`getBalance` | Yes | **Unlimited** (rented port) | country/city/operator | n/a (flat) | **$33–169/IP/mo**, unlimited traffic | 1 IP, free 2h trial | Bearer token | **Best** (real GSM mobile, lowest ban) |
| **IPRoyal** (runner-up) | **YES** `POST /access/generate-proxy-list`, sub-user CRUD, `DELETE /sessions` | Yes (:32325) | **7 days** resi / unlimited dedicated mobile | country/city/state/ISP | $7→$1.75 | dedicated mobile ~$117–130/mo | 1 GB, free starter | **Bearer** | clean REST; resi cap 7d |
| ASocks | YES `create-port`/`delete-port`/`balance` | Yes | **≤60 min** ✗ | country/state/city/ASN | $3 flat | $3/GB | $15 (crypto) | `?apikey=` | great geo, sticky too short |
| Proxy-Cheap | YES `order`/`proxies`/`extend` | Yes | lifetime (static/mobile) | country/region/ISP | $0.78 | static mobile from $11.61/proxy | UNVERIFIED | `X-Api-Key`+secret | cheap static sticky |
| Bright Data | YES `POST/GET/DELETE /zone` | Yes (base64 Basic for SOCKS5+geo) | days via dedicated/ISP | country/city/ASN | $4.00→$3.50 | UNVERIFIED | trial | Bearer | highest-trust IPs, mature API |
| Oxylabs | YES sub-user CRUD | Yes (:7777) | 24h (SOCKS5+24h combo UNVERIFIED) | country/state/city | ~$6→$2.50 | mobile $7.50→$3.50/GB | $30 | Basic→JWT (1h) | best docs, ~2× cost |
| Decodo (Smartproxy) | YES (REST paths UNVERIFIED) | **Yes** (:7000) | 24h doc / 60min conflict | country/state/city/ASN/ZIP | $3.75→$2.50 | ~$3.75/GB | 3 GB, 3-day trial | API key | cheap resi SOCKS5 |
| SOAX | Partial (dashboard-buy) | Yes | resi 60 min; ISP/static 24h | country/city/region | $3.60→$2.00 | UNVERIFIED | ~$90 | `package_key` | provisioning leans on dashboard |
| ProxyEmpire | Partial (no alloc API) | Yes (+UDP) | UNVERIFIED | country/.../ISP | $3.5→~$1.5 | from $4.50/GB | $1.97 trial | UNVERIFIED | markets TG, no alloc API |
| Astroproxy | YES port CRUD + `newip` | Yes | UNVERIFIED | country/city/ISP | ~$7.30 measured | ~$13/GB; $0.30/port/mo | ~100 MB | API key (hdr UNVERIFIED) | real port CRUD |
| PIA S5 | **NO** (desktop client `127.0.0.1:10101`) | Yes | ~90 min ✗ | country/city/ISP | $3.5/GB | $0.25→$0.045/IP | $50 | local app | ✗ desktop-bound, ban flags |
| 922S5 | **DEFUNCT** | — | — | — | — | — | — | — | ✗ do not use |

## DECISION — **Mobileproxy.space** (implemented vendor + recommendation)

The only provider that **natively satisfies "same IP for days/weeks"** without caveats: each
port is a **dedicated GSM mobile IP**, one-user-per-channel, rented day→year; the IP changes
only when you call `changeIp`. Mobile carrier IPs have the **lowest Telegram ban rate** — the
literal goal of this epic. Matches our low-volume profile: a handful of accounts each pinned
to one country-matched mobile IP surviving weeks, allocated/released via API, **unlimited
traffic** at $33 entry (no per-GB metering risk).

- API (from official PHP SDK + [mobileproxy.space/en/user.html?api=](https://mobileproxy.space/en/user.html?api=)):
  `buyProxy()` allocate, `getTestProxy()` free 2h trial, `changeIp()` rotate (no rate limit),
  `changeEquipment()` re-target geo, `getBalance()`, `refundProxy()` release,
  `getMyProxy()/getProxyIp()/getIpStats()` inspect. Auth: **Bearer token**.
- SOCKS5 supported; country/city/operator geo across 40+ countries.

**Why over the research's tie with IPRoyal:** IPRoyal has the cleanest documented Bearer REST,
but its residential sticky caps at **7 days < our 14-day probation**, forcing its pricier
(~$117/mo) dedicated mobile — so on a mobile-vs-mobile basis Mobileproxy.space is **both
cheaper ($33 entry) and better quality** while satisfying weeks-stickiness natively. IPRoyal
remains the documented swappable alternative (env `ACCOUNT_FACTORY_PROXY_PROVIDER=iproyal`).

**Implementation risk + mitigation:** the exact REST auth header/wire format is partly
UNVERIFIED in public docs. Mitigate by (a) making base URL + auth header configurable
constants/settings, (b) implementing against the documented SDK method semantics, (c)
deterministic **mocked-httpx unit tests** (vendor-format-independent), (d) confirming the
exact wire format on the **free 2h trial** with the owner's key before the real measurement.

### Exact API shape to implement against (Mobileproxy.space)
```
Base:  https://mobileproxy.space/   (REST at /en/user.html?api=)
Auth:  Authorization: Bearer <MOBILEPROXY_API_TOKEN>
Geo:   getCountries / getCities / getOperators / getPrices(countryId)
Alloc: buyProxy({country/city/operator, period}) -> proxy id + host:port + proxy_key  (SOCKS5)
Read:  getMyProxy(id) / getProxyIp(id) / getIpStats / getBalance
Rotate: changeIp(proxy_key)   # DO NOT call → stickiness = rental length
Release: refundProxy(id)
```
Runner-up IPRoyal shape: `POST https://resi-api.iproyal.com/v1/access/generate-proxy-list`
`{port:"socks5", rotation:"sticky", location:"_country-de", lifetime:"7d"}`, Bearer auth,
`DELETE /sessions` to release, `GET /residential/me` usage.
([docs.iproyal.com/proxies/residential/api/access](https://docs.iproyal.com/proxies/residential/api/access))

## Alternative — SMSPVA Rental API (add alongside, not instead)
Verified from the SMSPVA OpenAPI spec ([docs.smspva.com/json/schema.php](https://docs.smspva.com/json/schema.php?lang=en)):
real programmatic rental at `GET /api/rent.php?method=create|activate|sms|prolong|delete`,
`dtype=week|month` (min 7 / max 90 days), same number receives **many** SMS over the window,
**Telegram = service `opt29`** (~$1.10/day ≈ $7.70/wk) vs activation ~$0.07–0.65 one-time.
**Verdict:** keep cheap activation `get_number` as default for the first code; add `rent.php`
**selectively** for high-value accounts that must stay re-loginable for weeks (future/login
2FA). JSON+`apikey` shape nearly mirrors the existing activation client → low integration
cost. Gate economically + on a live `opt29` persistence/ban smoke test. **Follow-up task.**

## Open items to confirm on trial (before the real measurement)
- Mobileproxy.space: reconcile per-IP pricing; confirm REST auth header; live Telethon SOCKS5 login on a trial port.
- SMSPVA rental: one live `opt29` rental to confirm multi-day persistence + no re-login ban.
