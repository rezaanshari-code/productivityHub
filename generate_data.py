"""
generate_data.py
Fetch semua sheet dari Google Spreadsheet pakai API Key (tidak perlu Service Account).
Syarat: Spreadsheet sudah di-set "Anyone with link can view"
"""

import os, json
import pandas as pd
import urllib.request

# ── Config ───────────────────────────────────────────────────────────────────
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1-2oAckm4nZjcj0y6ToLrVNlNL1VxJyIiwHosB9QW-dk")
API_KEY        = os.environ.get("GOOGLE_API_KEY")   # dari GitHub Secret

# ── Ambil daftar sheet + gid via Sheets API v4 ───────────────────────────────
def get_sheet_list():
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}"
        f"?fields=sheets.properties&key={API_KEY}"
    )
    with urllib.request.urlopen(url) as r:
        meta = json.loads(r.read())
    sheets = []
    for s in meta["sheets"]:
        props = s["properties"]
        sheets.append({"title": props["title"], "gid": props["sheetId"]})
    return sheets

# ── Baca tiap sheet sebagai CSV ───────────────────────────────────────────────
def read_sheet_csv(gid):
    url = (
        f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}"
        f"/export?format=csv&gid={gid}"
    )
    return pd.read_csv(url)

# ── Clean data ────────────────────────────────────────────────────────────────
def clean_df(df):
    if "Status LC" in df.columns:
        df = df[df["Status LC"] != "New"].copy()

    numeric_cols = [
        "Total DO Cust","Total DO Store","Total DO",
        "Tol (UJP)","Parkir (UJP)","BBM (UJP)","Others (UJP)",
        "Total Cost UJP","Cost VR","Cost MPP Fee","Cost Ovt",
        "Cost Insentif","Total Cost","Volume BBM","Jarak (KM)","Jumlah DP"
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(",","").str.strip(), errors="coerce"
            )

    if "Jalur" in df.columns:
        df["Jalur"] = (
            df["Jalur"].astype(str).str.replace("\xa0"," ").str.strip()
            .replace({"nan":"(Tidak Ada Jalur)","-":"(Tidak Ada Jalur)","":"(Tidak Ada Jalur)"})
        )

    def tat_to_min(v):
        v = str(v).strip()
        if ":" in v:
            p = v.split(":")
            try: return int(p[0])*60 + int(p[1])
            except: return None
        return None

    if "TAT" in df.columns:
        df["TAT_minutes"] = df["TAT"].apply(tat_to_min)

    return df

# ── Metrics ───────────────────────────────────────────────────────────────────
def get_metrics(df):
    tat = df["TAT_minutes"].dropna().mean() if "TAT_minutes" in df.columns else None
    h = int(tat//60) if tat and not pd.isna(tat) else 0
    m = int(tat%60)  if tat and not pd.isna(tat) else 0
    return {
        "trips":       int(len(df)),
        "total_do":    int(df["Total DO"].sum()),
        "do_cust":     int(df["Total DO Cust"].sum()),
        "do_store":    int(df["Total DO Store"].sum()),
        "total_cost":  float(df["Total Cost"].sum()),
        "total_ujp":   float(df["Total Cost UJP"].sum()),
        "bbm_ujp":     float(df["BBM (UJP)"].sum()),
        "jarak_km":    float(df["Jarak (KM)"].dropna().sum()),
        "tat_avg":     f"{h}:{m:02d}" if tat and not pd.isna(tat) else "N/A",
        "tat_minutes": round(float(tat),1) if tat and not pd.isna(tat) else None,
    }

def get_jalur(df):
    r = {}
    for jalur, grp in df.groupby("Jalur"):
        r[str(jalur)] = get_metrics(grp)
    return dict(sorted(r.items(), key=lambda x: x[1]["trips"], reverse=True))

def get_persons(df, col, top=50):
    people = []
    src = df[df[col].notna()].copy()
    src = src[~src[col].astype(str).str.strip().isin(["","nan"])]
    for name, grp in src.groupby(col):
        if not name or str(name).strip() in ["","nan"]: continue
        m = get_metrics(grp); m["name"] = str(name).strip()
        people.append(m)
    return sorted(people, key=lambda x: x["trips"], reverse=True)[:top]

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("🔄  Mengambil daftar sheet …")
    sheet_list = get_sheet_list()
    print(f"   Ditemukan {len(sheet_list)} sheet: {[s['title'] for s in sheet_list]}")

    all_data = {}
    for s in sheet_list:
        name, gid = s["title"], s["gid"]
        print(f"   📄  Reading: {name} (gid={gid})")
        try:
            df = read_sheet_csv(gid)
            df = clean_df(df)
            if "BU Hub" not in df.columns or len(df) == 0:
                print(f"   ⚠️   Skip {name} (kosong / tidak ada kolom BU Hub)")
                continue
            all_data[name] = df
            print(f"   ✅  {name}: {len(df)} baris valid")
        except Exception as e:
            print(f"   ❌  Gagal baca {name}: {e}")

    # Build dashboard data
    dashboard = {"hubs":{}, "bu":{"AHI":{},"HCI":{}}, "overall":{}}

    for sheet, df in all_data.items():
        bu = df["BU Hub"].iloc[0]
        dashboard["hubs"][sheet] = {
            "name": sheet, "bu": bu,
            "metrics":    get_metrics(df),
            "jalur":      get_jalur(df),
            "drivers":    get_persons(df, "Nama Driver"),
            "assistants": get_persons(df, "Nama Asst to Driver"),
        }

    for bu in ["AHI","HCI"]:
        sheets = [s for s,d in all_data.items() if d["BU Hub"].iloc[0]==bu]
        if not sheets: continue
        combined = pd.concat([all_data[s] for s in sheets])
        dashboard["bu"][bu] = {
            "metrics":    get_metrics(combined),
            "jalur":      get_jalur(combined),
            "drivers":    get_persons(combined, "Nama Driver"),
            "assistants": get_persons(combined, "Nama Asst to Driver"),
            "hubs":       sheets,
        }

    all_combined = pd.concat(all_data.values())
    dashboard["overall"] = {
        "metrics":    get_metrics(all_combined),
        "jalur":      get_jalur(all_combined),
        "drivers":    get_persons(all_combined, "Nama Driver"),
        "assistants": get_persons(all_combined, "Nama Asst to Driver"),
    }

    os.makedirs("public", exist_ok=True)
    with open("public/data.json","w", encoding="utf-8") as f:
        json.dump(dashboard, f, ensure_ascii=False)

    print(f"\n✅  public/data.json tersimpan")
    print(f"   Total trips: {dashboard['overall']['metrics']['trips']:,}")

if __name__ == "__main__":
    main()
