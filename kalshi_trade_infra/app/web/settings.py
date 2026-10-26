"""The web layer's settings: env switches and per-user limits that app.server and the route modules
in app.web.routes both read. Moved verbatim from app.server, which re-imports every name."""
from __future__ import annotations

import os
import re

DEV_LOGIN = os.getenv("APP_DEV_LOGIN") == "1"
# Open signup: when APP_OPEN_SIGNUP=1, ANY Google account can create a Tau account (no waitlist
# approval). Default off = invite-only (operator + approved waitlist emails). Spend is still bounded
# downstream (billing-readiness gate, bounded free credits), and the live-trading gate is untouched.
OPEN_SIGNUP = os.getenv("APP_OPEN_SIGNUP") == "1"
SECURE_COOKIES = os.getenv("APP_INSECURE_COOKIES") != "1"

MAX_ACTIVE_RESEARCH = 2
MAX_RESEARCH_PER_DAY = int(os.getenv("APP_MAX_RESEARCH_PER_DAY", "0"))  # 0 = unlimited (no daily cap)
MAX_CHAT_PER_HOUR = 40
MAX_ACTIVE_DEPLOYMENTS = 100
MAX_PAPER_BALANCE = 1_000_000.0
MAX_WAITLIST_PER_MINUTE = 10
ADMIN_EMAIL = os.getenv("TAU_ADMIN_EMAIL", "tjhprivate0416@gmail.com")
SPA_ROUTES = re.compile(r"^/(?:|dashboard|research(?:/\d+)?|strategies(?:/\d+)?|deploy|community|billing|admin|system|funds|explore|example|devlog|track-record|settings(?:/(?:account|billing|system|theme))?|signin|terms|privacy)$")
