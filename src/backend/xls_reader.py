"""Read-only reader for legacy .xls workbooks (OLE2 compound file + BIFF5/BIFF8).

The backend must stay on the Python standard library, so this module implements
the minimal compound-document and BIFF record parsing needed to import the
standard result tables. It covers the records written by Excel 97-2016 (BIFF8)
plus the older BIFF5 label/number records, and exposes a small openpyxl-like
surface (worksheets / sheetnames / sheet rows) so the import pipeline can treat
.xls and .xlsx files the same way.

Limitations (deliberate): no formula evaluation (cached results are used), no
style/format interpretation, no charts or macro sheet content, no write
support. Values that cannot be represented are returned as text or None and
never invented.
"""
from __future__ import annotations

import struct
from pathlib import Path

OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
# Sector ids at or above this value are special markers, not real sectors.
SPECIAL_SECTOR = 0xFFFFFFF0
FREESECTOR = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECTOR = 0xFFFFFFFD
DIFSECTOR = 0xFFFFFFFC

# BIFF record ids used by this reader.
_BOF = 0x0809
_EOF = 0x000A
_BOUNDSHEET = 0x0085
_SST = 0x00FC
_CONTINUE = 0x003C
_CODEPAGE = 0x00DA
_LABELSST = 0x00FD
_LABEL = 0x0204
_NUMBER = 0x0203
_RK = 0x027E
_MULRK = 0x00BD
_FORMULA = 0x0006
_STRING = 0x0207
_BLANK = 0x0201
_MULBLANK = 0x00BE
_BOOLERR = 0x0205

# Records whose payloads are parsed with chunk-aware string readers.
_CHUNKED_RECORDS = {_SST, _LABEL, _STRING}

_ERROR_CODES = {
    0x00: "#NULL!", 0x07: "#DIV/0!", 0x0F: "#VALUE!", 0x17: "#REF!",
    0x1D: "#NAME?", 0x24: "#NUM!", 0x2A: "#N/A", 0x2B: "#GETTING_DATA",
}

_CODEPAGE_ALIASES = {936: "gbk", 950: "big5", 932: "cp932", 949: "cp949", 1250: "cp1250",
                     1251: "cp1251", 1252: "cp1252", 1253: "cp1253", 1254: "cp1254",
                     1255: "cp1255", 1256: "cp1256", 1257: "cp1257", 1258: "cp1258"}


class XlsError(ValueError):
    """Raised when a file is not a supported .xls workbook."""


class _Cell:
    __slots__ = ("value", "row", "column")

    def __init__(self, value, row: int, column: int):
        self.value = value
        self.row = row
        self.column = column

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"_Cell({self.value!r}, r{self.row}, c{self.column})"


class _Sheet:
    """One worksheet holding a sparse {(row, column): value} grid."""

    def __init__(self, title: str = ""):
        self.title = title
        self.state = "visible"
        self._cells: dict[tuple[int, int], object] = {}
        self.max_row = 0
        self.max_column = 0

    def _put(self, row: int, column: int, value):
        if not 1 <= row <= 0xFFFF or not 1 <= column <= 0xFFFF:
            return
        self._cells[(row, column)] = value
        if row > self.max_row:
            self.max_row = row
        if column > self.max_column:
            self.max_column = column

    def cell(self, row: int, column: int):
        return _Cell(self._cells.get((row, column)), row, column)

    def __getitem__(self, row_number: int):
        if not isinstance(row_number, int):
            raise TypeError("工作表行号必须为整数")
        return [self.cell(row_number, column) for column in range(1, self.max_column + 1)]

    def iter_rows(self, min_row: int = 1, max_row: int | None = None, min_col: int = 1,
                  max_col: int | None = None, values_only: bool = False):
        last_row = self.max_row if max_row is None else min(self.max_row, max_row)
        last_col = self.max_column if max_col is None else min(self.max_column, max_col)
        for row in range(max(1, min_row), max(0, last_row) + 1):
            columns = range(max(1, min_col), last_col + 1)
            if values_only:
                yield tuple(self._cells.get((row, column)) for column in columns)
            else:
                yield [self.cell(row, column) for column in columns]

    def row_values(self, row_number: int):
        return [self._cells.get((row_number, column)) for column in range(1, self.max_column + 1)]


class _Book:
    def __init__(self, sheets: list[_Sheet]):
        self._sheets = sheets
        self._by_name = {sheet.title: sheet for sheet in sheets}
        self.closed = False

    @property
    def worksheets(self):
        return list(self._sheets)

    @property
    def sheetnames(self):
        return [sheet.title for sheet in self._sheets]

    def __getitem__(self, name: str):
        try:
            return self._by_name[name]
        except KeyError:
            raise KeyError(f"工作表不存在：{name}") from None

    def close(self):
        self.closed = True


class _ChunkCursor:
    """Cursor over the chunks (record payload + CONTINUE payloads) of one record.

    BIFF strings may cross a CONTINUE boundary; every continuation restarts with
    a fresh flags byte, so plain concatenation is not valid for those records.
    """

    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.ci = 0
        self.pos = 0

    def at_end(self) -> bool:
        return self.pos >= len(self.chunks[self.ci])

    def next_chunk(self):
        if self.ci + 1 >= len(self.chunks):
            raise XlsError("记录数据被 CONTINUE 边界截断")
        self.ci += 1
        self.pos = 0

    def read(self, count: int) -> bytes:
        parts, remaining = [], count
        while remaining > 0:
            if self.at_end():
                self.next_chunk()
            take = min(remaining, len(self.chunks[self.ci]) - self.pos)
            parts.append(self.chunks[self.ci][self.pos:self.pos + take])
            self.pos += take
            remaining -= take
        return b"".join(parts)

    def skip(self, count: int):
        self.read(count)


class _CompoundFile:
    """Minimal OLE2 (Compound File Binary) reader for the Workbook stream."""

    def __init__(self, data: bytes):
        if len(data) < 512 or data[:8] != OLE_SIGNATURE:
            raise XlsError("不是有效的 .xls 文件（缺少 OLE2 复合文档头）")
        self.data = data
        sector_shift, mini_shift = struct.unpack_from("<HH", data, 0x1E)
        self.sector_size = 1 << sector_shift
        self.mini_sector_size = 1 << mini_shift
        self.mini_cutoff = struct.unpack_from("<I", data, 0x38)[0] or 4096
        fat_count = struct.unpack_from("<I", data, 0x2C)[0]
        dir_start = struct.unpack_from("<I", data, 0x30)[0]
        mini_fat_start = struct.unpack_from("<I", data, 0x3C)[0]
        mini_fat_count = struct.unpack_from("<I", data, 0x40)[0]
        difat_start = struct.unpack_from("<I", data, 0x44)[0]
        difat_count = struct.unpack_from("<I", data, 0x48)[0]
        if not 64 <= self.sector_size <= 65536 or len(data) < self.sector_size:
            raise XlsError(".xls 文件的扇区大小无效")

        difat = [value for value in struct.unpack_from("<109I", data, 0x4C)
                 if value < SPECIAL_SECTOR]
        sector = difat_start
        for _ in range(difat_count):
            if sector >= SPECIAL_SECTOR or (sector + 1) * self.sector_size > len(data):
                break
            block = self._sector(sector)
            entries = struct.unpack(f"<{self.sector_size // 4}I", block)
            difat.extend(value for value in entries[:-1] if value < SPECIAL_SECTOR)
            sector = entries[-1]

        fat: list[int] = []
        for fat_sector in difat[:fat_count or len(difat)]:
            if fat_sector >= SPECIAL_SECTOR:
                continue
            fat.extend(struct.unpack(f"<{self.sector_size // 4}I", self._sector(fat_sector)))
        self.fat = fat

        mini_fat: list[int] = []
        sector, guard = mini_fat_start, 0
        while sector < SPECIAL_SECTOR and guard <= mini_fat_count:
            mini_fat.extend(struct.unpack(f"<{self.sector_size // 4}I", self._sector(sector)))
            sector = fat[sector] if sector < len(fat) else ENDOFCHAIN
            guard += 1
        self.mini_fat = mini_fat

        self.entries: dict[str, tuple[int, int]] = {}
        self._root_stream = b""
        for name, kind, start, size in self._directory_chain(dir_start):
            if kind == 5:
                self._root_stream = self._read_fat_chain(start, size)
            elif kind == 2 and name:
                self.entries[name.lower()] = (start, size)

    def _sector(self, sector: int) -> bytes:
        start = (sector + 1) * self.sector_size
        return self.data[start:start + self.sector_size]

    def _read_fat_chain(self, start: int, size: int) -> bytes:
        parts, sector, guard = [], start, 0
        while sector < SPECIAL_SECTOR and sector < len(self.fat) and guard <= len(self.fat) + 2:
            parts.append(self._sector(sector))
            sector = self.fat[sector]
            guard += 1
        data = b"".join(parts)
        return data[:size] if size else data

    def _read_mini_chain(self, start: int, size: int) -> bytes:
        parts, sector, guard = [], start, 0
        while sector < SPECIAL_SECTOR and sector < len(self.mini_fat) and guard <= len(self.mini_fat) + 2:
            offset = sector * self.mini_sector_size
            parts.append(self._root_stream[offset:offset + self.mini_sector_size])
            sector = self.mini_fat[sector]
            guard += 1
        data = b"".join(parts)
        return data[:size] if size else data

    def _directory_chain(self, start: int):
        data = self._read_fat_chain(start, 0)
        for offset in range(0, len(data) - 127, 128):
            entry = data[offset:offset + 128]
            name_length = struct.unpack_from("<H", entry, 0x40)[0]
            kind = entry[0x42]
            start_sector = struct.unpack_from("<I", entry, 0x74)[0]
            size = struct.unpack_from("<Q", entry, 0x78)[0] & 0xFFFFFFFF
            if kind not in (1, 2, 5) or name_length < 2:
                continue
            raw = entry[:name_length - 2]
            name = raw.decode("utf-16-le", "replace").rstrip("\x00")
            yield name, kind, start_sector, size

    def stream(self, *names: str) -> bytes:
        for name in names:
            entry = self.entries.get(name.lower())
            if not entry:
                continue
            start, size = entry
            if size and size < self.mini_cutoff and self._root_stream:
                return self._read_mini_chain(start, size)
            return self._read_fat_chain(start, size)
        raise XlsError("未找到 Workbook 流，可能不是 Excel 工作簿")


def _iter_records(stream: bytes):
    """Yield (record_id, chunks) where chunks is the payload plus CONTINUE payloads."""
    offset, total = 0, len(stream)
    while offset + 4 <= total:
        record_id, length = struct.unpack_from("<HH", stream, offset)
        offset += 4
        payload = stream[offset:offset + length]
        if len(payload) != length:
            raise XlsError("BIFF 记录长度超出文件范围")
        offset += length
        chunks = [payload]
        keep_chunks = record_id in _CHUNKED_RECORDS
        while offset + 4 <= total:
            next_id, next_length = struct.unpack_from("<HH", stream, offset)
            if next_id != _CONTINUE:
                break
            offset += 4
            chunk = stream[offset:offset + next_length]
            if len(chunk) != next_length:
                raise XlsError("BIFF CONTINUE 记录长度超出文件范围")
            offset += next_length
            if keep_chunks:
                chunks.append(chunk)
            else:
                chunks[0] += chunk
        yield record_id, chunks


def _biff_string(cursor: _ChunkCursor, codepage: str, biff5: bool) -> str:
    """Read a long (2-byte length) BIFF string; handles CONTINUE flag restarts."""
    if biff5:
        length = struct.unpack("<H", cursor.read(2))[0]
        return cursor.read(length).decode(codepage, "replace") if length else ""
    length = struct.unpack("<H", cursor.read(2))[0]
    flags = cursor.read(1)[0]
    runs = struct.unpack("<H", cursor.read(2))[0] if flags & 0x08 else 0
    ext_size = struct.unpack("<I", cursor.read(4))[0] if flags & 0x04 else 0
    high_byte = bool(flags & 0x01)
    parts: list[bytes] = []
    remaining = length
    while remaining > 0:
        if cursor.at_end():
            cursor.next_chunk()
            high_byte = bool(cursor.read(1)[0] & 0x01)
        room = len(cursor.chunks[cursor.ci]) - cursor.pos
        take = min(remaining, room // 2 if high_byte else room)
        if take <= 0:
            cursor.next_chunk()
            high_byte = bool(cursor.read(1)[0] & 0x01)
            continue
        parts.append(cursor.read(take * 2 if high_byte else take))
        remaining -= take
    if runs:
        cursor.skip(runs * 4)
    if ext_size:
        cursor.skip(ext_size)
    raw = b"".join(parts)
    return raw.decode("utf-16-le", "replace") if high_byte else raw.decode(codepage, "replace")


def _boundsheet_name(payload: bytes, codepage: str, biff5: bool) -> str:
    """Read a BOUNDSHEET sheet name.

    Standard BIFF8 stores cch(1)+flags(1)+chars. Some non-standard writers
    (observed in WPS-produced .xls files) omit the length/flags entirely and
    put the 8-bit name directly after the fixed header, and may use
    non-standard sheet types, so all three layouts are attempted in order.
    """
    rest = payload[8:]
    if not rest:
        return ""
    if biff5:
        length = rest[0]
        if 0 < length <= len(rest) - 1:
            return rest[1:1 + length].decode(codepage, "replace")
        return rest.decode(codepage, "replace")
    length, flags = rest[0], rest[1] if len(rest) > 1 else 0
    expected = 2 + (length * 2 if flags & 0x01 else length)
    if len(rest) >= 2 and expected == len(rest):
        raw = rest[2:]
        return raw.decode("utf-16-le", "replace") if flags & 0x01 else raw.decode(codepage, "replace")
    if rest[0] == len(rest) - 1:  # 1-byte length + 8-bit characters
        return rest[1:].decode(codepage, "replace")
    return rest.decode(codepage, "replace")


def _rk_value(rk: int):
    signed = struct.unpack("<i", struct.pack("<I", rk))[0]
    if signed & 0x02:
        value = float(signed >> 2)
    else:
        value = struct.unpack("<d", struct.pack("<Q", (rk & 0xFFFFFFFC) << 32))[0]
    if rk & 0x01:
        value = value / 100.0
    return _normalize_number(value)


def _normalize_number(value: float):
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return int(value)
    return value


def _cell_address(payload: bytes):
    row, column = struct.unpack_from("<HH", payload, 0)
    return row + 1, column + 1


def _parse_sst(chunks: list[bytes], codepage: str, biff5: bool) -> list[str]:
    unique = struct.unpack_from("<I", chunks[0], 4)[0]
    cursor = _ChunkCursor(chunks)
    cursor.pos = 8
    return [_biff_string(cursor, codepage, biff5) for _ in range(unique)]


def _parse_workbook(stream: bytes) -> _Book:
    records = list(_iter_records(stream))
    if not records:
        raise XlsError(".xls 文件为空")
    first_id, first_chunks = records[0]
    if first_id != _BOF:
        raise XlsError("不是有效的 BIFF 工作簿（缺少 BOF 记录）")
    version = struct.unpack_from("<H", first_chunks[0], 0)[0]
    biff5 = version <= 0x0500
    codepage = "cp1252"
    strings: list[str] = []
    # One slot per BOUNDSHEET entry; worksheet/macro BOF substreams fill them in
    # order so charts and other embedded substreams cannot shift the mapping.
    slots: list[dict] = []
    current: dict | None = None
    pending_formula: tuple[int, int] | None = None

    for record_id, chunks in records[1:]:
        payload = chunks[0]
        if record_id == _BOF:
            substream = struct.unpack_from("<H", payload, 2)[0] if len(payload) >= 4 else 0x0010
            if substream == 0x0010:
                current = next((slot for slot in slots if slot["sheet"] is None), None)
                if current is None:
                    current = {"name": "", "kind": 0x00, "sheet": None}
                    slots.append(current)
                current["sheet"] = _Sheet()
                pending_formula = None
            else:
                current = None
            continue
        if record_id == _EOF:
            current = None
            continue
        if current is None:
            if record_id == _CODEPAGE and len(payload) >= 2:
                codepage = _CODEPAGE_ALIASES.get(struct.unpack_from("<H", payload, 0)[0], "cp1252")
            elif record_id == _BOUNDSHEET and len(payload) >= 8:
                kind = struct.unpack_from("<H", payload, 6)[0]
                name = _boundsheet_name(payload, codepage, biff5)
                slots.append({"name": name, "kind": kind, "sheet": None})
            elif record_id == _SST:
                strings = _parse_sst(chunks, codepage, biff5)
            continue

        sheet = current["sheet"]
        if sheet is None:
            continue
        if record_id == _LABELSST and len(payload) >= 10:
            row, column = _cell_address(payload)
            sst_index = struct.unpack_from("<I", payload, 6)[0]
            sheet._put(row, column, strings[sst_index] if 0 <= sst_index < len(strings) else None)
        elif record_id == _LABEL:
            row, column = _cell_address(payload)
            cursor = _ChunkCursor(chunks)
            cursor.pos = 6
            sheet._put(row, column, _biff_string(cursor, codepage, biff5))
        elif record_id == _NUMBER and len(payload) >= 14:
            row, column = _cell_address(payload)
            sheet._put(row, column, _normalize_number(struct.unpack_from("<d", payload, 6)[0]))
        elif record_id == _RK and len(payload) >= 10:
            row, column = _cell_address(payload)
            sheet._put(row, column, _rk_value(struct.unpack_from("<I", payload, 6)[0]))
        elif record_id == _MULRK and len(payload) >= 6:
            row, _ = _cell_address(payload)
            first_column = struct.unpack_from("<H", payload, 2)[0]
            for offset in range((len(payload) - 6) // 6):
                rk = struct.unpack_from("<I", payload, 6 + offset * 6)[0]
                sheet._put(row, first_column + offset + 1, _rk_value(rk))
        elif record_id == _MULBLANK and len(payload) >= 6:
            row, _ = _cell_address(payload)
            first_column = struct.unpack_from("<H", payload, 2)[0]
            for offset in range((len(payload) - 6) // 2):
                sheet._put(row, first_column + offset + 1, None)
        elif record_id == _BLANK:
            row, column = _cell_address(payload)
            sheet._put(row, column, None)
        elif record_id == _BOOLERR and len(payload) >= 8:
            row, column = _cell_address(payload)
            value, is_error = payload[6], payload[7]
            sheet._put(row, column, _ERROR_CODES.get(value, "#ERR") if is_error else bool(value))
        elif record_id == _FORMULA and len(payload) >= 20:
            row, column = _cell_address(payload)
            result = payload[6:14]
            if result[6:8] == b"\xff\xff":
                kind = result[0]
                if kind == 0x01:
                    pending_formula = (row, column)
                elif kind == 0x02:
                    sheet._put(row, column, bool(result[1]))
                elif kind == 0x03:
                    sheet._put(row, column, _ERROR_CODES.get(result[1], "#ERR"))
            else:
                sheet._put(row, column, _normalize_number(struct.unpack_from("<d", result)[0]))
        elif record_id == _STRING and pending_formula is not None:
            cursor = _ChunkCursor(chunks)
            cursor.pos = 0
            row, column = pending_formula
            sheet._put(row, column, _biff_string(cursor, codepage, biff5))
            pending_formula = None

    # Keep the slots that actually received a worksheet/macro substream; chart
    # and other embedded substreams leave their BOUNDSHEET slot unfilled, so the
    # declared sheet type (which non-standard writers set oddly) is not trusted.
    # Row/column extents come from the cells themselves: the DIMENSIONS record
    # is only a hint and some writers report absurd values (e.g. millions of
    # formatted-but-empty rows).
    ordered: list[_Sheet] = []
    for slot in (slot for slot in slots if slot["sheet"] is not None):
        sheet = slot["sheet"]
        sheet.title = slot["name"] or f"Sheet{len(ordered) + 1}"
        ordered.append(sheet)
    if not ordered:
        raise XlsError(".xls 文件中没有工作表")
    return _Book(ordered)


def load_workbook(path, read_only: bool = True, data_only: bool = True) -> _Book:
    """Open a legacy .xls workbook.

    The signature mirrors openpyxl.load_workbook for the arguments the import
    pipeline uses; cached formula results are always returned because formulas
    are never evaluated here.
    """
    source = Path(path).expanduser()
    if not source.is_file():
        raise XlsError(f"文件不存在：{source}")
    stream = _CompoundFile(source.read_bytes()).stream("Workbook", "Book")
    return _parse_workbook(stream)
