"""
BLF Parser + DBC Decoder + LTTB Downsampling

Reads Vector BLF log files using python-can, decodes CAN signals using cantools,
and provides downsampled time-series data for visualization.
"""

import math
from collections import defaultdict
from pathlib import Path

import can
import cantools


def load_dbc_files(dbc_paths):
    """Load one or more DBC files and merge into a single database."""
    db = cantools.database.Database()
    for path in dbc_paths:
        db.add_dbc_file(str(path))
    return db


def _build_frame_id_lookup(db):
    """Build a fast {frame_id: message_obj} lookup dict."""
    lookup = {}
    for msg in db.messages:
        lookup[msg.frame_id] = msg
    return lookup


def parse_blf(blf_path, dbc_paths, progress_cb=None):
    """
    Parse a BLF file and decode all signals using DBC definitions.

    Returns:
        dict with keys:
        - signals: dict of "MessageName.SignalName" -> {timestamps, values, unit, message_id, channel}
        - summary: {msg_count, duration, channels, first_timestamp}
        - undecoded_ids: list of {arbitration_id (hex), channel, count}
    """
    db = load_dbc_files(dbc_paths)
    lookup = _build_frame_id_lookup(db)

    # Accumulators
    signal_data = defaultdict(lambda: {
        "timestamps": [],
        "values": [],
        "unit": "",
        "message_id": 0,
        "channel": None,
    })
    undecoded = defaultdict(lambda: {"count": 0, "channel": None})

    msg_count = 0
    first_ts = None
    last_ts = None
    channels = set()

    # Get file size for progress reporting
    file_size = blf_path.stat().st_size if hasattr(blf_path, 'stat') else Path(blf_path).stat().st_size

    # Phase 1: Loading DBC
    if progress_cb:
        progress_cb("loading_dbc", 0, 0)

    with can.BLFReader(str(blf_path)) as reader:
        # Try to estimate total messages from file size (~40-80 bytes per msg)
        est_total = max(file_size // 60, 1)

        if progress_cb:
            progress_cb("parsing", 0, est_total)

        for msg in reader:
            msg_count += 1
            ts = msg.timestamp

            # Report progress every 5000 messages
            if progress_cb and msg_count % 5000 == 0:
                progress_cb("parsing", msg_count, est_total)

            if first_ts is None:
                first_ts = ts
            last_ts = ts

            if msg.channel is not None:
                channels.add(msg.channel)

            frame_id = msg.arbitration_id
            dbc_msg = lookup.get(frame_id)

            if dbc_msg is None:
                hex_id = f"0x{frame_id:03X}"
                undecoded[hex_id]["count"] += 1
                undecoded[hex_id]["channel"] = msg.channel
                continue

            # Handle CAN FD: truncate data if longer than DBC expects
            data = msg.data
            if len(data) > dbc_msg.length:
                data = data[:dbc_msg.length]

            try:
                decoded = dbc_msg.decode(data, decode_choices=False)
            except Exception:
                hex_id = f"0x{frame_id:03X}"
                undecoded[hex_id]["count"] += 1
                undecoded[hex_id]["channel"] = msg.channel
                continue

            for sig_name, value in decoded.items():
                if not isinstance(value, (int, float)):
                    continue

                key = f"{dbc_msg.name}.{sig_name}"
                entry = signal_data[key]
                entry["timestamps"].append(ts)
                entry["values"].append(float(value))
                entry["message_id"] = frame_id
                entry["channel"] = msg.channel

                # Get unit from DBC signal definition
                if not entry["unit"]:
                    for sig in dbc_msg.signals:
                        if sig.name == sig_name:
                            entry["unit"] = sig.unit or ""
                            break

    # Normalize timestamps to start at t=0
    if progress_cb:
        progress_cb("finalizing", msg_count, msg_count)

    if first_ts is not None:
        for entry in signal_data.values():
            entry["timestamps"] = [t - first_ts for t in entry["timestamps"]]

    # Build signal list with stats
    signal_list = []
    for key, entry in sorted(signal_data.items()):
        msg_name, sig_name = key.split(".", 1)
        values = entry["values"]
        signal_list.append({
            "key": key,
            "message_name": msg_name,
            "signal_name": sig_name,
            "channel": entry["channel"],
            "unit": entry["unit"],
            "samples": len(values),
            "min": round(min(values), 4) if values else 0,
            "max": round(max(values), 4) if values else 0,
        })

    # Build undecoded ID list
    undecoded_list = [
        {"arbitration_id": aid, "channel": info["channel"], "count": info["count"]}
        for aid, info in sorted(undecoded.items())
    ]

    duration = (last_ts - first_ts) if (first_ts is not None and last_ts is not None) else 0

    return {
        "signals": dict(signal_data),
        "summary": {
            "msg_count": msg_count,
            "duration": round(duration, 3),
            "channels": sorted(channels),
        },
        "signal_list": signal_list,
        "undecoded_ids": undecoded_list,
    }


def lttb_downsample(timestamps, values, target_points):
    """
    Largest-Triangle-Three-Buckets (LTTB) downsampling.

    Reduces a time series to target_points while preserving visual shape.
    Returns (sampled_timestamps, sampled_values).
    """
    n = len(timestamps)
    if n <= target_points or target_points < 3:
        return timestamps, values

    sampled_ts = [timestamps[0]]
    sampled_vals = [values[0]]

    bucket_size = (n - 2) / (target_points - 2)

    a_index = 0
    a_x = timestamps[0]
    a_y = values[0]

    for i in range(1, target_points - 1):
        # Calculate the average point for the next bucket
        avg_start = int(math.floor((i + 0) * bucket_size)) + 1
        avg_end = int(math.floor((i + 1) * bucket_size)) + 1
        avg_end = min(avg_end, n)

        avg_x = 0.0
        avg_y = 0.0
        avg_count = avg_end - avg_start
        if avg_count <= 0:
            avg_count = 1
            avg_start = min(avg_start, n - 1)
            avg_end = avg_start + 1

        for j in range(avg_start, avg_end):
            avg_x += timestamps[j]
            avg_y += values[j]
        avg_x /= avg_count
        avg_y /= avg_count

        # Find the point in the current bucket with the largest triangle area
        bucket_start = int(math.floor((i - 1) * bucket_size)) + 1
        bucket_end = int(math.floor(i * bucket_size)) + 1
        bucket_end = min(bucket_end, n)

        max_area = -1.0
        max_index = bucket_start

        for j in range(bucket_start, bucket_end):
            area = abs(
                (a_x - avg_x) * (values[j] - a_y)
                - (a_x - timestamps[j]) * (avg_y - a_y)
            )
            if area > max_area:
                max_area = area
                max_index = j

        sampled_ts.append(timestamps[max_index])
        sampled_vals.append(values[max_index])

        a_x = timestamps[max_index]
        a_y = values[max_index]
        a_index = max_index

    # Always include the last point
    sampled_ts.append(timestamps[-1])
    sampled_vals.append(values[-1])

    return sampled_ts, sampled_vals


def get_signal_data(parsed_data, signal_keys, max_points=5000):
    """
    Extract time-series data for selected signals with optional downsampling.

    Args:
        parsed_data: Result from parse_blf()
        signal_keys: List of "MessageName.SignalName" strings
        max_points: Maximum points per signal (LTTB downsampling applied if exceeded)

    Returns:
        dict of signal_key -> {timestamps, values, unit, total_points, returned_points}
    """
    result = {}
    signals = parsed_data["signals"]

    for key in signal_keys:
        if key not in signals:
            continue

        entry = signals[key]
        ts = entry["timestamps"]
        vals = entry["values"]
        total = len(ts)

        if total > max_points:
            ts, vals = lttb_downsample(ts, vals, max_points)

        result[key] = {
            "timestamps": [round(t, 6) for t in ts],
            "values": [round(v, 6) for v in vals],
            "unit": entry["unit"],
            "total_points": total,
            "returned_points": len(ts),
        }

    return result
