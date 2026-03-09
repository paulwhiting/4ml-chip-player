#!/usr/bin/env python3
"""
4ML Channel Reducer — Read a 4ML file, remove duplicate notes, and pack into
the minimum number of channels (one note per channel at any time). Output the
reduced 4ML to stdout and statistics to stderr.

See docs/4ml.md for 4ML syntax. Duration units: 128ths of a whole note.
"""

import re
import sys
from dataclasses import dataclass, field
from typing import Optional

# --- 4ML constants (from docs/4ml.md) ---
DURATION_128THS = {
    "1": 128, "2": 64, "4": 32, "8": 16, "16": 8, "32": 4, "64": 2, "128": 1,
    "2.": 96, "4.": 48, "8.": 24, "16.": 12, "32.": 6, "64.": 3,
}
DEFAULT_DURATION = "8"
NOTE_NAMES = ("c", "c+", "d", "d+", "e", "e+", "f", "f+", "g", "g+", "a", "a+", "b", "b+")
NOTE_SEMITONES = {name: i for i, name in enumerate(NOTE_NAMES)}  # c=0..b+=11


@dataclass
class NoteEvent:
    """A single note: start and duration in 128ths, pitch as (octave, note_index)."""
    start_128: int
    dur_128: int
    octave: int
    note: str  # e.g. 'c', 'c+', 'd', ...

    def pitch_key(self):
        """Unique key for pitch (octave + semitone)."""
        return (self.octave, NOTE_SEMITONES.get(self.note, 0))

    def duplicate_key(self):
        """Key for duplicate detection: same start, duration, pitch."""
        return (self.start_128, self.dur_128, self.pitch_key())


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def parse_and_strip(content: str) -> tuple[list[str], list[str]]:
    """Remove comments and whitespace, return (channel_strings, pattern_strings).
    Channel order preserved by C0, C1, ...; pattern by P1, P2, ...
    """
    s = content
    s = re.sub(r";.*?(?=\n|$)", "\n", s)
    s = re.sub(r"/\*[\s\S]*?\*/", "", s)
    s = re.sub(r"\s+", "", s)

    pattern = re.compile(r"C(\d+)")
    channel_nums = sorted(set(int(m.group(1)) for m in pattern.finditer(s)), reverse=False)
    max_c = max(channel_nums) if channel_nums else -1

    channel_data = []
    for x in range(max_c + 1):
        # Match Cx (not Cx0) then content until next C or P
        parts = re.findall(rf"C{x}(?!\d)([^CP]*)", s)
        channel_data.append("".join(parts))

    while "" in channel_data:
        channel_data.remove("")

    pattern_pat = re.compile(r"P(\d+)")
    pattern_nums = sorted(set(int(m.group(1)) for m in pattern_pat.finditer(s)))
    max_p = max(pattern_nums) if pattern_nums else -1

    pattern_data = []
    for x in range(max_p + 1):
        parts = re.findall(rf"P{x}(?!\d)([^PC]*)", s)
        pattern_data.append("".join(parts))

    while "" in pattern_data:
        pattern_data.remove("")

    return channel_data, pattern_data


MAX_LOOP_EXPAND = 256  # cap to avoid huge expansion from e.g. [255 r1]


def expand_loops(s: str) -> str:
    """Expand [N ... ] to N copies of the inner content (capped)."""
    out = []
    i = 0
    while i < len(s):
        if s[i] == "[":
            j = i + 1
            count_str = ""
            while j < len(s) and s[j].isdigit():
                count_str += s[j]
                j += 1
            if not count_str:
                i += 1
                continue
            count = min(int(count_str), MAX_LOOP_EXPAND)
            depth = 1
            start = j
            while j < len(s) and depth > 0:
                if s[j] == "[":
                    depth += 1
                elif s[j] == "]":
                    depth -= 1
                j += 1
            inner = s[start : j - 1]
            expanded_inner = expand_loops(inner)
            for _ in range(count):
                out.append(expanded_inner)
            i = j
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def expand_patterns(channel_str: str, pattern_data: list[str], depth: int = 0) -> str:
    """Replace pN with pattern body. Recursion limit to avoid infinite macro loops."""
    if depth > 50:
        return channel_str
    out = []
    i = 0
    while i < len(channel_str):
        if channel_str[i] == "p":
            j = i + 1
            num_str = ""
            while j < len(channel_str) and channel_str[j].isdigit():
                num_str += channel_str[j]
                j += 1
            if num_str:
                idx = int(num_str)
                if 1 <= idx <= len(pattern_data):
                    body = expand_loops(pattern_data[idx - 1])
                    body = expand_patterns(body, pattern_data, depth + 1)
                    out.append(body)
                i = j
                continue
        out.append(channel_str[i])
        i += 1
    return "".join(out)


def duration_to_128ths(dur_str: str) -> int:
    if dur_str in DURATION_128THS:
        return DURATION_128THS[dur_str]
    return DURATION_128THS.get(DEFAULT_DURATION, 16)


def parse_sequence_to_events(seq: str) -> list[NoteEvent]:
    """Walk sequence and yield (start_128, dur_128, pitch or None for rest)."""
    events: list[NoteEvent] = []
    i = 0
    tick = 0
    prev_duration = DEFAULT_DURATION
    octave = 3  # 4ML default

    while i < len(seq):
        c = seq[i]

        # Note or rest
        if c in "r" or c in "cdefgab":
            note_char = c
            i += 1
            if i < len(seq) and seq[i] in "+#":
                note_char = c + "+"
                i += 1
            dur_str = ""
            while i < len(seq) and seq[i].isdigit() and len(dur_str) < 3:
                dur_str += seq[i]
                i += 1
            if i < len(seq) and seq[i] == ".":
                dur_str += "."
                i += 1
            if not dur_str:
                dur_str = prev_duration
            else:
                prev_duration = dur_str

            dur_128 = duration_to_128ths(dur_str)

            if note_char == "r":
                tick += dur_128
                continue

            if note_char not in NOTE_SEMITONES:
                tick += dur_128
                continue

            events.append(NoteEvent(
                start_128=tick,
                dur_128=dur_128,
                octave=octave,
                note=note_char,
            ))
            tick += dur_128
            continue

        if c == "o":
            i += 1
            val = ""
            while i < len(seq) and seq[i].isdigit():
                val += seq[i]
                i += 1
            if val:
                octave = int(val)  # 1-based in 4ML; we store 1-based for output
            continue

        if c in "<>":
            if c == "<":
                octave = max(0, octave - 1)
            else:
                octave = min(8, octave + 1)
            i += 1
            continue

        if c in "v@tKsF":
            i += 1
            if i < len(seq) and seq[i] == "-":
                i += 1
            while i < len(seq) and seq[i].isdigit():
                i += 1
            continue

        if c in "&^":
            i += 1
            continue

        if c == "[" or c == "]":
            i += 1
            continue

        if c == "i":
            i += 1
            while i < len(seq) and seq[i].isdigit():
                i += 1
            continue

        i += 1

    return events


def collect_all_notes(channel_events: list[list[NoteEvent]]) -> list[NoteEvent]:
    """Deduplicate: same (start, duration, pitch) -> keep one."""
    seen = set()
    out = []
    for events in channel_events:
        for ev in events:
            key = ev.duplicate_key()
            if key not in seen:
                seen.add(key)
                out.append(ev)
    return out


def pack_into_channels(notes: list[NoteEvent]) -> list[list[NoteEvent]]:
    """Sort by start, assign each note to first free channel. Returns list of channels."""
    if not notes:
        return []
    sorted_notes = sorted(notes, key=lambda n: (n.start_128, n.duplicate_key()))
    channels: list[list[NoteEvent]] = []
    channel_end: list[int] = []

    for n in sorted_notes:
        assigned = False
        for ch in range(len(channels)):
            if channel_end[ch] <= n.start_128:
                channels[ch].append(n)
                channel_end[ch] = n.start_128 + n.dur_128
                assigned = True
                break
        if not assigned:
            channels.append([n])
            channel_end.append(n.start_128 + n.dur_128)

    return channels


def is_rest_only_or_empty(events: list[NoteEvent]) -> bool:
    return len(events) == 0


# Standard 4ML durations (128ths) in descending order for greedy decomposition
_DURATION_ORDER = [
    (128, "1"), (96, "2."), (64, "2"), (48, "4."), (32, "4"), (24, "8."), (16, "8"),
    (12, "16."), (8, "16"), (6, "32."), (4, "32"), (3, "64."), (2, "64"), (1, "128"),
]


def ticks_to_duration_str(tick: int) -> str:
    """Map 128ths to a single 4ML duration string if exact match."""
    if tick <= 0:
        return "8"
    for val, name in _DURATION_ORDER:
        if val == tick:
            return name
    return "8"


def decompose_ticks_to_rests(rest_ticks: int) -> list[str]:
    """Decompose rest_ticks (128ths) into a list of 4ML duration strings that sum exactly.
    Avoids timing drift when a gap has no single standard duration (e.g. 56 = 32+24 = r4 r8.)."""
    if rest_ticks <= 0:
        return []
    out: list[str] = []
    remaining = rest_ticks
    for val, name in _DURATION_ORDER:
        while remaining >= val:
            out.append("r" + name)
            remaining -= val
    return out


def events_to_4ml_channel(events: list[NoteEvent], tempo: int = 50) -> str:
    """Serialize one channel's events to 4ML string (with rests for gaps)."""
    if not events:
        return f"t{tempo} r1"
    parts = [f"t{tempo}"]
    cur_tick = 0
    for n in sorted(events, key=lambda e: e.start_128):
        if n.start_128 > cur_tick:
            for rest_token in decompose_ticks_to_rests(n.start_128 - cur_tick):
                parts.append(rest_token)
            cur_tick = n.start_128
        parts.append(f"o{n.octave}" + n.note + ticks_to_duration_str(n.dur_128))
        cur_tick = n.start_128 + n.dur_128
    return " ".join(parts)


def main() -> None:
    if len(sys.argv) < 2:
        log("Usage: 4ml-reduce-channels.py <file.4ml>")
        sys.exit(1)

    path = sys.argv[1]
    try:
        with open(path, "r") as f:
            content = f.read()
    except FileNotFoundError:
        log(f"File not found: {path}")
        sys.exit(1)

    channel_strings, pattern_data = parse_and_strip(content)
    total_input_channels = len(channel_strings)
    total_input_notes = 0
    channel_events: list[list[NoteEvent]] = []
    empty_or_rest_only: list[int] = []

    for ch_idx, ch_str in enumerate(channel_strings):
        expanded = expand_patterns(ch_str, pattern_data)
        expanded = expand_loops(expanded)
        events = parse_sequence_to_events(expanded)
        if not events:
            empty_or_rest_only.append(ch_idx)
        total_input_notes += len(events)
        channel_events.append(events)

    all_notes = collect_all_notes(channel_events)
    packed = pack_into_channels(all_notes)
    # Drop empty channels (we already only pack note-bearing channels)
    packed = [ch for ch in packed if not is_rest_only_or_empty(ch)]
    total_output_channels = len(packed)
    total_output_notes = sum(len(ch) for ch in packed)
    duplicates_removed = total_input_notes - len(all_notes)
    channels_dropped_empty = len(empty_or_rest_only)
    channels_saved = total_input_channels - total_output_channels

    # Output reduced 4ML to stdout
    tempo = 50
    for i, ch_events in enumerate(packed):
        print(f"C{i + 1} {events_to_4ml_channel(ch_events, tempo)}")
    if not packed:
        print("C1 t50 r1")

    # Statistics to stderr
    log("4ML channel reduction statistics:")
    log(f"  Input channels:        {total_input_channels}")
    log(f"  Output channels:       {total_output_channels}")
    log(f"  Channels saved:        {channels_saved}")
    log(f"  Input note events:     {total_input_notes}")
    log(f"  Output note events:    {total_output_notes}")
    log(f"  Duplicate notes removed: {duplicates_removed}")
    log(f"  Empty/rest-only channels dropped: {channels_dropped_empty}")



if __name__ == "__main__":
    main()
