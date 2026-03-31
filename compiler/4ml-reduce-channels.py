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
from collections import defaultdict

from compiler import parse_4ml_file, process_mmml_string
from utils import tokenize, tokens_to_string, decompose_notes

# --- 4ML constants (from docs/4ml.md) ---
DURATION_128THS = {
	"1": 128, "2": 64, "4": 32, "8": 16, "16": 8, "32": 4, "64": 2, "128": 1,
	"2.": 96, "4.": 48, "8.": 24, "16.": 12, "32.": 6, "64.": 3,
}
DEFAULT_DURATION = "8"
DEFAULT_OCTAVE = "3"
DEFAULT_VOLUME = "1"
DEFAULT_TEMPO = 64
DEFAULT_INSTRUMENT = 1
NOTE_NAMES = ("c", "c+", "d", "d+", "e", "e+", "f", "f+", "g", "g+", "a", "a+", "b", "b+")
NOTE_SEMITONES = {name: i for i, name in enumerate(NOTE_NAMES)}  # c=0..b+=11


@dataclass
class NoteEvent:
	"""A single note: start and duration in 128ths, pitch as (octave, note_index)."""
	start_128: int
	dur_128: int
	octave: int
	volume: int
	tempo: int
	instrument: int
	note: str  # e.g. 'c', 'c+', 'd', ...
	percussion: bool = False

	def pitch_key(self):
		"""Unique key for pitch (octave + semitone)."""
		return (self.octave, NOTE_SEMITONES.get(self.note, 0))

	def duplicate_key(self):
		"""Key for duplicate detection: same start, duration, pitch."""
		return (self.start_128, self.dur_128, self.pitch_key(), self.instrument, self.percussion)


def log(msg: str) -> None:
	print(msg, file=sys.stderr)


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
	tick = 0
	prev_duration = None
	octave = None
	volume = None
	tempo = None
	instrument = None
	percussion = False

	tokens = tokenize(seq)

	for token in tokens:

		# handle percussion toggle commands
		if token[0] == 'x':
			if len(token) > 1 and token[1:] in ('0', '-'):
				percussion = False
			else:
				# x, x1, x+ all turn percussion on
				percussion = True
			continue

		# support previous duration
		result = process_mmml_string(token, previous_duration=prev_duration, octave=octave, volume=volume, tempo=tempo, instrument=instrument)

		c = token[0]

		if c == 'r':
			tick += result['ticks']
			continue

		octave = result['octave']
		volume = result['volume']
		tempo = result['tempo']
		instrument = result['instrument']

		# Note or rest
		if c in "cdefgab":
			duration = result['ticks']
			events.append(NoteEvent(
				start_128=tick,
				dur_128=duration,
				octave=octave,
				volume=volume,
				note=token,
				tempo=tempo,
				instrument=instrument,
				percussion=percussion
			))
			tick += duration
			continue

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


def pack_into_channels(notes: list[NoteEvent]) -> tuple[list[list[NoteEvent]], int]:
	"""Sort by start, assign each note to first free channel. Returns (channels, max_length)."""
	if not notes:
		return ([], 0)
	sorted_notes = sorted(notes, key=lambda n: (n.start_128, n.duplicate_key()))

	# group by (instrument, percussion) - percussion stays separate from melody
	group_channels = defaultdict(list[list[NoteEvent]])
	group_channel_end = defaultdict(list[int])


	for n in sorted_notes:
		key = (n.instrument, n.percussion)
		assigned = False
		for ch in range(len(group_channels[key])):
			if group_channel_end[key][ch] <= n.start_128:
				group_channels[key][ch].append(n)
				group_channel_end[key][ch] = n.start_128 + n.dur_128
				assigned = True
				break
		if not assigned:
			group_channels[key].append([n])
			group_channel_end[key].append(n.start_128 + n.dur_128)

	max_length = max(end for ends in group_channel_end.values() for end in ends)

	return ([channel for group in group_channels.values() for channel in group], max_length)


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


def events_to_4ml_channel(events: list[NoteEvent], target_length: Optional[int] = None) -> str:
	"""Serialize one channel's events to 4ML string (with rests for gaps)."""
	if not events:
		return f"r1"
	parts = []
	cur_tick = 0
	octave = DEFAULT_OCTAVE
	volume = DEFAULT_VOLUME
	# TODO: tempo is a global value, not separate per channel like we do here
	tempo = DEFAULT_TEMPO
	instrument = DEFAULT_INSTRUMENT
	percussion = False
	for n in sorted(events, key=lambda e: e.start_128):
		if n.start_128 > cur_tick:
			d = decompose_notes(n.start_128 - cur_tick)
			parts.append('r' + 'r'.join(d))
			cur_tick = n.start_128
		if n.octave != octave:
			parts.append(f"o{n.octave}")
			octave = n.octave
		if n.volume != volume:
			parts.append(f"v{n.volume}")
			volume = n.volume
		if n.tempo != tempo:
			parts.append(f"t{n.tempo}")
			tempo = n.tempo
		if n.instrument != instrument:
			parts.append(f"@{n.instrument}")
			instrument = n.instrument
		if n.percussion != percussion:
			parts.append('x' if n.percussion else 'x0')
			percussion = n.percussion
		parts.append(n.note)
		cur_tick = n.start_128 + n.dur_128

	# Pad to target length if specified
	if target_length is not None and cur_tick < target_length:
		d = decompose_notes(target_length - cur_tick)
		parts.append('r' + 'r'.join(d))

	return " ".join(parts)


def main() -> None:
	if len(sys.argv) < 2:
		log("Usage: 4ml-reduce-channels.py <file.4ml>")
		sys.exit(1)

	path = sys.argv[1]
	data = parse_4ml_file(path)

	channel_strings = data["channels"]
	pattern_data = data["patterns"]

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
	packed, max_length = pack_into_channels(all_notes)
	# Drop empty channels (we already only pack note-bearing channels)
	packed = [ch for ch in packed if not is_rest_only_or_empty(ch)]
	total_output_channels = len(packed)
	total_output_notes = sum(len(ch) for ch in packed)
	duplicates_removed = total_input_notes - len(all_notes)
	channels_dropped_empty = len(empty_or_rest_only)
	channels_saved = total_input_channels - total_output_channels

	# Output reduced 4ML to stdout
	for i, ch_events in enumerate(packed):
		print(f"C{i + 1} {events_to_4ml_channel(ch_events, max_length)}")
	if not packed:
		print("C1 r1")

	# Statistics to stderr
	log("4ML channel reduction statistics:")
	log(f"	Input channels:		   {total_input_channels}")
	log(f"	Output channels:	   {total_output_channels}")
	log(f"	Channels saved:		   {channels_saved}")
	log(f"	Input note events:	   {total_input_notes}")
	log(f"	Output note events:    {total_output_notes}")
	log(f"	Duplicate notes removed: {duplicates_removed}")
	log(f"	Empty/rest-only channels dropped: {channels_dropped_empty}")



if __name__ == "__main__":
	main()
