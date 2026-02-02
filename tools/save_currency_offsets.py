#!/usr/bin/env python3
import argparse
import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass
class Entry:
    name: str
    value: int
    start: int
    end: int
    payload: bytes


def decode_varint(buf: bytes, idx: int) -> Tuple[int, int]:
    shift = 0
    result = 0
    while True:
        if idx >= len(buf):
            raise ValueError("Unexpected end of buffer while decoding varint")
        byte = buf[idx]
        result |= (byte & 0x7F) << shift
        idx += 1
        if byte < 0x80:
            return result, idx
        shift += 7


def encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("Varint cannot encode negative values")
    out = bytearray()
    while True:
        to_write = value & 0x7F
        value >>= 7
        if value:
            out.append(to_write | 0x80)
        else:
            out.append(to_write)
            break
    return bytes(out)


def parse_payload(payload: bytes) -> Tuple[str, Dict[int, List[Tuple[int, int, bytes]]]]:
    idx = 0
    fields: Dict[int, List[Tuple[int, int, bytes]]] = {}
    name = ""
    while idx < len(payload):
        tag, idx = decode_varint(payload, idx)
        field_num = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 0:
            value, idx = decode_varint(payload, idx)
            fields.setdefault(field_num, []).append((wire_type, value, b""))
        elif wire_type == 2:
            length, idx = decode_varint(payload, idx)
            raw = payload[idx:idx + length]
            idx += length
            fields.setdefault(field_num, []).append((wire_type, length, raw))
            if field_num == 1:
                try:
                    name = raw.decode("utf-8")
                except UnicodeDecodeError:
                    name = ""
        else:
            raise ValueError(f"Unsupported wire type {wire_type} in payload")
    return name, fields


def rebuild_payload(fields: Dict[int, List[Tuple[int, int, bytes]]]) -> bytes:
    out = bytearray()
    for field_num in sorted(fields.keys()):
        for wire_type, length_or_value, raw in fields[field_num]:
            tag = (field_num << 3) | wire_type
            out += encode_varint(tag)
            if wire_type == 0:
                out += encode_varint(length_or_value)
            elif wire_type == 2:
                out += encode_varint(length_or_value)
                out += raw
            else:
                raise ValueError(f"Unsupported wire type {wire_type} in rebuild")
    return bytes(out)


def find_entries(decoded: bytes) -> List[Entry]:
    entries: List[Entry] = []
    idx = 0
    while idx < len(decoded):
        if decoded[idx] != 0x1A:
            idx += 1
            continue
        length, next_idx = decode_varint(decoded, idx + 1)
        payload_start = next_idx
        payload_end = payload_start + length
        if payload_end > len(decoded):
            idx += 1
            continue
        payload = decoded[payload_start:payload_end]
        try:
            name, fields = parse_payload(payload)
        except ValueError:
            idx += 1
            continue
        if name and 1 in fields and 3 in fields:
            value_field = fields[3][0]
            if value_field[0] == 0:
                value = value_field[1]
                entries.append(Entry(name=name, value=value, start=idx, end=payload_end, payload=payload))
        idx = payload_end
    return entries


def update_entry(decoded: bytes, entry: Entry, new_value: int) -> bytes:
    name, fields = parse_payload(entry.payload)
    if name != entry.name:
        raise ValueError("Entry payload name mismatch")
    if 3 not in fields:
        raise ValueError("Entry missing value field")
    wire_type, _, raw = fields[3][0]
    if wire_type != 0:
        raise ValueError("Entry value field is not varint")
    fields[3][0] = (wire_type, new_value, raw)
    rebuilt = rebuild_payload(fields)
    length_encoded = encode_varint(len(rebuilt))
    updated = bytearray()
    updated += decoded[:entry.start]
    updated.append(0x1A)
    updated += length_encoded
    updated += rebuilt
    updated += decoded[entry.end:]
    return bytes(updated)


def parse_amounts(values: List[str]) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"Invalid amount format: {item}")
        name, raw = item.split("=", 1)
        result[name] = int(raw)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect currency entries in the base64-encoded player save file."
    )
    parser.add_argument("--input", default="player", help="Path to the player save file")
    parser.add_argument(
        "--actual",
        action="append",
        default=[],
        help="Actual in-game amounts, e.g. gold=75 (can be repeated)",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        help="Desired in-game amounts to write, e.g. lucky_coin=999 (can be repeated)",
    )
    parser.add_argument(
        "--output",
        help="Optional output path for the updated save file",
    )
    args = parser.parse_args()

    raw = Path(args.input).read_bytes()
    decoded = base64.b64decode(raw)

    entries = {entry.name: entry for entry in find_entries(decoded)}

    print("Found entries:")
    for name in sorted(entries.keys()):
        print(f"- {name}: stored={entries[name].value}")

    actuals = parse_amounts(args.actual) if args.actual else {}
    offsets: Dict[str, int] = {}
    if actuals:
        print("\nOffsets (stored - actual):")
        for name, actual in actuals.items():
            entry = entries.get(name)
            if not entry:
                raise ValueError(f"Missing entry for {name}")
            offset = entry.value - actual
            offsets[name] = offset
            print(f"- {name}: {offset}")

    sets = parse_amounts(args.set) if args.set else {}
    if sets:
        if not offsets:
            raise ValueError("Provide --actual values to compute offsets before --set")
        updated = decoded
        for name, desired in sets.items():
            if name not in offsets:
                raise ValueError(f"Missing offset for {name}. Provide --actual {name}=... first.")
            current_entries = {entry.name: entry for entry in find_entries(updated)}
            if name not in current_entries:
                raise ValueError(f"Missing entry for {name} after update scan.")
            new_value = desired + offsets[name]
            updated = update_entry(updated, current_entries[name], new_value)
            print(f"Updated {name}: stored={new_value}")
        if args.output:
            Path(args.output).write_bytes(base64.b64encode(updated))
            print(f"Wrote updated save to {args.output}")
        else:
            raise ValueError("Provide --output to write updated save data")


if __name__ == "__main__":
    main()
