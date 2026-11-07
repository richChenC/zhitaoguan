"""Minimal .xls (OLE2 + BIFF8) writer used only by the test suite.

It exists so tests can build real compound-document/BIIF8 files without any
third-party package, exercising the same code paths as xls_reader (mini FAT
streams, CONTINUE chunking with string straddles, rich-text strings, RK/MULRK,
formula string results, ...).
"""
from __future__ import annotations

import struct

SECTOR_SIZE = 512
MINI_SECTOR_SIZE = 64
MINI_CUTOFF = 4096
MAX_RECORD = 0x201F

FREESECTOR = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECTOR = 0xFFFFFFFD

BOF, EOF, BOUNDSHEET, SST = 0x0809, 0x000A, 0x0085, 0x00FC
CODEPAGE, DIMENSIONS, ROW = 0x00DA, 0x005D, 0x0208
LABELSST, LABEL, NUMBER, RK, MULRK = 0x00FD, 0x0204, 0x0203, 0x027E, 0x00BD
FORMULA, STRING, BLANK, MULBLANK, BOOLERR = 0x0006, 0x0207, 0x0201, 0x00BE, 0x0205


def _record(record_id: int, payload: bytes) -> bytes:
    assert len(payload) <= MAX_RECORD
    return struct.pack("<HH", record_id, len(payload)) + payload


def _utf16_string(text: str, rich_runs: int = 0, ext_size: int | None = None) -> bytes:
    flags = 0x01
    out = struct.pack("<H", len(text))
    if rich_runs:
        flags |= 0x08
    if ext_size is not None:
        flags |= 0x04
    out += bytes([flags])
    if rich_runs:
        out += struct.pack("<H", rich_runs)
    if ext_size is not None:
        out += struct.pack("<I", ext_size)
    out += text.encode("utf-16-le")
    if rich_runs:
        out += b"\x01\x02\x03\x04" * rich_runs
    if ext_size:
        out += b"\xEE" * ext_size
    return out


def _short_string(text: str) -> bytes:
    return bytes([len(text), 0x01]) + text.encode("utf-16-le")


def _rk(value) -> int:
    if isinstance(value, bool):
        raise TypeError("bool must use BOOLERR")
    if isinstance(value, int) and abs(value) < (1 << 29):
        return ((value << 2) | 0x02) & 0xFFFFFFFF
    packed = struct.unpack("<Q", struct.pack("<d", float(value)))[0]
    return (packed >> 32) & 0xFFFFFFFC


def _cell_record(row: int, col: int, value, strings: list[str], use_sst: bool = True) -> list[bytes]:
    """Records for one cell; returns a list so formula strings can add a STRING record."""
    zero_row, zero_col = row - 1, col - 1
    address = struct.pack("<HHH", zero_row, zero_col, 0)
    if value is None:
        return [_record(BLANK, address)]
    if isinstance(value, bool):
        return [_record(BOOLERR, address + bytes([int(value), 0]))]
    if isinstance(value, str):
        if use_sst:
            if value not in strings:
                strings.append(value)
            return [_record(LABELSST, address + struct.pack("<I", strings.index(value)))]
        return [_record(LABEL, address + _utf16_string(value))]
    if isinstance(value, int) or (isinstance(value, float) and float(value).is_integer() and abs(value) < 1e15):
        return [_record(RK, address + struct.pack("<I", _rk(value)))]
    return [_record(NUMBER, address + struct.pack("<d", float(value)))]


def _mulrk_record(row: int, first_col: int, values: list) -> bytes:
    zero_row = row - 1
    payload = struct.pack("<HH", zero_row, first_col - 1)
    for value in values:
        payload += struct.pack("<HI", 0, _rk(value))
    payload += struct.pack("<H", first_col - 1 + len(values) - 1)
    return _record(MULRK, payload)


def _formula_string_record(row: int, col: int, text: str) -> list[bytes]:
    address = struct.pack("<HHH", row - 1, col - 1, 0)
    result = bytes([0x01, 0, 0, 0, 0, 0, 0xFF, 0xFF])
    formula = _record(FORMULA, address + result + struct.pack("<HHI", 0, 0, 0) + struct.pack("<H", 0))
    return [formula, _record(STRING, _utf16_string(text))]


def _sst_record(strings: list[str], chunk_size: int = MAX_RECORD) -> bytes:
    """SST record with CONTINUE chunks.

    Emulates Excel's chunking: a string's 3-byte header is never split, and
    when character data crosses a chunk boundary the continuation starts with a
    fresh flags byte (the rule xls_reader implements).
    """
    chunks: list[bytearray] = [bytearray(struct.pack("<II", len(strings), len(strings)))]

    def current_chunk() -> bytearray:
        return chunks[-1]

    for text in strings:
        encoded = text.encode("utf-16-le")
        header = struct.pack("<H", len(text)) + b"\x01"
        char_length = len(encoded)
        body = encoded
        # Header first (never split across chunks).
        if len(current_chunk()) + len(header) > chunk_size:
            chunks.append(bytearray())
        current_chunk().extend(header)
        position = 0
        while position < len(body):
            in_chars = position < char_length
            room = chunk_size - len(current_chunk())
            if in_chars:
                # Never split a UTF-16 character across a CONTINUE boundary.
                take = min(room, len(body) - position)
                take -= take % 2
                if take <= 0:
                    chunks.append(bytearray(b"\x01"))  # characters continue: flags byte
                    take = min(chunk_size - 1, len(body) - position)
                    take -= take % 2
                    take = max(take, 2)
            else:
                if room <= 0:
                    chunks.append(bytearray())
                    room = chunk_size
                take = min(room, len(body) - position)
            current_chunk().extend(body[position:position + take])
            position += take

    out = _record(SST, bytes(chunks[0]))
    for chunk in chunks[1:]:
        out += _record(0x003C, bytes(chunk))
    return out


def build_biff(sheets: list[tuple[str, list[list]]], sst_chunk_size: int = MAX_RECORD,
               boundsheet_style: str = "standard") -> bytes:
    """sheets: [(name, rows)] with rows as lists of str/int/float/None/bool values."""
    strings: list[str] = []
    sheet_streams: list[bytes] = []
    for name, rows in sheets:
        parts = [_record(BOF, struct.pack("<HHHH", 0x0600, 0x0010, 0x1FBB, 0x07CD) + struct.pack("<I", 0x00000101))]
        max_col = max((len(row) for row in rows), default=0)
        parts.append(_record(DIMENSIONS, struct.pack("<IIHHH", 0, max(len(rows), 1), 0, max(max_col, 1), 0)))
        for row_index, row in enumerate(rows, 1):
            parts.append(_record(ROW, struct.pack("<HHHHHHHHH", row_index - 1, 0, max_col, 0x0F00, 0, 0, 0, 0, 0)))
            for col_index, value in enumerate(row, 1):
                if value == "=FORMULA_TEXT":
                    parts.extend(_formula_string_record(row_index, col_index, f"计算{row_index}-{col_index}"))
                else:
                    parts.extend(_cell_record(row_index, col_index, value, strings))
        parts.append(_record(EOF, b""))
        sheet_streams.append(b"".join(parts))

    for _pass in range(3):  # BOUNDSHEET positions are fixed-size; two passes converge
        globals_head = [_record(BOF, struct.pack("<HHHH", 0x0600, 0x0005, 0x1FBB, 0x07CD) + struct.pack("<I", 0x00000101)),
                        _record(CODEPAGE, struct.pack("<H", 1252))]
        globals_len = len(b"".join(globals_head)) + len(b"".join(
            _record(BOUNDSHEET, struct.pack("<IHH", 0, 0, 0) +
                    (_short_string(name) if boundsheet_style == "standard" else name.encode("latin-1")))
            for name, _ in sheets))
        globals_len += len(_sst_record(strings, sst_chunk_size)) + len(_record(EOF, b""))
        positions = []
        offset = globals_len
        for stream in sheet_streams:
            positions.append(offset)
            offset += len(stream)
        boundsheets = []
        for (name, _), position in zip(sheets, positions):
            name_bytes = _short_string(name) if boundsheet_style == "standard" else name.encode("latin-1")
            boundsheets.append(_record(BOUNDSHEET, struct.pack("<IHH", position, 0, 0) + name_bytes))
        globals = b"".join(globals_head) + b"".join(boundsheets) + _sst_record(strings, sst_chunk_size) + _record(EOF, b"")
        if len(globals) == globals_len:
            break
    return globals + b"".join(sheet_streams)


def build_xls(path, sheets: list[tuple[str, list[list]]], sst_chunk_size: int = MAX_RECORD,
              boundsheet_style: str = "standard") -> None:
    stream = build_biff(sheets, sst_chunk_size, boundsheet_style)
    with open(path, "wb") as handle:
        handle.write(_ole_container(stream))


def _ole_container(stream: bytes) -> bytes:
    mini = len(stream) < MINI_CUTOFF
    directory_root_start, directory_root_size = 0, 0
    if mini:
        mini_data = stream + b"\x00" * (-len(stream) % MINI_SECTOR_SIZE)
        root_stream = mini_data + b"\x00" * (-len(mini_data) % SECTOR_SIZE)
        root_sectors = len(root_stream) // SECTOR_SIZE
        workbook_start, workbook_size = 0, len(stream)
        dir_sector = root_sectors
        minifat_sector = dir_sector + 1
        fat_sector = minifat_sector + 1
        total = fat_sector + 1
        fat = [FREESECTOR] * total
        for index in range(root_sectors):
            fat[index] = index + 1 if index + 1 < root_sectors else ENDOFCHAIN
        fat[dir_sector] = ENDOFCHAIN
        fat[minifat_sector] = ENDOFCHAIN
        fat[fat_sector] = FATSECTOR
        minifat = [FREESECTOR] * (SECTOR_SIZE // 4)
        mini_count = len(mini_data) // MINI_SECTOR_SIZE
        for index in range(mini_count):
            minifat[index] = index + 1 if index + 1 < mini_count else ENDOFCHAIN
        directory_root_start, directory_root_size = 0, len(mini_data)
    else:
        data_sectors = (len(stream) + SECTOR_SIZE - 1) // SECTOR_SIZE
        dir_sector = data_sectors
        fat_sector = dir_sector + 1
        total = fat_sector + 1
        fat = [FREESECTOR] * total
        for index in range(data_sectors):
            fat[index] = index + 1 if index + 1 < data_sectors else ENDOFCHAIN
        fat[dir_sector] = ENDOFCHAIN
        fat[fat_sector] = FATSECTOR
        root_stream = b""
        minifat = b""
        workbook_start, workbook_size = 0, len(stream)

    header = bytearray(SECTOR_SIZE)
    header[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<HH", header, 0x1E, 9, 6)
    struct.pack_into("<I", header, 0x2C, 1)
    struct.pack_into("<I", header, 0x30, dir_sector)
    struct.pack_into("<I", header, 0x38, MINI_CUTOFF)
    struct.pack_into("<I", header, 0x3C, minifat_sector if mini else ENDOFCHAIN)
    struct.pack_into("<I", header, 0x40, 1 if mini else 0)
    struct.pack_into("<I", header, 0x44, ENDOFCHAIN)
    struct.pack_into("<I", header, 0x48, 0)
    struct.pack_into("<109I", header, 0x4C, *([fat_sector] + [FREESECTOR] * 108))

    def entry(name: str, kind: int, start: int, size: int, child: int = -1) -> bytes:
        block = bytearray(128)
        encoded = name.encode("utf-16-le") + b"\x00\x00"
        block[0:len(encoded)] = encoded
        struct.pack_into("<H", block, 0x40, len(encoded))
        block[0x42] = kind
        block[0x43] = 1
        struct.pack_into("<iii", block, 0x44, -1, -1, child)
        struct.pack_into("<I", block, 0x74, start)
        struct.pack_into("<Q", block, 0x78, size)
        return bytes(block)

    directory = entry("Root Entry", 5, directory_root_start, directory_root_size, child=1)
    directory += entry("Workbook", 2, workbook_start, workbook_size)
    directory += b"\x00" * (SECTOR_SIZE - len(directory))

    def fat_bytes() -> bytes:
        raw = b"".join(struct.pack("<I", value) for value in fat)
        return raw + b"\xFF" * (SECTOR_SIZE - len(raw))

    body = b""
    if mini:
        body += root_stream + directory + b"".join(struct.pack("<I", value) for value in minifat) + fat_bytes()
    else:
        padded = stream + b"\x00" * (-len(stream) % SECTOR_SIZE)
        body += padded + directory + fat_bytes()
    return bytes(header) + body
