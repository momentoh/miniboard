#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daosh.mycafe24.com 용 IT/품질 뉴스 자동 수집 & 워드프레스 게시 스크립트

동작 방식
---------
1. config/feeds.yaml 에 정의된 키워드(구글 뉴스 RSS 검색) 및 개별 RSS 주소에서
   기사 목록을 가져옵니다.
2. data/posted.json 에 기록된 "이미 올린 기사" 링크와 비교해 새 기사만 골라냅니다.
3. 새 기사가 있으면, 카테고리(IT / 품질)별로 묶어서 오늘 날짜의 "다이제스트"
   글 하나를 워드프레스 REST API로 발행합니다. (제목 + 요약 + 원문 링크만 사용,
   원문 전체를 긁어오지 않습니다 - 저작권 보호)
4. data/posted.json 을 갱신합니다. (GitHub Actions 워크플로우가 이 변경사항을
   자동으로 커밋합니다)

필요한 환경변수 (GitHub Actions Secrets 로 설정)
------------------------------------------------
WP_URL           예: https://daosh.mycafe24.com
WP_USERNAME      예: daosh
WP_APP_PASSWORD  워드프레스 프로필에서 발급받은 Application Password
"""

import base64
import html
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote

import feedparser
import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "feeds.yaml"
POSTED_PATH = ROOT / "data" / "posted.json"
KST = timezone(timedelta(hours=9))

MAX_POSTED_HISTORY = 2000  # posted.json 무한 증식 방지용 상한


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_posted():
    if POSTED_PATH.exists():
        with open(POSTED_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_posted(posted_links):
    POSTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 오래된 항목부터 잘라내어 파일이 무한히 커지지 않도록 함
    trimmed = list(posted_links)[-MAX_POSTED_HISTORY:]
    with open(POSTED_PATH, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)


def google_news_rss_url(query: str) -> str:
    q = quote(query)
    return f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"


def clean_summary(raw_html: str, max_sentences: int = 2, max_chars: int = 160) -> str:
    """RSS의 summary/description 필드에서 태그를 제거하고 앞부분만 남긴다.
    원문 전체를 재현하지 않도록 문장 수/글자 수 상한을 둔다."""
    if not raw_html:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()

    # 문장 단위로 자르기 (마침표/물음표/느낌표 기준)
    sentences = re.split(r"(?<=[.!?。])\s+", text)
    short = " ".join(sentences[:max_sentences]).strip()

    if len(short) > max_chars:
        short = short[:max_chars].rsplit(" ", 1)[0] + "…"
    return short


def fetch_feed_items(feed_url: str, max_items: int):
    parsed = feedparser.parse(feed_url)
    items = []
    for entry in parsed.entries[:max_items]:
        link = entry.get("link", "").strip()
        title = html.unescape(re.sub(r"\s+", " ", entry.get("title", "")).strip())
        summary_raw = entry.get("summary", "") or entry.get("description", "")
        source = ""
        if "source" in entry and hasattr(entry.source, "title"):
            source = entry.source.title
        elif " - " in title:
            # 구글 뉴스 검색 결과 제목은 보통 "기사제목 - 언론사명" 형태
            title, _, source = title.rpartition(" - ")
        if not link or not title:
            continue
        items.append(
            {
                "title": title.strip(),
                "link": link,
                "source": source.strip(),
                "summary": clean_summary(summary_raw),
            }
        )
    return items


def collect_new_items(config: dict, already_posted: set):
    """category -> [item, ...] 형태로 신규 기사만 수집"""
    by_category = {}

    sources = []
    for f in config.get("keyword_feeds") or []:
        sources.append(
            {
                "label": f["label"],
                "category": f.get("category", "IT"),
                "url": google_news_rss_url(f["query"]),
                "max_items": f.get("max_items", 5),
            }
        )
    for f in config.get("direct_feeds") or []:
        if not f:
            continue
        sources.append(
            {
                "label": f["label"],
                "category": f.get("category", "IT"),
                "url": f["url"],
                "max_items": f.get("max_items", 5),
            }
        )

    for src in sources:
        try:
            items = fetch_feed_items(src["url"], src["max_items"])
        except Exception as e:  # 개별 피드 오류가 전체를 막지 않도록
            print(f"[경고] '{src['label']}' 피드를 가져오지 못했습니다: {e}", file=sys.stderr)
            continue

        new_items = [it for it in items if it["link"] not in already_posted]
        if not new_items:
            continue

        by_category.setdefault(src["category"], []).append(
            {"label": src["label"], "items": new_items}
        )

    return by_category


def build_post_html(by_category: dict, today_str: str) -> str:
    parts = [f"<p>{today_str} 기준으로 수집된 IT/품질 관련 뉴스입니다. (제목 클릭 시 원문으로 이동합니다)</p>"]

    category_order = ["IT", "품질"]
    for category in category_order:
        groups = by_category.get(category)
        if not groups:
            continue
        parts.append(f"<h2>{html.escape(category)} 뉴스</h2>")
        for group in groups:
            parts.append(f"<h3>{html.escape(group['label'])}</h3>")
            parts.append("<ul>")
            for it in group["items"]:
                title = html.escape(it["title"])
                link = html.escape(it["link"], quote=True)
                source = html.escape(it["source"]) if it["source"] else ""
                summary = html.escape(it["summary"]) if it["summary"] else ""
                source_tag = f" <em>({source})</em>" if source else ""
                summary_tag = f"<br/>{summary}" if summary else ""
                parts.append(
                    f'<li><a href="{link}" target="_blank" rel="noopener noreferrer">{title}</a>{source_tag}{summary_tag}</li>'
                )
            parts.append("</ul>")

    return "\n".join(parts)


class WordPressClient:
    def __init__(self, base_url: str, username: str, app_password: str):
        self.base_url = base_url.rstrip("/")
        token = base64.b64encode(f"{username}:{app_password}".encode("utf-8")).decode("utf-8")
        self.headers = {"Authorization": f"Basic {token}"}

    def _get(self, path, params=None):
        r = requests.get(f"{self.base_url}{path}", headers=self.headers, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, path, json_body):
        r = requests.post(f"{self.base_url}{path}", headers=self.headers, json=json_body, timeout=30)
        r.raise_for_status()
        return r.json()

    def get_or_create_category(self, name: str) -> int:
        found = self._get("/wp-json/wp/v2/categories", params={"search": name, "per_page": 100})
        for cat in found:
            if cat["name"] == name:
                return cat["id"]
        created = self._post("/wp-json/wp/v2/categories", {"name": name})
        return created["id"]

    def create_post(self, title: str, content_html: str, category_ids: list, status: str = "publish"):
        body = {
            "title": title,
            "content": content_html,
            "status": status,
            "categories": category_ids,
        }
        return self._post("/wp-json/wp/v2/posts", body)


def main():
    wp_url = os.environ.get("WP_URL")
    wp_user = os.environ.get("WP_USERNAME")
    wp_app_password = os.environ.get("WP_APP_PASSWORD")

    if not all([wp_url, wp_user, wp_app_password]):
        print("[오류] WP_URL / WP_USERNAME / WP_APP_PASSWORD 환경변수가 필요합니다.", file=sys.stderr)
        sys.exit(1)

    config = load_config()
    already_posted = load_posted()

    by_category = collect_new_items(config, already_posted)

    total_new = sum(len(it) for groups in by_category.values() for it in [g["items"] for g in groups])
    if not by_category:
        print("새로 올릴 기사가 없습니다. 종료합니다.")
        return

    today_str = datetime.now(KST).strftime("%Y-%m-%d")
    title = f"[뉴스 브리핑] {today_str} IT · 품질 소식"
    content_html = build_post_html(by_category, today_str)

    wp = WordPressClient(wp_url, wp_user, wp_app_password)

    category_ids = []
    for cat_name in by_category.keys():
        try:
            category_ids.append(wp.get_or_create_category(cat_name))
        except Exception as e:
            print(f"[경고] 카테고리 '{cat_name}' 처리 실패: {e}", file=sys.stderr)

    result = wp.create_post(title, content_html, category_ids)
    print(f"[완료] 게시글 발행: {result.get('link', result.get('id'))}")

    # 새로 올라간 링크들을 posted.json에 기록
    newly_posted_links = [
        it["link"]
        for groups in by_category.values()
        for g in groups
        for it in g["items"]
    ]
    already_posted.update(newly_posted_links)
    save_posted(already_posted)
    print(f"[완료] 신규 기사 {len(newly_posted_links)}건을 기록했습니다.")


if __name__ == "__main__":
    main()
