#!/bin/sh
# Copies the engine's model catalog into the iOS app bundle resources.
# Run after catalog, rubric, policy or result changes. Engine/Router.swift and Rubrics.swift
# must also mirror core.py, including paired option-order checks; copying data cannot port logic.
# The parity checks below fail when engine constants or text diverge.
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
cp "$root/issue_router/catalog.json" "$root/ios/JevIssueRouter/Resources/catalog.json"
echo "Copied catalog.json into ios/JevIssueRouter/Resources/"
PYTHONPATH="$root" python3 -m unittest discover -s "$root/tests" -p test_ios.py
