#!/usr/bin/env bash
# Publish a SCRUBBED snapshot of the repo to the public GitHub remote as a single
# clean commit (force-push). The private full history stays local only.
#
# Exact secrets/identifiers to redact live in scripts/scrub_secrets.env (GITIGNORED,
# one `FROM|TO` per line), so THIS script carries no sensitive values and is itself
# safe to read. Structural ids (CloudFront domains, i-…/sg-… ids) are redacted by
# regex. The script ABORTS before pushing if any sensitive pattern survives.
#
# Usage: scripts/publish_public.sh [source_ref]     # default: HEAD
set -euo pipefail

REMOTE="git@github.com:JihuiTanUchicago/kalshi_trade.git"
SRC="${1:-HEAD}"
ROOT="$(git rev-parse --show-toplevel)"
VALUES="$ROOT/kalshi_trade_infra/scripts/scrub_secrets.env"
cd "$ROOT"

# 1. Safety backup of the full private history (local branch + tag).
git branch -f private-full-history "$SRC"
git tag   -f pre-opensource-backup "$SRC"

# 2. Export only tracked files of SRC into a clean temp tree (no .git, no untracked).
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
git archive "$SRC" | tar -x -C "$TMP"
cd "$TMP"

# 3. Remove files that must never be public.
rm -rf kalshi_trade_infra/PLAN.md mvp.md kalshi_trade_infra/DESIGN.md \
       kalshi_trade_infra/PRODUCT.md kalshi_trade_infra/AGENTS.md \
       kalshi_trade_infra/pids trading_agent_new OPEN_SOURCE_AUDIT.md \
       kalshi_trade_infra/app/static/apple-developer-merchantid-domain-association \
       kalshi_trade_infra/scripts/scrub_secrets.env \
       kalshi_trade_infra/scripts/publish_public.sh 2>/dev/null || true
find . -type d \( -name .impeccable -o -name .pytest_cache -o -name .claude \) \
       -exec rm -rf {} + 2>/dev/null || true

# 4. Redact: exact literals from the gitignored values file + structural-id regexes.
python3 - "$VALUES" <<'PY'
import os, re, sys
vals = {}
if os.path.exists(sys.argv[1]):
    for line in open(sys.argv[1]):
        line = line.rstrip("\n")
        if not line or line.startswith("#") or "|" not in line:
            continue
        a, b = line.split("|", 1); vals[a] = b
RE = [(re.compile(r'\b[a-z0-9]{10,}\.cloudfront\.net'), 'your-dashboard.example.com'),
      (re.compile(r'\bi-0[0-9a-f]{8,}\b'), '<EC2_INSTANCE_ID>'),
      (re.compile(r'\bsg-0[0-9a-f]{8,}\b'), '<SECURITY_GROUP_ID>')]
for root, _, files in os.walk('.'):
    if root == './.git' or root.startswith('./.git/'):
        continue
    for fn in files:
        p = os.path.join(root, fn)
        try:
            raw = open(p, 'rb').read()
            if b'\x00' in raw[:4096]:  # binary
                continue
            t = raw.decode('utf-8', 'surrogateescape'); o = t
        except Exception:
            continue
        for a, b in vals.items():
            t = t.replace(a, b)
        for rx, b in RE:
            t = rx.sub(b, t)
        if t != o:
            open(p, 'w', encoding='utf-8', errors='surrogateescape').write(t)
print("redacted")
PY

# 5. Hard gate: build a pattern from the regexes + every literal, abort if any remain.
PAT='i-0[0-9a-f]{8,}|[a-z0-9]{10,}\.cloudfront\.net|sg-0[0-9a-f]{8,}'
if [ -f "$VALUES" ]; then
  while IFS='|' read -r a _; do
    case "$a" in ''|'#'*) continue;; esac
    PAT="$PAT|$(printf '%s' "$a" | sed 's/[][\.*^$(){}+?|/]/\\&/g')"
  done < "$VALUES"
fi
if grep -rInE "$PAT" . --exclude-dir=.git >/dev/null 2>&1; then
  echo "GATE FAILED — sensitive data still present:" >&2
  grep -rInE "$PAT" . --exclude-dir=.git | head >&2
  exit 1
fi
echo "gate clean"

# 6. Fresh single-commit history, force-push to public main.
git init -q -b main
git add -A
git -c user.name="JihuiTanUchicago" -c user.email="admin@example.com" \
    commit -q -m "chore: public release (clean history)"
git push -f "$REMOTE" HEAD:main
echo "published clean snapshot -> $REMOTE (main)"
