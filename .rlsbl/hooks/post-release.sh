#!/usr/bin/env bash
# Post-release hook. Runs after a successful release (non-fatal).
# Environment: RLSBL_VERSION is set to the released version.
# Customize this for your project (e.g., local install, deploy, notify).

set -euo pipefail

echo "Post-release: v$RLSBL_VERSION"

# Push to assembly for unified documentation site
if command -v selfdoc &>/dev/null && [ -f selfdoc.json ]; then
  if python3 -c "import json; c=json.load(open('selfdoc.json')); exit(0 if c.get('assembly') or (c.get('topology') or {}).get('assembly') else 1)" 2>/dev/null; then
    echo "Pushing to documentation assembly..."
    selfblog assembly push || echo "Warning: assembly push failed (non-fatal)"
  fi
fi
