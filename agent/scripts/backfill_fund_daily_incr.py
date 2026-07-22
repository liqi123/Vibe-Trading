"""
增量回补问财数据 — 只补 fund_daily 表中缺失的近期日期
"""
import logging, sys, os, json, time
from datetime import date, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("backfill_incr")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def get_trading_dates_from_db(db_path: str, start: str, end: str) -> list[str]:
    import sqlite3
    conn = sqlite3.connect(db_path)
    cur = conn.execute("SELECT DISTINCT trade_date FROM daily_kline WHERE trade_date >= ? AND trade_date <= ? ORDER BY trade_date", (int(start.replace("-", "")), int(end.replace("-", ""))))
    dates = [str(r[0])[:4] + "-" + str(r[0])[4:6] + "-" + str(r[0])[6:8] for r in cur.fetchall()]
    conn.close()
    return dates


def get_stock_list_from_db(db_path: str) -> list[str]:
    import sqlite3
    conn = sqlite3.connect(db_path)
    cur = conn.execute("SELECT DISTINCT code FROM daily_kline ORDER BY code LIMIT 1000")
    codes = [r[0] for r in cur.fetchall()]
    conn.close()
    return codes


def get_existing_dates(db_path: str) -> set[str]:
    import sqlite3
    conn = sqlite3.connect(db_path)
    cur = conn.execute("SELECT DISTINCT date FROM fund_daily ORDER BY date")
    dates = {r[0] for r in cur.fetchall()}
    conn.close()
    return dates


def _claw_headers():
    import secrets
    return {
        "X-Claw-Call-Type": "data",
        "X-Claw-Skill-Id": "report-search",
        "X-Claw-Skill-Version": "1.0.0",
        "X-Claw-Plugin-Id": "none",
        "X-Claw-Plugin-Version": "none",
        "X-Claw-Trace-Id": secrets.token_hex(32),
    }


def query_iwencai(date_str: str, fields: list[str]) -> list[dict]:
    import requests
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.environ.get("VIBE_TRADING_IWENCAI_KEY") or os.environ.get("IWENCAI_API_KEY")
    if not api_key:
        log.error("未找到 IWENCAI_API_KEY")
        return []

    query_str = f"{date_str} " + " ".join(fields)
    payload = {"query": query_str, "perpage": 5000, "page": 1}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        **_claw_headers(),
    }

    for attempt in range(2):
        try:
            resp = requests.post(
                "https://openapi.iwencai.com/v1/query2data",
                json=payload,
                headers=headers,
                timeout=90,
            )
            if resp.status_code == 401:
                log.error("API key 无效 (401): %s", resp.text[:200])
                return []
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                if "datas" in data:
                    return data["datas"]
                answer = data.get("data", {}).get("answer")
                if isinstance(answer, list) and answer:
                    try:
                        return (answer[0].get("txt", [{}])[0].get("content", {})
                                .get("components", [{}])[0].get("data", {})
                                .get("datas", []))
                    except (IndexError, AttributeError):
                        pass
            log.warning("  %s: 无数据返回, raw=%s", date_str, str(data)[:200])
            return []
        except requests.exceptions.RequestException as e:
            log.warning("  %s: 请求失败 (attempt %d): %s", date_str, attempt + 1, e)
            time.sleep(3)
    return []


def extract_row(row: dict, field_maps: dict) -> dict:
    extracted = {}
    code_raw = row.get("股票代码", row.get("code", ""))
    code = code_raw[-6:] if len(code_raw) >= 6 else code_raw

    column_map = {}
    for col_name, zh_names in field_maps.items():
        for zh in zh_names:
            if zh in row:
                column_map[col_name] = row[zh]
                break

    return {"code": code, **column_map}


def main():
    db_path = r"G:\tdx_data\tdx_daily.db"
    if not os.path.exists(db_path):
        log.error("数据库不存在: %s", db_path)
        sys.exit(1)

    today = date.today().isoformat()
    last_db_date = "2026-07-10"

    log.info("数据库: %s", db_path)
    log.info("上次数据到: %s, 今天: %s", last_db_date, today)

    trading_dates = get_trading_dates_from_db(db_path, last_db_date, today)
    log.info("交易日 (>= %s): %d 天", last_db_date, len(trading_dates))

    existing = get_existing_dates(db_path)
    missing = [d for d in trading_dates if d not in existing]
    log.info("已有 %d 天, 缺失 %d 天", len(existing), len(missing))

    if not missing:
        log.info("所有数据已存在，无需回补")
        return

    field_maps = {
        "turnover_pct": ["换手率"],
        "pe_ttm": ["市盈率ttm", "滚动市盈率", "市盈率"],
        "pb": ["市净率"],
        "mcap_yi": ["总市值"],
        "main_net_flow": ["主力资金净流入", "主力资金流向", "主力资金"],
        "margin_balance": ["融资余额"],
    }
    query_fields = ["换手率", "市盈率ttm", "市净率", "总市值", "主力资金净流入", "融资余额"]

    import sqlite3
    conn = sqlite3.connect(db_path)

    for i, date_str in enumerate(missing):
        log.info("  [%d/%d] %s ...", i + 1, len(missing), date_str)
        rows = query_iwencai(date_str, query_fields)
        if not rows:
            log.warning("  %s: 跳过（无数据）", date_str)
            continue

        inserted = 0
        for row in rows:
            extracted = extract_row(row, field_maps)
            code = extracted.pop("code")
            if not code:
                continue

            conn.execute(
                """INSERT OR REPLACE INTO fund_daily
                   (date, code, turnover_pct, pe_ttm, pb, mcap_yi, main_net_flow, margin_balance)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    date_str, code,
                    extracted.get("turnover_pct"),
                    extracted.get("pe_ttm"),
                    extracted.get("pb"),
                    extracted.get("mcap_yi"),
                    extracted.get("main_net_flow"),
                    extracted.get("margin_balance"),
                ),
            )
            inserted += 1

        conn.commit()
        log.info("    -> %d 条记录写入", inserted)
        time.sleep(1.5)

    conn.close()
    log.info("回补完成!")


if __name__ == "__main__":
    main()
