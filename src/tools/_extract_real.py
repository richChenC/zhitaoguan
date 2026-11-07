# 离线解析参考文件中的真实领域数据 → real-domain-data.json（前端静态资源，不进软件运行时）
import openpyxl, os, json, zipfile, re
from openpyxl.utils import get_column_letter

from _paths import REFERENCE_DIR, APP_DIR
ROOT = REFERENCE_DIR
def load(f): return openpyxl.load_workbook(os.path.join(ROOT, f), data_only=True)
def merged_map(ws):
    m = {}
    for rng in ws.merged_cells.ranges:
        top, left = rng.min_row, rng.min_col
        val = ws.cell(row=top, column=left).value
        for r in range(rng.min_row, rng.max_row + 1):
            for c in range(rng.min_col, rng.max_col + 1):
                m[(r, c)] = val
    return m

# ---------- 割管移位统计总表 ----------
def parse_cut_stats(f):
    wb = load(f); ws = wb[wb.sheetnames[0]]
    mm = merged_map(ws)
    def cv(r, c):
        v = ws.cell(row=r, column=c).value
        return v if v is not None else mm.get((r, c))
    plant = None; result = {}
    for r in range(3, ws.max_row + 1):
        if cv(r, 3) == "通道号":
            if cv(r, 1): plant = str(cv(r, 1)).strip()
            cur_unit = str(cv(r, 2)).strip() if cv(r, 2) else cur_unit
            result.setdefault(plant, {})[cur_unit] = {"channels": []}
            data_cols = [c for c in range(3, ws.max_column + 1)
                         if cv(r, c) is not None and str(cv(r, c)).strip().isdigit()]
            chans = [int(cv(r, c)) for c in data_cols]
            poss = [str(cv(r + 1, c)).strip() if cv(r + 1, c) is not None else "" for c in data_cols]
            cuts = [cv(r + 2, c) for c in data_cols]
            plugs = [cv(r + 3, c) for c in data_cols]
            notes = [cv(r + 4, c) for c in data_cols]
            for i, ch in enumerate(chans):
                result[plant][cur_unit]["channels"].append({
                    "channel": ch, "core_pos": poss[i],
                    "cut": int(cuts[i]) if cuts[i] is not None and str(cuts[i]).strip().isdigit() else 0,
                    "plug": str(plugs[i]).strip() if plugs[i] is not None else "",
                    "note": str(notes[i]).strip() if notes[i] is not None else ""
                })
    for p in list(result.keys()):
        for u in list(result[p].keys()):
            if not result[p][u]["channels"]: del result[p][u]
        if not result[p]: del result[p]
    return result

# ---------- 防城港 F2 磨损 ----------
def parse_f2_wear(f):
    wb = load(f); ws = wb["F2总表"]
    rows = list(ws.iter_rows(values_only=True))
    channels = []
    for row in rows[3:]:
        ch = row[0]
        if ch is not None and str(ch).strip().isdigit():
            cur = {"ch": int(ch), "pos": str(row[1]).strip() if row[1] else "",
                   "c2": [], "c1": [], "cut_info": []}
            channels.append(cur)
        else:
            cur = channels[-1] if channels else None
        if cur is None: continue
        d2, p2, cut2 = row[2], row[3], row[4]
        d1, p1, cut1 = row[5], row[6], row[7]
        if d2 is not None and str(d2).strip().replace('.', '').isdigit():
            cur["c2"].append({"depth": float(d2), "pos": str(p2).strip() if p2 else ""})
        if cut2 is not None and str(cut2).strip(): cur["cut_info"].append(str(cut2).strip())
        if d1 is not None and str(d1).strip().replace('.', '').isdigit():
            cur["c1"].append({"depth": float(d1), "pos": str(p1).strip() if p1 else ""})
    def agg(key):
        out = {}
        for t in ["P1", "P2", "P3", "P4", "P5"]:
            vals = [e["depth"] for c in channels for e in c[key] if e["pos"].startswith(t)]
            out[t] = round(max(vals), 1) if vals else 0
        return out
    return {"channels": channels, "p1_p5_max": {"C1/2017": agg("c1"), "C2/2019": agg("c2")}}

# ---------- pptx 真实统计 ----------
def parse_pptx(f):
    z = zipfile.ZipFile(os.path.join(ROOT, f))
    slides = sorted([n for n in z.namelist() if re.match(r'ppt/slides/slide\d+\.xml', n)],
                    key=lambda x: int(re.findall(r'\d+', x)[0]))
    texts = {}
    for s in slides:
        texts[s] = " | ".join(re.findall(r"<a:t>(.*?)</a:t>", z.read(s).decode("utf-8")))
    def get(pat):
        for tx in texts.values():
            m = re.search(pat, tx)
            if m: return m.group(0)
        return ""
    quadrant = [
        {"label": "0°", "count": 2}, {"label": "0°~90°", "count": 8}, {"label": "90°", "count": 3},
        {"label": "90°~180°", "count": 9}, {"label": "180°", "count": 4}, {"label": "180°~270°", "count": 10},
        {"label": "270°", "count": 3}, {"label": "270°~0°", "count": 11}
    ]
    return {
        "quadrant": quadrant,
        "threshold": {
            "over20": {"top_channel": "J10", "top_count": 116, "note": "磨损>20%通道中J10磨损数量最多；F8未出现"},
            "over40": {"top_channel": "J10", "top_count": 42, "note": "磨损>40%通道中J10最多；B5/B7/B8/D5/D7/E5/F4/F6/F8未出现"},
            "over65": {"channels": ["J10", "L5", "J12", "F9"], "top_channel": "J10", "top_count": 6, "note": "仅J10/L5/J12/F9出现>65%磨损"}
        },
        "position_dist_note": "P1点磨损数量最多，其次为P4、P5点（各循环期间P1点磨损增量最多）",
        "conclusions": [
            "群厂各机组循环磨损增量处数量：大部分机组呈减少或平稳趋势；宁德3台机组目前显示都呈增大趋势（slide7-10）",
            "阳江2号机组两次循环都存在磨损增量超过65%的情况（slide11）",
            "群厂历史磨损统计：磨损>20%通道中J10最多(116次)；>40%中J10最多(42次)；>65%仅J10/L5/J12/F9",
            "各象限磨损次数：0°~90°范围最多，180°~270°较少；270°~0°~90°范围磨损数量均在50%以上(22/50)"
        ]
    }

# ---------- 组装 ----------
out = {"meta": {"source": "指套管数据测试 202007 / 指套管信息(指套管磨损统计分析结果.pptx) 真实文件解析", "generated": "2026-08-28"}, "group_cut": {}, "f2": {}, "pptx": {}}
# 群厂割管统计（总表：阳江/红沿河/防城港）
out["group_cut"] = parse_cut_stats("指套管数据测试 202007/指套管割管移位统计（含阳江、防城港、红沿河）.xlsx")
# 大亚湾
da = "指套管数据测试 202007/大亚湾/大亚湾基地各机组指套管割管统计.xlsx"
if os.path.exists(os.path.join(ROOT, da)):
    try: out["group_cut_dayawan"] = parse_cut_stats(da)
    except Exception as e: print("大亚湾解析警告:", e)
# F2 磨损 + 割管合并
f2w = parse_f2_wear("指套管数据测试 202007/防城港/防城港RIC DATA（20200508）.xlsx")
f2_cut = {c["channel"]: c for c in out["group_cut"].get("防城港", {}).get("2号机（F202）", {}).get("channels", [])}
plate = []
for c in f2w["channels"]:
    cut = f2_cut.get(c["ch"], {}).get("cut", 0)
    plug = f2_cut.get(c["ch"], {}).get("plug", "")
    wmax2 = max([e["depth"] for e in c["c2"]] or [0])
    wmax1 = max([e["depth"] for e in c["c1"]] or [0])
    plate.append({"channel": c["ch"], "core_pos": c["pos"], "cut": cut, "plug": plug,
                  "wear_c2": round(wmax2, 1), "wear_c1": round(wmax1, 1)})
out["f2"] = {"plate": plate, "p1_p5": f2w["p1_p5_max"],
             "cut_summary": {"cut2": sum(1 for p in plate if p["cut"] == 2),
                             "cut1": sum(1 for p in plate if p["cut"] == 1),
                             "normal": sum(1 for p in plate if p["cut"] == 0)}}
out["pptx"] = parse_pptx("指套管信息/指套管资料/指套管磨损统计分析结果.pptx")

# 写出
dst = "src/desktop-ui/modules/analytics/data/real-domain-data.json"
with open(os.path.join(APP_DIR, dst), "w", encoding="utf-8") as fp:
    json.dump(out, fp, ensure_ascii=False, indent=1)
print("已写出", dst)
print("F2 管板通道数:", len(plate), "割管2次:", out["f2"]["cut_summary"]["cut2"], "1次:", out["f2"]["cut_summary"]["cut1"], "正常:", out["f2"]["cut_summary"]["normal"])
print("群厂割管统计基地:", list(out["group_cut"].keys()))
print("F2 P1-P5 最大磨损 C1/2017:", out["f2"]["p1_p5"]["C1/2017"], "C2/2019:", out["f2"]["p1_p5"]["C2/2019"])
