import os
import json
import pandas as pd

# Paths (adjust if needed)
EXCEL_PATH = r"C:/Users/tyinc/Desktop/ai 개발관련/차입금관리/★ 차입금_관리내역.xlsx"

# Output files (will be placed alongside this script)
KPI_JSON = "kpi_inputs.json"
HIST_JSON = "historical_rates.json"
CREDIT_JSON = "credit_ratings.json"

def load_kpi_defaults():
    """Fallback KPI values matching the original Streamlit defaults."""
    return {
        "balance_24": 302375.0,
        "avg_rate_24": 4.75,
        "bok_rate_24": 3.00,
        "balance_25": 332875.0,
        "avg_rate_25": 4.12,
        "bok_rate_25": 2.65,
        "balance_26": 332875.0,
        "avg_rate_26": 4.12,
        "bok_rate_26": 2.65,
    }

def export_kpi():
    kpi = load_kpi_defaults()
    with open(KPI_JSON, "w", encoding="utf-8") as f:
        json.dump(kpi, f, ensure_ascii=False, indent=2)
    print(f"Exported KPI defaults to {KPI_JSON}")

def export_hist():
    xl = pd.ExcelFile(EXCEL_PATH)
    df_hist = pd.DataFrame()
    if "과거 이자율변동내역" in xl.sheet_names:
        df_hist_raw = xl.parse("과거 이자율변동내역", header=None)
        # locate header row (contains '금융기관')
        header_idx = -1
        for i in range(len(df_hist_raw)):
            if '금융기관' in str(df_hist_raw.iloc[i, 1]):
                header_idx = i
                break
        if header_idx == -1:
            raise RuntimeError("Header row not found in 과거 이자율변동내역")
        history = []
        current_loan_type = ""
        for i in range(header_idx + 1, len(df_hist_raw)):
            row = df_hist_raw.iloc[i]
            bank_name = str(row.iloc[1]).strip()
            if not bank_name or bank_name.lower() == "nan":
                continue
            if bank_name in ("계", "기준시점", "24년말"):
                break
            loan_type_val = row.iloc[2]
            if pd.notna(loan_type_val) and str(loan_type_val).strip() not in ("", "0"):
                current_loan_type = str(loan_type_val).strip().replace('\n', ' ')
            # limit
            limit_val = pd.to_numeric(row.iloc[3], errors='coerce')
            limit_str = f"{limit_val/100000000:.0f}억" if pd.notna(limit_val) and limit_val > 0 else ""
            display_name = bank_name
            if current_loan_type:
                display_name = f"{bank_name} ({current_loan_type}{', ' + limit_str if limit_str else ''})"
            elif limit_str:
                display_name = f"{bank_name} ({limit_str})"
            def parse_rate(v):
                v = pd.to_numeric(v, errors='coerce')
                if pd.isna(v):
                    return 0
                return v * 100 if v < 1 else v
            history.append({
                "금융기관": display_name,
                "2023년": parse_rate(row.iloc[6]),
                "2024년": parse_rate(row.iloc[8]),
                "2025년": parse_rate(row.iloc[11]),
                "2026년": parse_rate(row.iloc[14]),
                "신용등급변동": str(row.iloc[12]) if pd.notna(row.iloc[12]) else "-"
            })
        df_hist = pd.DataFrame(history)
    # Export as JSON (list of records)
    df_hist.to_json(HIST_JSON, orient='records', force_ascii=False, indent=2)
    print(f"Exported historical rates to {HIST_JSON}")

def rating_to_numeric(rating_str):
    import re
    r = str(rating_str).strip().upper()
    if r in ('-', 'NAN', '') or '전년등급' in r:
        return None
    match = re.search(r"\(([^)]+)\)", r)
    if match:
        r = match.group(1).strip()
    r = r.replace('0', '')
    mapping = {
        'AAA': 10,
        'AA+': 9,
        'AA': 8,
        'AA-': 7,
        'A+': 6,
        'A': 5,
        'A-': 4,
        'BBB+': 3,
        'BBB': 2,
        'BBB-': 1,
    }
    for k in sorted(mapping, key=len, reverse=True):
        if k in r:
            return mapping[k]
    if any(tok in r for tok in ('3등급', 'A5', 'A-2', 'A-3')):
        return 4
    if any(tok in r for tok in ('5등급', 'A6')):
        return 2
    return None

def export_credit():
    xl = pd.ExcelFile(EXCEL_PATH)
    if "1금융 신용등급현황" not in xl.sheet_names:
        raise RuntimeError("Sheet '1금융 신용등급현황' not found")
    df_raw = xl.parse("1금융 신용등급현황", header=None)
    years_header = [str(df_raw.iloc[5, col]).strip() for col in range(2, 11)]
    rows = []
    for r in range(6, 14):
        row = df_raw.iloc[r]
        bank = str(row.iloc[1]).strip()
        raw = {"금융기관": bank}
        for idx, col in enumerate(range(2, 11)):
            yr = years_header[idx]
            val = str(row.iloc[col]).strip() if pd.notna(row.iloc[col]) else "-"
            raw[yr] = val.replace('\n', ' ')
        rows.append(raw)
    chart = []
    for r in range(6, 14):
        row = df_raw.iloc[r]
        bank = str(row.iloc[1]).strip()
        nums = []
        last = None
        for col in range(6, 11):
            txt = str(row.iloc[col]).strip() if pd.notna(row.iloc[col]) else ""
            num = rating_to_numeric(txt)
            if num is None:
                if ('전년등급' in txt or txt == '-' or not txt) and last is not None:
                    num = last
            if num is not None:
                last = num
            nums.append(num)
        chart.append({"금융기관": bank, "ratings": nums})
    out = {
        "table": rows,
        "chart": chart,
        "years": [str(df_raw.iloc[5, col]).strip() for col in range(6, 11)]
    }
    with open(CREDIT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Exported credit rating data to {CREDIT_JSON}")

def export_loan_details():
    """Export all rows from the '차입금_관리내역' sheet as loan details JSON."""
    xl = pd.ExcelFile(EXCEL_PATH)
    # Directly parse the first sheet (the loan data sheet), avoiding name encoding issues
    df = xl.parse(0)
    # Expected columns: 금융기관, year, balance, rate (derived from year columns like historical_rates)
    # We'll normalize to a list of dicts with keys: bank, year, balance, rate
    records = []
    for _, row in df.iterrows():
        bank = str(row.iloc[1]).strip()
        # Columns for years start at index 2? Original export_full_data used df.to_dict directly.
        # Here we map years 2023-2026 columns assuming they exist at positions 6,8,11,14 like historical_rates.
        year_cols = {"2023": 6, "2024": 8, "2025": 11, "2026": 14}
        for yr, col_idx in year_cols.items():
            bal = pd.to_numeric(row.iloc[col_idx - 1], errors='coerce')  # adjust if needed
            rate = pd.to_numeric(row.iloc[col_idx], errors='coerce')
            if pd.notna(bal) and pd.notna(rate):
                records.append({"bank": bank, "year": yr, "balance": bal, "rate": rate})
    with open("loan_details.json", "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print("Exported loan details to loan_details.json")

if __name__ == "__main__":
    export_kpi()
    export_hist()
    export_credit()
    export_loan_details()
    print("All export files generated. Open dashboard.html in a browser.")
