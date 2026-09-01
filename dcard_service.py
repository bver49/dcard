"""Dcard 文章統計核心，供既有命令列入口使用。

ChatGPT App 使用的 dcard-post-counts-js skill 不會載入本檔案；它有自己的
JavaScript 瀏覽器 runner。保留本檔案是為了讓 dcardParserNew.py 的既有修改
仍然可以運作。
"""

from __future__ import annotations

import csv
import io
import json
import random
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Union
from urllib.parse import urlencode

import undetected_chromedriver as uc
from selenium import webdriver


BOARD_NAME_MAPPING: Dict[int, str] = {
    1: "mood",
    2: "relationship",
    3: "mlb",
    4: "nba",
    5: "cpbl",
    6: "baseball",
    7: "basketball",
    8: "sportsevents",
}

BOARD_DISPLAY_NAMES: Dict[str, str] = {
    "mood": "心情",
    "relationship": "感情",
    "mlb": "MLB",
    "nba": "NBA",
    "cpbl": "中職",
    "baseball": "棒球",
    "basketball": "籃球",
    "sportsevents": "大型賽事",
}

BOARD_ALIASES: Dict[str, str] = {}
for _number, _code in BOARD_NAME_MAPPING.items():
    BOARD_ALIASES[str(_number)] = _code
    BOARD_ALIASES[_code] = _code
    BOARD_ALIASES[BOARD_DISPLAY_NAMES[_code].lower()] = _code
BOARD_ALIASES.update(
    {
        "心情版": "mood",
        "感情版": "relationship",
        "mlb版": "mlb",
        "nba版": "nba",
        "中職版": "cpbl",
        "棒球版": "baseball",
        "籃球版": "basketball",
        "大型賽事版": "sportsevents",
    }
)

MAX_DAYS = 90
TAIPEI_TIMEZONE = timezone(timedelta(hours=8))


class DcardScraperError(RuntimeError):
    """Dcard 抓取失敗。"""


def normalize_boards(boards: Union[str, int, Iterable[Union[str, int]]]) -> List[str]:
    if isinstance(boards, (str, int)):
        values: Iterable[Union[str, int]] = [boards]
    else:
        values = boards

    normalized: List[str] = []
    for raw_board in values:
        for item in re.split(r"[,，、\s]+", str(raw_board).strip().lower()):
            if not item:
                continue
            code = BOARD_ALIASES.get(item)
            if code is None:
                raise ValueError(
                    "無法辨識看板『{}』，可用看板：{}".format(
                        raw_board, ", ".join(BOARD_DISPLAY_NAMES.values())
                    )
                )
            if code not in normalized:
                normalized.append(code)
    if not normalized:
        raise ValueError("至少需要指定一個看板")
    return normalized


def validate_days(days: Union[str, int]) -> int:
    if isinstance(days, bool):
        raise ValueError("天數必須是正整數")
    try:
        value = int(days)
    except (TypeError, ValueError) as error:
        raise ValueError("天數必須是正整數") from error
    if value < 1 or value > MAX_DAYS:
        raise ValueError("天數必須介於 1 到 {} 天".format(MAX_DAYS))
    return value


def build_date_range(
    days: Union[str, int],
    include_today: bool = False,
    today: Optional[Union[date, datetime]] = None,
) -> List[date]:
    day_count = validate_days(days)
    if today is None:
        current_date = datetime.now(TAIPEI_TIMEZONE).date()
    elif isinstance(today, datetime):
        current_date = today.date()
    else:
        current_date = today
    last_date = current_date if include_today else current_date - timedelta(days=1)
    first_date = last_date - timedelta(days=day_count - 1)
    return [first_date + timedelta(days=index) for index in range(day_count)]


def parse_post_date(created_at: str) -> date:
    parsed = datetime.fromisoformat(created_at.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(TAIPEI_TIMEZONE).date()


@dataclass
class CountResult:
    board_codes: List[str]
    dates: List[str]
    counts: Dict[str, Dict[str, int]]
    generated_at: str
    include_today: bool = False

    def to_csv(self) -> str:
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["board_code", "board_name"] + self.dates + ["total"])
        for board_code in self.board_codes:
            values = [self.counts[board_code].get(day, 0) for day in self.dates]
            writer.writerow(
                [board_code, BOARD_DISPLAY_NAMES[board_code]] + values + [sum(values)]
            )
        return "\ufeff" + output.getvalue()

    def write_csv(self, path: Union[str, Path]) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8-sig", newline="") as output:
            output.write(self.to_csv().lstrip("\ufeff"))
        return target


FETCH_PAGE_SCRIPT = """
const callback = arguments[arguments.length - 1];
const query = arguments[0];
fetch("https://www.dcard.tw/service/api/v2/globalPaging/page?" + query, {
  credentials: "include"
})
  .then((response) => {
    if (!response.ok) throw new Error("HTTP " + response.status);
    return response.json();
  })
  .then((jsonData) => callback(jsonData))
  .catch((error) => callback({"__error": String(error)}));
"""

LIST_KEY_SCRIPT = """
const node = document.getElementById('__NEXT_DATA__');
if (!node) return null;
try {
  const data = JSON.parse(node.textContent);
  return data?.props?.pageProps?.tabs?.[1]?.payload?.listKey || null;
} catch (error) {
  return null;
}
"""


class DcardScraper:
    def __init__(
        self,
        log_dir: Union[str, Path] = ".",
        version_main: Optional[int] = None,
        browser_factory: Optional[Callable[..., Any]] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        random_generator: Optional[random.Random] = None,
        initial_sleep: Sequence[int] = (5, 10),
        page_sleep: Sequence[int] = (10, 25),
        progress_fn: Callable[[str], None] = print,
    ) -> None:
        self.log_dir = Path(log_dir)
        self.version_main = version_main
        self.browser_factory = browser_factory or uc.Chrome
        self.sleep_fn = sleep_fn
        self.random_generator = random_generator or random.Random()
        self.initial_sleep = initial_sleep
        self.page_sleep = page_sleep
        self.progress_fn = progress_fn

    def fetch_counts(
        self,
        boards: Union[str, int, Iterable[Union[str, int]]],
        days: Union[str, int],
        include_today: bool = False,
        today: Optional[Union[date, datetime]] = None,
        write_logs: bool = True,
    ) -> CountResult:
        board_codes = normalize_boards(boards)
        dates = build_date_range(days, include_today, today)
        date_strings = [item.isoformat() for item in dates]
        date_set = set(dates)
        counts = {
            code: {day: 0 for day in date_strings} for code in board_codes
        }

        for board_code in board_codes:
            self._fetch_board(
                board_code,
                counts[board_code],
                date_set,
                dates[0],
                write_logs,
            )

        return CountResult(
            board_codes=board_codes,
            dates=date_strings,
            counts=counts,
            generated_at=datetime.now(TAIPEI_TIMEZONE).isoformat(timespec="seconds"),
            include_today=include_today,
        )

    @staticmethod
    def _extract_posts(payload: Mapping[str, Any]) -> List[Mapping[str, Any]]:
        posts: List[Mapping[str, Any]] = []
        for widget in payload.get("widgets", []) or []:
            try:
                post = widget["forumList"]["items"][0]["post"]
            except (KeyError, IndexError, TypeError):
                continue
            if isinstance(post, Mapping):
                posts.append(post)
        return posts

    @staticmethod
    def _initial_query(list_key: str, offset: int) -> str:
        return urlencode(
            {
                "enrich": "true",
                "forumLogo": "true",
                "pinnedPosts": "widget",
                "country": "TW",
                "platform": "web",
                "listKey": list_key,
                "immersiveVideoListKey": list_key.replace("f_latest", "v_latest"),
                "pageKey": list_key,
                "offset": str(offset),
            }
        )

    @staticmethod
    def _next_query(list_key: str, next_key: str, offset: int) -> str:
        return urlencode(
            {
                "immersiveVideoListKey": list_key,
                "country": "TW",
                "enrich": "true",
                "platform": "web",
                "offset": str(offset),
                "pageKey": next_key,
            }
        )

    def _create_browser(self) -> Any:
        options = webdriver.ChromeOptions()
        options.add_argument("--incognito")
        # Start Chrome through the driver subprocess. This avoids the
        # multiprocessing resource_tracker used by use_subprocess=False,
        # which can emit semaphore errors in PyInstaller one-file builds.
        kwargs: Dict[str, Any] = {"options": options, "use_subprocess": True}
        if self.version_main is not None:
            kwargs["version_main"] = self.version_main
        return self.browser_factory(**kwargs)

    def _pause(self, interval: Sequence[int]) -> None:
        minimum, maximum = interval
        if maximum > 0:
            self.sleep_fn(self.random_generator.randint(minimum, maximum))

    def _fetch_board(
        self,
        board_code: str,
        counts: Dict[str, int],
        date_set: set,
        first_date: date,
        write_logs: bool,
    ) -> None:
        browser = None
        try:
            browser = self._create_browser()
            self.progress_fn("開始開啟 {} 看板...".format(BOARD_DISPLAY_NAMES[board_code]))
            browser.get("https://www.dcard.tw/f")
            self._pause(self.initial_sleep)
            browser.get("https://www.dcard.tw/f/{}?tab=latest".format(board_code))
            self._pause((3, 5))
            list_key = browser.execute_script(LIST_KEY_SCRIPT)
            if not list_key:
                raise DcardScraperError(
                    "看板 {} 無法取得 listKey".format(BOARD_DISPLAY_NAMES[board_code])
                )

            offset = 0
            query = self._initial_query(list_key, offset)
            page_number = 0
            while True:
                payload = browser.execute_async_script(FETCH_PAGE_SCRIPT, query)
                if not isinstance(payload, Mapping):
                    raise DcardScraperError("Dcard API 回傳格式錯誤")
                if payload.get("__error"):
                    raise DcardScraperError(str(payload["__error"]))
                posts = self._extract_posts(payload)
                if not posts:
                    break

                post_dates: List[date] = []
                for post in posts:
                    created_at = post.get("createdAt")
                    if not created_at:
                        continue
                    try:
                        post_date = parse_post_date(str(created_at))
                    except ValueError:
                        continue
                    post_dates.append(post_date)
                    if post_date in date_set:
                        counts[post_date.isoformat()] += 1

                page_number += 1
                offset += len(posts)
                next_key = payload.get("nextKey")
                query = self._next_query(list_key, str(next_key), offset) if next_key else ""
                oldest_page_date = min(post_dates).isoformat() if post_dates else "未知"
                progress = "、".join(
                    "{}={}".format(day, counts[day]) for day in sorted(counts)
                )
                self.progress_fn(
                    "[{}] 第 {} 頁：本頁 {} 筆，最舊日期 {}；累計 {}".format(
                        BOARD_DISPLAY_NAMES[board_code],
                        page_number,
                        len(posts),
                        oldest_page_date,
                        progress,
                    )
                )
                if write_logs:
                    self._append_log(board_code, counts, query)

                if post_dates and min(post_dates) < first_date:
                    break
                if not next_key:
                    break
                self._pause(self.page_sleep)
        except DcardScraperError:
            raise
        except Exception as error:
            raise DcardScraperError(
                "抓取 {} 時發生錯誤：{}".format(BOARD_DISPLAY_NAMES[board_code], error)
            ) from error
        finally:
            if browser is not None:
                try:
                    browser.quit()
                except Exception:
                    pass

    def _append_log(
        self, board_code: str, counts: Mapping[str, int], query: str
    ) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        with (self.log_dir / (board_code + "Log.json")).open(
            "a", encoding="utf-8"
        ) as output:
            output.write(json.dumps(dict(counts), ensure_ascii=False) + " " + query + "\n")
