#!/usr/bin/env bash
set -euo pipefail

echo "  Updating CLI schema..."
uv run wesktop --dump-schema
