"""Named constants for the API-key feature (TASK-028).

No magic literals (CONVENTIONS). Referenced by service.py, schemas.py,
and auth/api_key.py.
"""

# Brand prefix prepended to every key (tp_ makes keys recognisable at a glance).
API_KEY_PREFIX: str = "tp_"

# Entropy source: secrets.token_urlsafe(32) → 43-char URL-safe base64 string.
# 32 bytes = 256 bits of entropy — vastly more than brute-force range.
_TOKEN_NBYTES: int = 32

# Prefix stored for narrow-lookup + display: brand prefix ("tp_") + 8 random chars.
# Stored in the DB, returned in list/read responses (never the full key).
_PREFIX_LEN: int = 8

# Name validation
_NAME_MIN_LEN: int = 1
_NAME_MAX_LEN: int = 255

# Coarse last-used tracking: only rewrite ApiKey.last_used_at if it is older than
# this, to avoid write-amplification on the high-RPS programmatic read path.
_LAST_USED_THROTTLE_SECONDS: int = 60

# Error / description messages (no magic strings at call sites).
MSG_API_KEY_NOT_FOUND: str = "api key not found"
