"""Read ETerSetup configuration as evidence, without inferring physical units."""
from pathlib import Path
import xml.etree.ElementTree as ET


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def element_value(element):
    children = list(element)
    if not children and not element.attrib:
        return (element.text or "").strip()
    result = {}
    if element.attrib:
        result["@attributes"] = dict(element.attrib)
    if (element.text or "").strip():
        result["#text"] = element.text.strip()
    for child in children:
        result.setdefault(local_name(child.tag), []).append(element_value(child))
    return result


def parse_setup(path):
    raw = Path(path).read_bytes()
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("SET 含不支持的 XML 实体声明")
    root = ET.fromstring(raw)
    if local_name(root.tag) != "ETerSetup":
        raise ValueError("SET 不是受支持的 ETerSetup 配置")
    channels = []
    for listing in root:
        if local_name(listing.tag) != "DataChannelList":
            continue
        for channel in listing:
            fields = {local_name(child.tag): child for child in channel}
            def text(name):
                child = fields.get(name)
                return "" if child is None else (child.text or "").strip()
            frequency = fields.get("Frequency")
            channels.append({
                "type": next((value for key, value in channel.attrib.items()
                              if local_name(key) == "type"), local_name(channel.tag)),
                "id": text("ChannelID"), "name": text("ChannelName"),
                "channel_type": text("ChannelType"),
                "frequency": element_value(frequency) if frequency is not None else None,
                "voltscale": text("Voltscale"), "rotation": text("Rotation"),
                "configuration": element_value(channel),
            })
    if not channels:
        raise ValueError("ETerSetup 缺少通道配置")
    return {"format": "ETerSetup", "parser_version": 1, "channels": channels,
            "configuration": element_value(root),
            "physical_calibration": "unconfirmed"}
