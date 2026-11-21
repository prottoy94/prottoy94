#!/usr/bin/env python3
"""Render the animated GitHub stats cards used in the profile README.

The workflow in .github/workflows/stats.yml runs this on a schedule and
publishes the SVGs to the `output` branch:

    GH_TOKEN=<token> python scripts/generate_stats.py --user prottoy94 --out dist

To preview the design offline with built-in sample numbers:

    python scripts/generate_stats.py --sample --out preview

Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

# ------------------------------------------------------------------ theme --

SANS = "'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"
MONO = "'JetBrains Mono', 'Fira Code', Consolas, 'SF Mono', Menlo, 'DejaVu Sans Mono', monospace"

WHITE = "#ffffff"
CYAN = "#00f0ff"
BLUE = "#00d4ff"
VIOLET = "#7b61ff"
MAGENTA = "#ff00c8"
PINK = "#ff7ae0"
LABEL = "#b8c0ff"
MUTED = "#7f86c9"
TRACK = "#1f1d33"

BASE_CSS = """
.corner{animation:corner 3s ease-in-out infinite}
@keyframes corner{0%,100%{opacity:.35}50%{opacity:1}}
.gr{animation:gr 5s infinite steps(1)}
.gc{animation:gc 5s infinite steps(1)}
@keyframes gr{0%,100%{transform:translate(-1px,0)}88%{transform:translate(-4px,1px)}90%{transform:translate(3px,-1px)}92%{transform:translate(-5px,0)}94%{transform:translate(-1px,0)}}
@keyframes gc{0%,100%{transform:translate(1px,0)}88%{transform:translate(4px,-1px)}90%{transform:translate(-3px,1px)}92%{transform:translate(5px,0)}94%{transform:translate(1px,0)}}
.rise{animation:rise .7s ease-out backwards}
@keyframes rise{from{opacity:0;transform:translateY(8px)}}
.grow{transform-box:fill-box;transform-origin:left center;animation:grow 1.2s cubic-bezier(.2,.8,.2,1) backwards}
@keyframes grow{from{transform:scaleX(0)}}
.spin,.spinr,.orbit,.halo{transform-box:fill-box;transform-origin:center}
.spin{animation:spin 24s linear infinite}
.spinr{animation:spin 16s linear infinite reverse}
.orbit{animation:spin 3.2s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.halo{animation:halo 2.6s ease-out infinite}
@keyframes halo{from{transform:scale(1);opacity:.7}to{transform:scale(2.6);opacity:0}}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}
"""

ICON_ATTRS = f'fill="none" stroke="{BLUE}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"'


def _star_points() -> str:
    pts = []
    for k in range(10):
        a = math.radians(-90 + k * 36)
        r = 7.4 if k % 2 == 0 else 3.1
        pts.append(f"{8 + r * math.cos(a):.2f},{8.6 + r * math.sin(a):.2f}")
    return " ".join(pts)


ICONS = {
    "star": f'<polygon points="{_star_points()}"/>',
    "commit": '<circle cx="8" cy="8" r="3"/><path d="M1 8h4M11 8h4"/>',
    "pr": (
        '<circle cx="4" cy="3.5" r="1.8"/><circle cx="4" cy="12.5" r="1.8"/>'
        '<circle cx="12" cy="12.5" r="1.8"/>'
        '<path d="M4 5.3v5.4M12 10.7V6.5a2 2 0 0 0-2-2H7.5M9 3 7.5 4.5 9 6"/>'
    ),
    "issue": f'<circle cx="8" cy="8" r="6.5"/><circle cx="8" cy="8" r="1.4" fill="{BLUE}"/>',
    "repo": '<path d="M3 13.5V2.5A1.5 1.5 0 0 1 4.5 1H13v11H4.5A1.5 1.5 0 0 0 3 13.5a1.5 1.5 0 0 0 1.5 1.5H13v-3"/>',
}

FLAME = "M0,-14 C3,-9 9,-5 9,2 A9,9 0 0 1 -9,2 C-9,-3 -5,-6 -3,-11 C-2,-7 -0.5,-6 0.5,-5.5 C1,-8.5 0.5,-11.5 0,-14 Z"
FLAME_CORE = "M0,-3 C2.5,0 5,2.5 5,5.5 A5,5 0 0 1 -5,5.5 C-5,2.5 -2.5,0 0,-3 Z"


# ------------------------------------------------------------- svg card --

class Card:
    def __init__(self, width: int, height: int):
        self.w, self.h = width, height
        self.defs: list[str] = []
        self.css: list[str] = []
        self.body: list[str] = []
        self._n = 0

    def uid(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    def add(self, *parts: str) -> None:
        self.body.extend(parts)

    def svg(self, label: str) -> str:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}" font-family="{SANS}" role="img" '
            f'aria-label="{escape(label, {chr(34): "&quot;"})}">'
            f"<defs>{''.join(self.defs)}</defs>"
            f"<style>{BASE_CSS}{''.join(self.css)}</style>"
            f"{''.join(self.body)}</svg>\n"
        )

    def frame(self) -> None:
        """Dark background, rotating neon border, HUD corners."""
        w, h = self.w, self.h
        self.defs.append(
            '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
            '<stop offset="0" stop-color="#0c0b14"/><stop offset="1" stop-color="#07070c"/></linearGradient>'
            '<linearGradient id="edge" x1="0" y1="0" x2="1" y2="0">'
            f'<stop offset="0" stop-color="{BLUE}"/><stop offset=".5" stop-color="{VIOLET}"/>'
            f'<stop offset="1" stop-color="{MAGENTA}"/>'
            '<animateTransform attributeName="gradientTransform" type="rotate" values="0 .5 .5;360 .5 .5" '
            'dur="8s" repeatCount="indefinite"/></linearGradient>'
            '<linearGradient id="hline" x1="0" y1="0" x2="1" y2="0">'
            f'<stop offset="0" stop-color="{BLUE}"/><stop offset=".6" stop-color="{MAGENTA}" stop-opacity=".6"/>'
            f'<stop offset="1" stop-color="{MAGENTA}" stop-opacity="0"/></linearGradient>'
            '<linearGradient id="numG" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset=".2" stop-color="{WHITE}"/><stop offset="1" stop-color="{BLUE}"/></linearGradient>'
            '<linearGradient id="numP" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset=".2" stop-color="{WHITE}"/><stop offset="1" stop-color="{PINK}"/></linearGradient>'
            '<filter id="glow" x="-50%" y="-50%" width="200%" height="200%">'
            '<feGaussianBlur stdDeviation="2.4" result="b"/>'
            '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
        )
        k = 14
        corners = (
            f"M8,{8 + k}V8H{8 + k} M{w - 8 - k},8H{w - 8}V{8 + k} "
            f"M{w - 8},{h - 8 - k}V{h - 8}H{w - 8 - k} M{8 + k},{h - 8}H8V{h - 8 - k}"
        )
        self.add(
            f'<rect width="{w}" height="{h}" rx="12" fill="url(#bg)"/>',
            f'<rect x=".75" y=".75" width="{w - 1.5}" height="{h - 1.5}" rx="11.5" fill="none" '
            'stroke="url(#edge)" stroke-width="1.5"/>',
            f'<path class="corner" d="{corners}" fill="none" stroke="{CYAN}" stroke-width="2" stroke-linecap="round"/>',
        )

    def title(self, text: str, underline: int, x: int = 25, y: int = 38) -> None:
        """Title with a permanent RGB split and a periodic glitch jolt."""
        t = escape(text)
        self.add(
            f'<g font-family="{MONO}" font-size="15" font-weight="700" letter-spacing="1.5">'
            f'<text class="gr" x="{x}" y="{y}" fill="{MAGENTA}" opacity=".8">{t}</text>'
            f'<text class="gc" x="{x}" y="{y}" fill="{CYAN}" opacity=".8">{t}</text>'
            f'<text x="{x}" y="{y}" fill="{WHITE}">{t}</text></g>',
            f'<rect class="grow" x="{x}" y="{y + 9}" width="{underline}" height="2" rx="1" '
            'fill="url(#hline)" style="animation-delay:.15s"/>',
        )

    def odometer(self, text: str, x: float, y: float, size: float, anchor: str = "end",
                 fill: str = WHITE, delay: float = 0.0) -> None:
        """Number whose digits roll into place like a slot machine.

        The final digit position is the element's own transform, so the number
        is correct even where animations are disabled.
        """
        adv = size * 0.62
        lh = round(size * 1.3, 1)
        total = adv * len(text)
        start = {"end": x - total, "middle": x - total / 2, "start": x}[anchor]
        clip = self.uid("oc")
        self.defs.append(
            f'<clipPath id="{clip}"><rect x="{-adv * 0.75:.1f}" y="{-size * 0.95:.1f}" '
            f'width="{adv * 1.5:.1f}" height="{lh}"/></clipPath>'
        )
        parts = [f'<g font-family="{MONO}" font-size="{size}" font-weight="700" fill="{fill}" text-anchor="middle">']
        di = 0
        for i, ch in enumerate(text):
            cx = start + (i + 0.5) * adv
            if not ch.isdigit():
                parts.append(f'<text x="{cx:.1f}" y="{y}">{escape(ch)}</text>')
                continue
            spins = 10 + int(ch)
            end = -spins * lh
            name = self.uid("od")
            dur = 1.1 + 0.18 * di
            self.css.append(
                f"@keyframes {name}{{from{{transform:translateY(0)}}to{{transform:translateY({end:.1f}px)}}}}"
            )
            strip = "".join(f'<text y="{k * lh:.1f}">{k % 10}</text>' for k in range(spins + 1))
            parts.append(
                f'<g transform="translate({cx:.1f},{y})" clip-path="url(#{clip})">'
                f'<g transform="translate(0,{end:.1f})" '
                f'style="animation:{name} {dur:.2f}s cubic-bezier(.12,.8,.24,1) {delay:.2f}s backwards">'
                f"{strip}</g></g>"
            )
            di += 1
        parts.append("</g>")
        self.add("".join(parts))


# ------------------------------------------------------------------ cards --

def render_stats(m: dict) -> str:
    c = Card(500, 200)
    c.frame()
    name = (m["name"] or m["login"]).upper()
    if len(name) > 16:
        name = name[:15] + "…"
    c.title(f"{name} // GITHUB STATS", underline=230)

    rows = [
        ("star", "Total Stars Earned", m["stars"]),
        ("commit", "Total Commits (last year)", m["commits"]),
        ("pr", "Total PRs", m["prs"]),
        ("issue", "Total Issues", m["issues"]),
        ("repo", "Contributed to (last year)", m["contributed"]),
    ]
    for i, (icon, label, value) in enumerate(rows):
        y = 76 + i * 26
        delay = 0.3 + i * 0.12
        c.add(
            f'<g class="rise" style="animation-delay:{delay:.2f}s">'
            f'<g transform="translate(25,{y - 12})" {ICON_ATTRS}>{ICONS[icon]}</g>'
            f'<text x="50" y="{y}" fill="{LABEL}" font-size="13.5" font-weight="600">{escape(label)}</text></g>'
        )
        c.odometer(f"{value:,}", 318, y, 15, "end", CYAN, delay + 0.1)

    # Rank ring: draws in, glows, has an orbiting spark and two counter-rotating HUD rings.
    r = 44
    circ = 2 * math.pi * r
    progress = max(3.0, min(100.0, 100 - m["percentile"]))
    offset = circ * (1 - progress / 100)
    c.defs.append(
        '<linearGradient id="ringG" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{CYAN}"/><stop offset="1" stop-color="{MAGENTA}"/></linearGradient>'
    )
    c.css.append(
        f".ring{{animation:ring 1.8s cubic-bezier(.2,.8,.2,1) .5s backwards}}"
        f"@keyframes ring{{from{{stroke-dashoffset:{circ:.1f}}}}}"
    )
    grade = escape(m["grade"])
    c.add(
        '<g class="rise" style="animation-delay:.2s"><g transform="translate(415,108)">'
        f'<circle class="spin" r="58" fill="none" stroke="{VIOLET}" stroke-opacity=".6" stroke-width="1.2" stroke-dasharray="3 7"/>'
        f'<circle class="spinr" r="34" fill="none" stroke="{BLUE}" stroke-opacity=".45" stroke-width="1" stroke-dasharray="1 5"/>'
        f'<circle r="{r}" fill="none" stroke="{TRACK}" stroke-width="7"/>'
        f'<circle class="ring" r="{r}" fill="none" stroke="url(#ringG)" stroke-width="7" stroke-linecap="round" '
        f'stroke-dasharray="{circ:.1f}" stroke-dashoffset="{offset:.1f}" transform="rotate(-90)" filter="url(#glow)"/>'
        f'<circle class="orbit" r="{r}" fill="none" stroke="{WHITE}" stroke-opacity=".85" stroke-width="2.5" '
        f'stroke-linecap="round" stroke-dasharray="5 {circ - 5:.1f}"/>'
        f'<text y="-14" text-anchor="middle" font-family="{MONO}" font-size="9" letter-spacing="3" fill="{MUTED}">RANK</text>'
        f'<g font-family="{MONO}" font-size="26" font-weight="800" text-anchor="middle">'
        f'<text class="gr" y="16" fill="{MAGENTA}" opacity=".85">{grade}</text>'
        f'<text class="gc" y="16" fill="{CYAN}" opacity=".85">{grade}</text>'
        f'<text y="16" fill="{WHITE}">{grade}</text></g></g></g>'
    )
    return c.svg(f"{m['name'] or m['login']}'s GitHub stats")


def render_languages(m: dict) -> str:
    c = Card(500, 200)
    c.frame()
    c.title("MOST USED LANGUAGES", underline=200)
    langs = m["languages"]
    if not langs:
        c.add(f'<text x="250" y="115" text-anchor="middle" fill="{MUTED}" font-size="14">No language data yet</text>')
        return c.svg("Most used languages")

    bx, by, bw, bh = 25, 62, 450, 10
    c.defs.append(
        f'<clipPath id="barClip"><rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="5"/></clipPath>'
        '<linearGradient id="shineG" x1="0" y1="0" x2="1" y2="0">'
        '<stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".75"/>'
        '<stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>'
    )
    c.css.append(
        ".shine{animation:shine 4s ease-in-out 1.6s infinite}"
        f"@keyframes shine{{from{{transform:translateX(0)}}55%,100%{{transform:translateX({bw + 90}px)}}}}"
    )
    segs, x = [], float(bx)
    for lang in langs:
        w = bw * lang["pct"] / 100
        segs.append(f'<rect x="{x:.2f}" y="{by}" width="{w + 0.6:.2f}" height="{bh}" fill="{lang["color"]}"/>')
        x += w
    c.add(
        f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="5" fill="{TRACK}"/>'
        f'<g clip-path="url(#barClip)"><g class="grow" style="animation-delay:.3s">{"".join(segs)}</g>'
        f'<rect class="shine" x="{bx - 80}" y="{by}" width="70" height="{bh}" fill="url(#shineG)"/></g>'
    )

    for i, lang in enumerate(langs):
        col, row = i % 2, i // 2
        x = 25 + col * 235
        y = 102 + row * 36
        delay = 0.5 + i * 0.1
        color = lang["color"]
        mini = max(2.0, 198 * lang["pct"] / 100)
        c.add(
            f'<g class="rise" style="animation-delay:{delay:.2f}s">'
            f'<circle class="halo" cx="{x + 5}" cy="{y - 4.5}" r="5" fill="{color}" style="animation-delay:{1.2 + i * 0.4:.1f}s"/>'
            f'<circle cx="{x + 5}" cy="{y - 4.5}" r="5" fill="{color}"/>'
            f'<text x="{x + 17}" y="{y}" fill="#d6dbff" font-size="12.5" font-weight="600">{escape(lang["name"])}</text>'
            f'<text x="{x + 215}" y="{y}" text-anchor="end" font-family="{MONO}" font-size="12" fill="{CYAN}">{lang["pct"]:.2f}%</text>'
            f'<rect x="{x + 17}" y="{y + 7}" width="198" height="4" rx="2" fill="{TRACK}"/>'
            f'<rect class="grow" x="{x + 17}" y="{y + 7}" width="{mini:.1f}" height="4" rx="2" fill="{color}" '
            f'style="animation-delay:{delay + 0.2:.2f}s"/></g>'
        )
    return c.svg("Most used languages")


def _side_panel(c: Card, cx: int, value: int, label: str, rng: str, delay: float) -> None:
    c.odometer(f"{value:,}", cx, 122, 34, "middle", "url(#numG)", delay)
    c.add(
        f'<g class="rise" style="animation-delay:{delay:.2f}s">'
        f'<text x="{cx}" y="157" text-anchor="middle" fill="{LABEL}" font-size="14" font-weight="600">{escape(label)}</text>'
        f'<text x="{cx}" y="181" text-anchor="middle" fill="{MUTED}" font-size="12">{escape(rng)}</text></g>'
    )


def render_streak(m: dict) -> str:
    W, H = 900, 220
    c = Card(W, H)
    c.frame()
    c.title("CONTRIBUTION STREAK", underline=210)
    c.add(
        f'<text x="{W - 25}" y="38" text-anchor="end" font-family="{MONO}" font-size="11" '
        f'letter-spacing="1" fill="{MUTED}">@{escape(m["login"])}</text>'
    )
    today = m["today"]

    # Dividers with a glowing blip travelling along them.
    c.defs.append(
        '<linearGradient id="vline" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{VIOLET}" stop-opacity="0"/><stop offset=".5" stop-color="{VIOLET}"/>'
        f'<stop offset="1" stop-color="{VIOLET}" stop-opacity="0"/></linearGradient>'
    )
    c.css.append(
        ".blip{animation:blip 3.4s ease-in-out infinite alternate}"
        "@keyframes blip{from{transform:translateY(0)}to{transform:translateY(110px)}}"
    )
    for i, x in enumerate((300, 600)):
        c.add(
            f'<rect x="{x - 0.5}" y="72" width="1" height="120" fill="url(#vline)"/>'
            f'<circle class="blip" cx="{x}" cy="77" r="2.2" fill="{CYAN}" filter="url(#glow)" '
            f'style="animation-delay:{-1.7 * i:.1f}s"/>'
        )

    total_rng = f"{fmt_date(m['first_day'], today, True)} - Present" if m["first_day"] else "No contributions yet"
    _side_panel(c, 150, m["total"], "Total Contributions", total_rng, 0.35)
    _side_panel(c, 750, m["longest"], "Longest Streak", span(m["longest_start"], m["longest_end"], today), 0.65)

    # Current streak: gapped ring that draws in, flickering flame, rising embers.
    cx, cy, r = 450, 104, 40
    circ = 2 * math.pi * r
    gap = 30
    dash = f'stroke-dasharray="{circ - gap:.1f} {gap}" stroke-dashoffset="{-gap / 2:.1f}" transform="rotate(-90)"'
    c.defs.append(
        '<linearGradient id="sringG" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{CYAN}"/><stop offset=".5" stop-color="{VIOLET}"/>'
        f'<stop offset="1" stop-color="{MAGENTA}"/></linearGradient>'
        '<linearGradient id="flameG" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#ffd166"/><stop offset=".55" stop-color="#ff8a00"/>'
        f'<stop offset="1" stop-color="{MAGENTA}"/></linearGradient>'
    )
    c.css.append(
        f".sring{{animation:sring 1.6s cubic-bezier(.2,.8,.2,1) .4s backwards}}"
        f"@keyframes sring{{from{{stroke-dasharray:0 {circ:.1f}}}}}"
        ".flame,.core{transform-box:fill-box;transform-origin:50% 100%}"
        ".flame{animation:flick 1.3s ease-in-out infinite alternate}"
        ".core{animation:flick .8s ease-in-out infinite alternate-reverse}"
        "@keyframes flick{0%{transform:scale(1,1) skewX(0)}33%{transform:scale(.94,1.08) skewX(-4deg)}"
        "66%{transform:scale(1.04,.95) skewX(3deg)}100%{transform:scale(.97,1.1) skewX(-2deg)}}"
    )
    embers = []
    for j, (dx, dl) in enumerate(((-6, 0.0), (5, 0.7), (9, 1.4))):
        c.css.append(
            f"@keyframes em{j}{{0%{{transform:translate(0,0);opacity:0}}15%{{opacity:1}}"
            f"100%{{transform:translate({dx}px,-26px);opacity:0}}}}"
        )
        embers.append(
            f'<circle cx="{dx / 3:.1f}" cy="{-r - 12}" r="1.4" fill="#ffb86b" '
            f'style="animation:em{j} 2.1s ease-out {dl}s infinite;opacity:0"/>'
        )
    c.add(
        f'<g class="rise" style="animation-delay:.2s"><g transform="translate({cx},{cy})">'
        f'<circle r="{r}" fill="none" stroke="{TRACK}" stroke-width="6" {dash}/>'
        f'<circle class="sring" r="{r}" fill="none" stroke="url(#sringG)" stroke-width="6" stroke-linecap="round" '
        f'{dash} filter="url(#glow)"/>'
        f'<circle class="spin" r="{r + 10}" fill="none" stroke="{MAGENTA}" stroke-opacity=".35" stroke-width="1" stroke-dasharray="2 8"/>'
        f'{"".join(embers)}'
        f'<g transform="translate(0,{-r})" filter="url(#glow)">'
        f'<path class="flame" d="{FLAME}" fill="url(#flameG)"/><path class="core" d="{FLAME_CORE}" fill="#ffe08a"/></g>'
        "</g></g>"
    )
    c.odometer(str(m["current"]), cx, cy + 12, 30, "middle", "url(#numP)", 0.6)
    cur_rng = span(m["current_start"], m["current_end"], today) if m["current"] else "Start a new streak today"
    c.add(
        '<g class="rise" style="animation-delay:.5s">'
        f'<text x="{cx}" y="{cy + r + 28}" text-anchor="middle" fill="{PINK}" font-size="14" font-weight="700">Current Streak</text>'
        f'<text x="{cx}" y="{cy + r + 50}" text-anchor="middle" fill="{MUTED}" font-size="12">{escape(cur_rng)}</text></g>'
    )

    return c.svg("Contribution streak")


# ------------------------------------------------------------------- data --

PROFILE_QUERY = """
query($login: String!) {
  user(login: $login) {
    name
    login
    createdAt
    followers { totalCount }
    pullRequests { totalCount }
    issues { totalCount }
    repositoriesContributedTo(first: 1, contributionTypes: [COMMIT, ISSUE, PULL_REQUEST, REPOSITORY]) { totalCount }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestReviewContributions
      contributionCalendar { weeks { contributionDays { date contributionCount } } }
    }
  }
}
"""

REPOS_QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    repositories(first: 100, after: $after, ownerAffiliations: OWNER, isFork: false) {
      pageInfo { hasNextPage endCursor }
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""


def history_query(created: datetime, now: datetime) -> str:
    """One contributionsCollection per calendar year (the API caps each at one year)."""
    parts = []
    for year in range(created.year, now.year + 1):
        start = f"{year}-01-01T00:00:00Z"
        end = f"{year}-12-31T23:59:59Z" if year < now.year else now.strftime("%Y-%m-%dT%H:%M:%SZ")
        parts.append(
            f'y{year}: contributionsCollection(from: "{start}", to: "{end}") '
            "{ contributionCalendar { weeks { contributionDays { date contributionCount } } } }"
        )
    return "query($login: String!) { user(login: $login) { " + " ".join(parts) + " } }"


def gql(token: str, query: str, variables: dict) -> dict:
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "profile-stats-cards",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        raise SystemExit(f"GraphQL error: {payload['errors']}")
    return payload["data"]


def fetch_raw(login: str, token: str) -> dict:
    profile = gql(token, PROFILE_QUERY, {"login": login})["user"]
    if profile is None:
        raise SystemExit(f"GitHub user {login!r} not found")
    repos, after = [], None
    while True:
        page = gql(token, REPOS_QUERY, {"login": login, "after": after})["user"]["repositories"]
        repos.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    now = datetime.now(timezone.utc)
    created = datetime.fromisoformat(profile["createdAt"].replace("Z", "+00:00"))
    history = gql(token, history_query(created, now), {"login": login})["user"]
    return {"profile": profile, "repos": repos, "history": history}


def sample_raw() -> dict:
    """GraphQL-shaped sample data matching the numbers on the current cards.

    The day-by-day pattern is simulated; totals and streaks match.
    """
    today = date(2026, 11, 20)
    first = date(2025, 3, 12)
    rng = random.Random(94)
    counts: dict[date, int] = {}
    d = date(2025, 1, 1)
    while d <= today:
        if d < first:
            counts[d] = 0
        elif d == first:
            counts[d] = 2
        else:
            counts[d] = rng.choice([1, 1, 1, 2, 2, 3, 4, 6]) if rng.random() < 0.2 else 0
        d += timedelta(days=1)

    protected: set[date] = {first}

    def force(a: date, b: date, active: bool) -> None:
        x = a
        while x <= b:
            counts[x] = (counts[x] or rng.choice([1, 2, 3])) if active else 0
            if active:
                protected.add(x)
            x += timedelta(days=1)

    force(date(2026, 9, 25), date(2026, 9, 25), False)
    force(date(2026, 10, 10), date(2026, 10, 10), False)
    force(date(2026, 11, 12), date(2026, 11, 12), False)
    force(date(2026, 9, 26), date(2026, 10, 9), True)
    force(date(2026, 11, 13), today, True)

    target = 307
    while (total := sum(counts.values())) != target:
        if total > target:
            multi = [k for k, v in counts.items() if v > 1]
            if multi:
                counts[rng.choice(multi)] -= 1
            else:
                counts[rng.choice([k for k, v in counts.items() if v == 1 and k not in protected])] = 0
        else:
            counts[rng.choice([k for k, v in counts.items() if v > 0])] += 1

    def days_json(a: date, b: date) -> list[dict]:
        out, x = [], a
        while x <= b:
            out.append({"date": x.isoformat(), "contributionCount": counts.get(x, 0)})
            x += timedelta(days=1)
        return out

    start = today - timedelta(days=364)
    start -= timedelta(days=(start.weekday() + 1) % 7)  # back to Sunday
    days = days_json(start, today)
    weeks = [{"contributionDays": days[i:i + 7]} for i in range(0, len(days), 7)]

    langs = [
        ("Jupyter Notebook", "#DA5B0B", 9487), ("GDScript", "#355570", 269),
        ("TypeScript", "#3178c6", 105), ("C++", "#f34b7d", 75),
        ("Python", "#3572A5", 33), ("C#", "#178600", 31),
    ]
    return {
        "profile": {
            "name": "Prottoy Roy",
            "login": "prottoy94",
            "createdAt": "2025-01-10T00:00:00Z",
            "followers": {"totalCount": 3},
            "pullRequests": {"totalCount": 11},
            "issues": {"totalCount": 0},
            "repositoriesContributedTo": {"totalCount": 1},
            "contributionsCollection": {
                "totalCommitContributions": 235,
                "totalPullRequestReviewContributions": 0,
                "contributionCalendar": {"weeks": weeks},
            },
        },
        "repos": [{
            "stargazerCount": 0,
            "languages": {"edges": [{"size": s, "node": {"name": n, "color": c}} for n, c, s in langs]},
        }],
        "history": {
            f"y{y}": {"contributionCalendar": {"weeks": [{"contributionDays": days_json(
                date(y, 1, 1), min(date(y, 12, 31), today))}]}}
            for y in (2025, 2026)
        },
    }


# ---------------------------------------------------------------- metrics --

def rank(commits: int, prs: int, issues: int, reviews: int, stars: int, followers: int) -> tuple[str, float]:
    """Same formula github-readme-stats uses, so the grade stays comparable."""
    def expo(x: float) -> float:
        return 1 - 2 ** -x

    def lognorm(x: float) -> float:
        return x / (1 + x)

    score = (
        2 * expo(commits / 250) + 3 * expo(prs / 50) + 1 * expo(issues / 25)
        + 1 * expo(reviews / 2) + 4 * lognorm(stars / 50) + 1 * lognorm(followers / 10)
    ) / 12
    pct = (1 - score) * 100
    for threshold, level in zip((1, 12.5, 25, 37.5, 50, 62.5, 75, 87.5, 100),
                                ("S", "A+", "A", "A-", "B+", "B", "B-", "C+", "C")):
        if pct <= threshold:
            return level, pct
    return "C", pct


def fmt_date(d: date, today: date, force_year: bool = False) -> str:
    s = f"{d:%b} {d.day}"
    return f"{s}, {d.year}" if force_year or d.year != today.year else s


def span(a: date | None, b: date | None, today: date) -> str:
    if not a or not b:
        return "No streak yet"
    return fmt_date(a, today) if a == b else f"{fmt_date(a, today)} - {fmt_date(b, today)}"


def streak_stats(daily: dict[date, int]) -> dict:
    if not daily:
        t = datetime.now(timezone.utc).date()
        return dict(total=0, first_day=None, today=t, current=0, current_start=None, current_end=None,
                    longest=0, longest_start=None, longest_end=None)
    first, last = min(daily), max(daily)
    seq, d = [], first
    while d <= last:
        seq.append((d, daily.get(d, 0)))
        d += timedelta(days=1)

    best, run, run_start = (0, None, None), 0, None
    for d, n in seq:
        if n > 0:
            if run == 0:
                run_start = d
            run += 1
            if run > best[0]:
                best = (run, run_start, d)
        else:
            run = 0

    # Today without contributions doesn't break the streak yet.
    i = len(seq) - 1
    if seq[i][1] == 0:
        i -= 1
    cur_end = seq[i][0] if i >= 0 else None
    cur = 0
    while i >= 0 and seq[i][1] > 0:
        cur += 1
        i -= 1
    cur_start = seq[i + 1][0] if cur else None

    return dict(
        total=sum(n for _, n in seq),
        first_day=next((d for d, n in seq if n > 0), None),
        today=last,
        current=cur, current_start=cur_start, current_end=cur_end if cur else None,
        longest=best[0], longest_start=best[1], longest_end=best[2],
    )


def calendar_days(collection: dict):
    for week in collection["contributionCalendar"]["weeks"]:
        for day in week["contributionDays"]:
            yield date.fromisoformat(day["date"]), day["contributionCount"]


def build_metrics(raw: dict) -> dict:
    p = raw["profile"]
    cc = p["contributionsCollection"]
    repos = raw["repos"]

    sizes: dict[str, dict] = {}
    for repo in repos:
        for edge in (repo.get("languages") or {}).get("edges", []):
            name = edge["node"]["name"]
            entry = sizes.setdefault(name, {"name": name, "color": edge["node"]["color"] or "#8b8b8b", "size": 0})
            entry["size"] += edge["size"]
    top = sorted(sizes.values(), key=lambda e: e["size"], reverse=True)[:6]
    top_total = sum(e["size"] for e in top) or 1
    languages = [{"name": e["name"], "color": e["color"], "pct": e["size"] * 100 / top_total} for e in top]

    weeks = [
        [(date.fromisoformat(day["date"]), day["contributionCount"]) for day in wk["contributionDays"]]
        for wk in cc["contributionCalendar"]["weeks"]
    ]
    weeks = [wk for wk in weeks if wk]

    daily: dict[date, int] = {}
    for coll in (raw.get("history") or {}).values():
        if coll:
            for d, n in calendar_days(coll):
                daily[d] = n
    for wk in weeks:
        for d, n in wk:
            daily[d] = n

    stars = sum(r["stargazerCount"] for r in repos)
    commits = cc["totalCommitContributions"]
    prs = p["pullRequests"]["totalCount"]
    issues = p["issues"]["totalCount"]
    followers = p["followers"]["totalCount"]
    reviews = cc["totalPullRequestReviewContributions"]
    grade, pct = rank(commits, prs, issues, reviews, stars, followers)

    return dict(
        name=p.get("name") or "", login=p["login"],
        stars=stars, commits=commits, prs=prs, issues=issues,
        contributed=p["repositoriesContributedTo"]["totalCount"],
        grade=grade, percentile=pct, languages=languages,
        **streak_stats(daily),
    )


# ------------------------------------------------------------------- main --

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user", default=os.environ.get("GITHUB_REPOSITORY_OWNER"), help="GitHub login")
    ap.add_argument("--out", default="dist", help="output directory")
    ap.add_argument("--sample", action="store_true", help="use built-in sample data (no network)")
    args = ap.parse_args()

    if args.sample:
        raw = sample_raw()
    else:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token or not args.user:
            ap.error("--user and a GH_TOKEN environment variable are required unless --sample is used")
        raw = fetch_raw(args.user, token)

    metrics = build_metrics(raw)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for filename, svg in (
        ("stats.svg", render_stats(metrics)),
        ("languages.svg", render_languages(metrics)),
        ("streak.svg", render_streak(metrics)),
    ):
        (out / filename).write_text(svg, encoding="utf-8")
        print(f"wrote {out / filename}")


if __name__ == "__main__":
    main()
