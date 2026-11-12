"""Exact adjudications visually checked against the original official PDFs.

These entries apply only to the identified records and confirmed signed
maintenance offset. They never change the stored source measurements.
PDF page numbers include the cover, rather than the printed page number.
"""

VERIFIED = (
    {
        "old": "H101", "new": "H102", "unit": 1, "tube": 2, "shift": 42,
        "current": ("P3", 1.46, 21), "historical": ("P3", 1.12, 23),
        "comparison": "R",
        "source": "AA141202615MFXA45SS，PDF第9页：2号管P3原位对应R",
    },
    {
        "old": "F201", "new": "F202", "unit": 2, "tube": 43, "shift": 42,
        "current": ("P5", 20.74, 84), "historical": ("P5", 7.57, 61),
        "comparison": "NI", "covered_position": "P5+42",
        "source": "BL241202615MFXA45SS，PDF第11页：43号管P5为NI，旧显示覆盖另标R1",
    },
    {
        "old": "F102", "new": "F103", "unit": 1, "tube": 42, "shift": 45,
        "current": ("P5+45", 4.39, 47), "historical": ("P4", 4.20, 47),
        "comparison": "R", "display": "R*", "permit_ni": True, "historical_report_location": "P5",
        "source": "BL141203618MFXA45SS，PDF第8至9页：旧报告P4误记，应为P5",
    },
) + tuple(
    {
        "old": "H203", "new": "H204", "unit": 2, "tube": 45, "shift": 44,
        "current": (position, new_volts, new_percent),
        "historical": (position, old_volts, old_percent), "comparison": "R",
        "source": f"AA241204610MFXA45SS，PDF第12页：45号管{position}原位对应R",
    }
    for position, old_volts, old_percent, new_volts, new_percent in (
        ("P1", 1.75, 27, 1.73, 26),
        ("P1+44", 2.33, 33, 2.18, 31),
        ("P1+86", 2.12, 31, 2.00, 29),
        ("P4", 2.74, 37, 2.76, 36),
        ("P4+44", 4.44, 48, 4.32, 47),
        ("P4+86", 4.37, 48, 4.14, 46),
    )
)
