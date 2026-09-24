"""
BLF File Cropper

Crops a Vector BLF log file by time ratio using python-can.
Examples:
    python blf_crop.py input.blf -s 0.2 -e 0.8          # Keep middle 60%
    python blf_crop.py input.blf -s 0.0 -e 0.5          # Keep first half
    python blf_crop.py input.blf -s 0.5 -o output.blf   # Keep last 50%
"""

import argparse
import sys
from pathlib import Path

import can


def get_time_range(blf_path):
    """Scan BLF file and return (first_timestamp, last_timestamp, total_messages)."""
    first_ts = None
    last_ts = None
    count = 0
    with can.BLFReader(str(blf_path)) as reader:
        for msg in reader:
            if first_ts is None:
                first_ts = msg.timestamp
            last_ts = msg.timestamp
            count += 1
    return first_ts, last_ts, count


def crop_blf(input_path, output_path, start_ratio=0.0, end_ratio=1.0):
    """
    Crop a BLF file by time ratio.

    Args:
        input_path: Path to input BLF file.
        output_path: Path to output BLF file.
        start_ratio: Start of crop range as ratio (0.0 ~ 1.0).
        end_ratio: End of crop range as ratio (0.0 ~ 1.0).
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        sys.exit(1)

    if not 0.0 <= start_ratio < end_ratio <= 1.0:
        print(f"Error: Invalid range ({start_ratio}, {end_ratio}). Must be 0 <= start < end <= 1.")
        sys.exit(1)

    # Phase 1: Scan time range
    print(f"Scanning: {input_path.name}")
    first_ts, last_ts, total_msgs = get_time_range(input_path)
    if first_ts is None or total_msgs == 0:
        print("Error: BLF file is empty.")
        sys.exit(1)

    duration = last_ts - first_ts
    crop_start_ts = first_ts + duration * start_ratio
    crop_end_ts = first_ts + duration * end_ratio

    print(f"  Total messages : {total_msgs:,}")
    print(f"  Duration       : {duration:.3f} s")
    print(f"  Time range     : {first_ts:.6f} ~ {last_ts:.6f}")
    print(f"  Crop ratio     : {start_ratio:.2%} ~ {end_ratio:.2%}")
    print(f"  Crop time      : {crop_start_ts:.6f} ~ {crop_end_ts:.6f}")
    print()

    # Phase 2: Filter and write
    print(f"Cropping -> {output_path.name}")
    kept = 0
    with can.BLFReader(str(input_path)) as reader:
        with can.BLFWriter(str(output_path)) as writer:
            for msg in reader:
                if crop_start_ts <= msg.timestamp <= crop_end_ts:
                    writer.on_message_received(msg)
                    kept += 1

    out_size = output_path.stat().st_size
    in_size = input_path.stat().st_size

    print(f"  Kept messages  : {kept:,} / {total_msgs:,} ({kept/total_msgs:.1%})")
    print(f"  Output size    : {out_size:,} bytes (input: {in_size:,} bytes, {out_size/in_size:.1%})")
    print("Done.")


def main():
    parser = argparse.ArgumentParser(
        description="Crop a BLF file by time ratio.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s input.blf -s 0.2 -e 0.8        Keep middle 60%%
  %(prog)s input.blf -s 0.0 -e 0.5        Keep first half
  %(prog)s input.blf -s 0.5               Keep last 50%% (default output: input_crop.blf)
""",
    )
    parser.add_argument("input", help="Input BLF file path")
    parser.add_argument("-o", "--output", help="Output BLF file path (default: <input>_crop.blf)")
    parser.add_argument(
        "-s", "--start", type=float, default=0.0,
        help="Start ratio, 0.0 ~ 1.0 (default: 0.0)",
    )
    parser.add_argument(
        "-e", "--end", type=float, default=1.0,
        help="End ratio, 0.0 ~ 1.0 (default: 1.0)",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.with_name(f"{input_path.stem}_crop{input_path.suffix}")

    crop_blf(input_path, output_path, args.start, args.end)


if __name__ == "__main__":
    main()
