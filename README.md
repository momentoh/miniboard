# miniboard — IT/품질 뉴스 자동 브리핑

[daosh.mycafe24.com](https://daosh.mycafe24.com/) 에 매일 IT 및 소프트웨어 품질 관련 뉴스를
자동으로 수집해서 게시하는 봇입니다. GitHub Actions가 매일 아침(KST 07:00) 자동으로
실행되어, 구글 뉴스 RSS 검색으로 최신 기사를 모으고 "제목 + 짧은 요약 + 원문 링크"
형태로 워드프레스에 새 글을 발행합니다. (저작권 보호를 위해 원문 전체는 가져오지 않습니다)

## 동작 방식

1. `config/feeds.yaml` 에 정의된 키워드/RSS 주소에서 기사를 수집
2. `data/posted.json` 과 비교해 이미 올린 기사는 제외
3. 새 기사가 있으면 오늘 날짜의 "뉴스 브리핑" 글 하나로 묶어서 워드프레스에 발행
   (카테고리: IT / 품질 — 없으면 자동 생성됨)
4. `data/posted.json` 갱신 후 자동 커밋

## 최초 설정 (딱 한 번만 하면 됩니다)

### 1) 워드프레스 애플리케이션 비밀번호 발급

`wp-admin` 로그인 → 프로필 편집 → 맨 아래 "Application Passwords" 섹션에서
새 비밀번호 발급 (자세한 방법은 워드프레스 공식 문서 참고)

### 2) GitHub 저장소에 Secrets 등록

저장소 페이지 → **Settings → Secrets and variables → Actions → New repository secret**
아래 3개를 각각 등록합니다.

| Secret 이름 | 값 |
|---|---|
| `WP_URL` | `https://daosh.mycafe24.com` |
| `WP_USERNAME` | 워드프레스 관리자 아이디 |
| `WP_APP_PASSWORD` | 1번에서 발급받은 애플리케이션 비밀번호 |

### 3) 동작 확인

저장소 **Actions 탭 → Daily IT/Quality News Digest → Run workflow** 버튼으로
수동 실행해서 정상적으로 글이 올라오는지 확인하세요. 이후엔 매일 자동으로 실행됩니다.

## 뉴스 소스(피드) 수정하기

`config/feeds.yaml` 파일만 수정하면 됩니다.

- `keyword_feeds`: 키워드로 구글 뉴스를 검색 (언론사 특정 불필요, 가장 간편)
- `direct_feeds`: 특정 언론사/기관의 RSS 주소를 알고 있을 때 직접 등록

각 항목의 `category` 는 `IT` 또는 `품질` 중 하나로 지정하면 워드프레스 카테고리로
자동 매핑됩니다. 새 카테고리 이름을 넣으면 자동으로 만들어집니다.

## 로컬에서 직접 테스트하기

```bash
pip install -r requirements.txt
export WP_URL="https://daosh.mycafe24.com"
export WP_USERNAME="daosh"
export WP_APP_PASSWORD="xxxx xxxx xxxx xxxx xxxx xxxx"
python scripts/rss_to_wp.py
```

## 참고

- 실행 주기를 바꾸려면 `.github/workflows/daily-digest.yml` 의 `cron` 값을 수정하세요.
- 워드프레스 기본 REST API(`/wp-json/wp/v2/posts`)를 사용합니다. 미니게시판(KBoard)은
  자체 REST API를 공식 지원하지 않아 대신 "IT"/"품질" 카테고리의 일반 포스트로 발행됩니다.
