#!/bin/sh
# Copies the engine's model catalog into the iOS app bundle resources.
# Run after editing issue_router/catalog.json; tests/test_ios.py fails while the copies differ.
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
cp "$root/issue_router/catalog.json" "$root/ios/JevIssueRouter/Resources/catalog.json"
echo "Copied catalog.json into ios/JevIssueRouter/Resources/"
