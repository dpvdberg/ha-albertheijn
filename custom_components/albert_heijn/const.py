"""Constants for the Albert Heijn integration."""

DOMAIN = "albert_heijn"

CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_MEMBER_ID = "member_id"

API_BASE_URL = "https://api.ah.nl"
AUTH_TOKEN_URL = f"{API_BASE_URL}/mobile-auth/v1/auth/token"
AUTH_REFRESH_URL = f"{API_BASE_URL}/mobile-auth/v1/auth/token/refresh"
GRAPHQL_URL = f"{API_BASE_URL}/graphql"

CLIENT_ID = "appie-ios"
USER_AGENT = "Appie/9.28 (iPhone17,3; iPhone; CPU OS 26_1 like Mac OS X)"
CLIENT_VERSION = "9.28"

DEFAULT_SCAN_INTERVAL = 300  # 5 minutes
