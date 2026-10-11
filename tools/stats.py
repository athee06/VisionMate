# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Shows how many times VisionMate and its vision data were downloaded, from GitHub's release counters.

Usage:
  python tools/stats.py                       print the counts
  python tools/stats.py --markdown STATS.md   also write a report and add today's totals to stats/history.csv

The vision data download count is the best measure of how many people set VisionMate up.
Uses the GITHUB_TOKEN environment variable if set. GitHub's counters can lag by a few hours.
"""
import argparse
import csv
import datetime
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "addon", "globalPlugins", "visionMate"))
import release  # noqa: E402

HISTORY = os.path.join(ROOT, "stats", "history.csv")


def fetchReleases():
	url = f"https://api.github.com/repos/{release.GITHUB_REPO}/releases?per_page=100"
	headers = {"Accept": "application/vnd.github+json", "User-Agent": "VisionMate-stats"}
	if os.environ.get("GITHUB_TOKEN"):
		headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
	with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
		return json.load(r)


def collect(releases):
	rows, data, addon = [], 0, 0
	for rel in releases:
		for asset in rel["assets"]:
			n = asset["download_count"]
			if asset["name"].endswith(".vmdata"):
				data += n
			elif asset["name"].endswith(".nvda-addon"):
				addon += n
			else:
				continue
			rows.append((rel["tag_name"], asset["name"], n))
	return rows, data, addon


def updateHistory(today, data, addon):
	os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
	history = []
	if os.path.isfile(HISTORY):
		with open(HISTORY, newline="", encoding="utf-8") as f:
			history = [r for r in csv.DictReader(f) if r["date"] != today]
	history.append({"date": today, "data_downloads": data, "addon_downloads": addon})
	with open(HISTORY, "w", newline="", encoding="utf-8") as f:
		w = csv.DictWriter(f, fieldnames=["date", "data_downloads", "addon_downloads"])
		w.writeheader()
		w.writerows(history)
	return history


def writeMarkdown(path, rows, data, addon, history):
	now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
	lines = [
		"# VisionMate download statistics",
		"",
		f"Updated automatically every day. Last update: {now}. GitHub's counters can lag by a few hours.",
		"",
		"| | Total |",
		"|---|---|",
		f"| **Set-ups** (vision data downloads, about one per user) | **{data}** |",
		f"| Add-on downloads (new installs and updates) | {addon} |",
		"",
		"## By release",
		"",
		"| Release | File | Downloads |",
		"|---|---|---|",
	]
	lines += [f"| {tag} | {name} | {n} |" for tag, name, n in rows]
	lines += ["", "## Daily history (last 30 days)", "", "| Date | Set-ups | Add-on downloads | New set-ups that day |",
		"|---|---|---|---|"]
	recent = history[-31:]
	for i, h in enumerate(recent):
		if i == 0 and len(history) > len(recent):
			continue
		prev = recent[i - 1] if i else None
		new = int(h["data_downloads"]) - int(prev["data_downloads"]) if prev else ""
		lines.append(f"| {h['date']} | {h['data_downloads']} | {h['addon_downloads']} | {new} |")
	lines += ["", "Full history: [stats/history.csv](stats/history.csv)", ""]
	with open(path, "w", encoding="utf-8") as f:
		f.write("\n".join(lines))


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("--markdown", help="Write a Markdown report to this file and update stats/history.csv")
	a = ap.parse_args()
	rows, data, addon = collect(fetchReleases())
	for tag, name, n in rows:
		print(f"{tag:<12} {name:<36} {n:>8}")
	print(f"\nVision data downloads (set-ups): {data}")
	print(f"Add-on downloads (installs and updates): {addon}")
	if a.markdown:
		today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
		writeMarkdown(os.path.join(ROOT, a.markdown), rows, data, addon, updateHistory(today, data, addon))


if __name__ == "__main__":
	main()
