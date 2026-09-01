"""原本命令列流程的相容入口。

新的抓取核心在 dcard_service.py；這個檔案保留原本的互動方式，
讓熟悉舊流程的人仍然可以直接執行：

    python dcardParserNew.py
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime
import os
import ssl
import sys
import traceback
from typing import Optional, Union

import certifi

from dcard_service import BOARD_DISPLAY_NAMES, DcardScraper, normalize_boards


# PyInstaller bundles do not always expose the host Python CA store. Ensure
# urllib (used by undetected_chromedriver) validates downloads with certifi.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
ssl._create_default_https_context = lambda: ssl.create_default_context(
    cafile=certifi.where()
)


class dcardParser:
    """保留舊 class 名稱，讓既有呼叫方式不需要立刻修改。"""

    def __init__(self, logPath: Optional[Union[str, Path]] = None) -> None:
        if logPath is None:
            if getattr(sys, "frozen", False):
                logPath = Path(sys.executable).resolve().parent
            else:
                logPath = Path(__file__).resolve().parent
        self.logPath = str(logPath)

    def _log_path(self) -> Path:
        log_dir = Path(self.logPath) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return log_dir / f"dcard_stats_{timestamp}.log"

    @staticmethod
    def _write_log(path: Path, message: str) -> None:
        with path.open("a", encoding="utf-8") as output:
            output.write(message.rstrip() + "\n")

    def run(
        self, daysBefore: Union[str, int], boardNum: Union[str, int]
    ) -> Optional[str]:
        log_path = self._log_path()
        self._write_log(
            log_path,
            "開始執行\n天數：{}\n看板：{}".format(daysBefore, boardNum),
        )
        try:
            board_code = normalize_boards(boardNum)[0]
            result = DcardScraper(log_dir=str(Path(self.logPath) / "logs")).fetch_counts(
                boards=[board_code],
                days=daysBefore,
                include_today=False,
            )
        except Exception as error:
            self._write_log(
                log_path,
                "失敗：{}\n{}".format(error, traceback.format_exc()),
            )
            print("錯誤：{}".format(error))
            print("詳細 log：{}".format(log_path))
            return None

        csv_text = result.to_csv()
        output_path = Path(self.logPath) / "result.csv"
        result.write_csv(output_path)
        self._write_log(
            log_path,
            "成功\n輸出：{}\n{}".format(output_path, csv_text.lstrip("\ufeff")),
        )
        print(
            "已完成 {} 看板的 CSV 統計：{}".format(
                BOARD_DISPLAY_NAMES[board_code], output_path
            )
        )
        print("執行 log：{}".format(log_path))
        print(csv_text.lstrip("\ufeff"))
        return csv_text


if __name__ == "__main__":
    days_before = input("要抓幾天內的資料（不包含今天）：")
    board_num = input(
        "請輸入看板名稱\n"
        "1.心情\n"
        "2.感情\n"
        "3.MLB\n"
        "4.NBA\n"
        "5.中職\n"
        "6.棒球\n"
        "7.籃球\n"
        "8.大型賽事\n"
        "請輸入編號："
    )
    parser = dcardParser()
    parser.run(daysBefore=days_before, boardNum=board_num)
