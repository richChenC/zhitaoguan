# -*- coding: utf-8 -*-
"""零依赖提取 Word97(.doc / .wps OLE2) 主文本流文本。

背景：项目禁止新增运行时第三方依赖，故不引入 olefile / antiword，
      直接解析 OLE2 复合文档 + FIB 的 fcMin/fcMac 取主文本流。

用法：
    python tools/_extract_doc.py <input.doc|.wps> [output.txt]
    不传 output 时打印到 stdout。
"""
import struct
import re
import sys

# ---------------- OLE2 ----------------

def _read_fat(data, ss):
    num_fat, = struct.unpack_from("<I", data, 0x2C)
    per_fat = ss // 4
    difat = list(struct.unpack_from("<%dI" % 109, data, 0x4C))
    fat_sectors = [s for s in difat[:num_fat] if s < 0xFFFFFFF0]
    fat = []
    for fs in fat_sectors:
        off = 512 + fs * ss
        fat.extend(struct.unpack_from("<%dI" % per_fat, data, off))
    return fat


def _read_chain(data, fat, ss, start, size):
    buf = bytearray()
    sec = start
    guard = 0
    while sec < 0xFFFFFFF0 and len(buf) < size and guard < 100000:
        off = 512 + sec * ss
        if off + ss > len(data):
            break
        buf.extend(data[off:off + ss])
        sec = fat[sec] if sec < len(fat) else 0xFFFFFFFE
        guard += 1
    return bytes(buf[:size])


def _find_stream(data, want):
    sector_shift, = struct.unpack_from("<H", data, 0x1E)
    ss = 1 << sector_shift
    dir_first, = struct.unpack_from("<I", data, 0x30)
    fat = _read_fat(data, ss)
    dir_stream = _read_chain(data, fat, ss, dir_first, 10 ** 9)
    for i in range(0, len(dir_stream) - 127, 128):
        e = dir_stream[i:i + 128]
        obj_type = e[66]
        if obj_type == 0:
            continue
        name_len, = struct.unpack_from("<H", e, 64)
        try:
            name = e[:max(0, name_len - 2)].decode("utf-16-le", "ignore")
        except Exception:
            name = ""
        if name == want:
            start, = struct.unpack_from("<I", e, 116)
            size, = struct.unpack_from("<Q", e, 120)
            return fat, ss, start, size
    return None


# ---------------- Word97 FIB ----------------

def extract_text(path):
    data = open(path, "rb").read()
    if data[:4] != b"\xd0\xcf\x11\xe0":
        raise ValueError("不是 OLE2 复合文档(非 Word97 格式): %s" % path)

    got = _find_stream(data, "WordDocument")
    if not got:
        raise ValueError("未找到 WordDocument 流")

    fat, ss, start, size = got
    wd = _read_chain(data, fat, ss, start, min(size, len(data)))
    if len(wd) <= 0x20:
        raise ValueError("WordDocument 流过短")

    fc_min, = struct.unpack_from("<I", wd, 0x18)
    fc_mac, = struct.unpack_from("<I", wd, 0x1C)
    fc_min = max(0, min(fc_min, len(wd)))
    fc_mac = max(fc_min, min(fc_mac, len(wd)))
    blob = wd[fc_min:fc_mac]

    # 用 0x00 占比自动判断编码（比解析 FIB 的 fCompressed 位更稳）
    zero_ratio = blob.count(0) / max(1, len(blob))
    text = blob.decode("utf-16-le", "ignore") if zero_ratio > 0.20 \
        else blob.decode("gbk", "ignore")

    text = text.replace("\r", "\n").replace("\x07", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    src = sys.argv[1]
    text = extract_text(src)
    if len(sys.argv) >= 3:
        open(sys.argv[2], "w", encoding="utf-8").write(text)
        print("written", sys.argv[2], len(text))
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)


if __name__ == "__main__":
    main()
