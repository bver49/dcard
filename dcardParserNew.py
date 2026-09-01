"""原本命令列流程的相容入口。

新的抓取核心在 dcard_service.py；這個檔案保留原本的互動方式，
讓熟悉舊流程的人仍然可以直接執行：

    python dcardParserNew.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from dcard_service import BOARD_DISPLAY_NAMES, DcardScraper, normalize_boards


class dcardParser:
    """保留舊 class 名稱，讓既有呼叫方式不需要立刻修改。"""

    def __init__(self, logPath: Union[str, Path] = ".") -> None:
        self.logPath = str(logPath)

    def run(
        self, daysBefore: Union[str, int], boardNum: Union[str, int]
    ) -> Optional[str]:
        try:
            board_code = normalize_boards(boardNum)[0]
            result = DcardScraper(log_dir=self.logPath).fetch_counts(
                boards=[board_code],
                days=daysBefore,
                include_today=False,
            )
        except (ValueError, RuntimeError) as error:
            print("錯誤：{}".format(error))
            return None

        csv_text = result.to_csv()
        output_path = Path(self.logPath) / "result.csv"
        result.write_csv(output_path)
        print(
            "已完成 {} 看板的 CSV 統計：{}".format(
                BOARD_DISPLAY_NAMES[board_code], output_path
            )
        )
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
