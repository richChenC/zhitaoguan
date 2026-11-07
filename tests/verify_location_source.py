"""Compare PI+168 in source XML, parser output and the read-only running DB."""
import hashlib
import json
import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.backend import server


def verify(database):
    database = Path(database).resolve()
    database_hash = hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(row) for row in db.execute(
            "SELECT id,outage,thimble_id,location,percent,datapoint,uid,report_path "
            "FROM findings WHERE is_deleted=0 AND outage='N109' AND thimble_id=1 "
            "AND percent=47 AND location LIKE '%168%'")]
    assert len(rows) == 1, "Expected the reported N109 47% record"
    row = rows[0]
    source = Path(row["report_path"])
    raw_bytes = source.read_bytes()
    source_hash = hashlib.sha256(raw_bytes).hexdigest()
    entries = [entry for entry in ET.fromstring(raw_bytes).findall("ReportEntry")
               if entry.findtext("Row") == str(row["thimble_id"]) and
               entry.findtext("Datapoint") == str(row["datapoint"])]
    assert len(entries) == 1, "Source entry must be identified by tube and datapoint"
    xml_location = entries[0].findtext("Location")
    parsed = [finding for finding in server.parse_report(source)
              if finding.thimble_id == row["thimble_id"] and finding.datapoint == row["datapoint"]]
    assert len(parsed) == 1
    assert xml_location == parsed[0].location == row["location"]
    assert parsed[0].percent == row["percent"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    assert hashlib.sha256(database.read_bytes()).hexdigest() == database_hash
    # This source is structured XML: no OCR participates in its import.
    return dict(passed=True, source=str(source), source_sha256=source_hash,
                database_sha256=database_hash, database_id=row["id"],
                source_uid=entries[0].findtext("Uid"), datapoint=row["datapoint"], depth=row["percent"],
                xml_location=xml_location, parser_location=parsed[0].location,
                database_location=row["location"],
                codepoints=[f"U+{ord(char):04X}" for char in xml_location],
                literal_element_present=b"<Location>PI+168</Location>" in raw_bytes,
                source_and_database_unchanged=True,
                import_method="XML element text; no OCR")


if __name__ == "__main__":
    evidence = verify(sys.argv[1])
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
