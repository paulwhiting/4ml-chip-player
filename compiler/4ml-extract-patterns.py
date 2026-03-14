#!/usr/bin/env python3
"""
4ML Pattern Extractor — Detect recurring sequences of notes/rests/commands in a
4ML file and replace them with numbered patterns (P1, P2, … / p1, p2, …) to
minimize total 4ML size. Repeats are detected across all channels.

See docs/4ml.md for 4ML syntax.
"""

import argparse
import re
import sys
import time
from collections import defaultdict
from typing import Callable
from compiler import process_mmml_string

# 4ML supports pattern numbers 0-255 (256 patterns total)
MAX_PATTERNS = 256
# Pattern body must start with one of these (notes a-g, rest r, octave o, volume v)
VALID_PATTERN_FIRST_CHARS = "abcdefgrov"

def _format_eta(seconds: float) -> str:
	if seconds < 60:
		return f"{seconds:.0f}s"
	if seconds < 3600:
		return f"{seconds / 60:.1f} min"
	return f"{seconds / 3600:.1f} hr"

# Progress reporting: print to stderr every this many scan iterations or sequence evals
PROGRESS_SCAN_INTERVAL = 200_000
PROGRESS_EVAL_INTERVAL = 100_000
# Sample size for runtime estimate (iterations)
ESTIMATE_SAMPLE = 50_000
# Width for in-place progress line (pad so previous text is overwritten)
PROGRESS_LINE_WIDTH = 100

# --- Parsing (aligned with 4ml-reduce-channels.py) ---

def parse_and_strip(content: str) -> tuple[list[str], list[str]]:
	"""Remove comments/whitespace; return (channel_strings, pattern_strings)."""
	s = content
	s = re.sub(r";.*?(?=\n|$)", "\n", s)
	s = re.sub(r"/\*[\s\S]*?\*/", "", s)
	s = re.sub(r"\s+", "", s)

	channel_nums = sorted(set(int(m.group(1)) for m in re.finditer(r"C(\d+)", s)))
	max_c = max(channel_nums) if channel_nums else -1
	channel_data = []
	for x in range(max_c + 1):
		parts = re.findall(rf"C{x}(?!\d)([^CP]*)", s)
		channel_data.append("".join(parts))
	while "" in channel_data:
		channel_data.remove("")

	pattern_nums = sorted(set(int(m.group(1)) for m in re.finditer(r"P(\d+)", s)))
	max_p = max(pattern_nums) if pattern_nums else -1
	pattern_data = []
	for x in range(max_p + 1):
		parts = re.findall(rf"P{x}(?!\d)([^PC]*)", s)
		pattern_data.append("".join(parts))
	while "" in pattern_data:
		pattern_data.remove("")

	return channel_data, pattern_data


MAX_LOOP_EXPAND = 256


def expand_loops(s: str) -> str:
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


# --- Tokenizer: one 4ML element per token (for repeat detection) ---

def tokenize(s: str) -> list[str]:
	"""Split 4ML string into list of tokens (notes, rests, o, v, t, @, K, s, F, &, ^, <, >).
	Never splits numbers: each numeric suffix (duration, octave, volume, etc.) is consumed in full.
	"""
	tokens = []
	i = 0
	while i < len(s):
		c = s[i]

		# Note or rest: r / c,d,e,f,g,a,b (optional +/#) then optional duration (1-3 digits, then optional .)
		# Tie (&/^) plus following note are merged so we never split a tied group (e.g. g1&g2).
		# Never split numbers: consume full duration (max 3 digits for 4ML 1-128) per note.
		if c == "r" or c in "cdefgab":
			tok = c
			i += 1
			if i < len(s) and s[i] in "+#":
				tok += s[i]
				i += 1
			nd = 0
			while i < len(s) and s[i].isdigit() and nd < 3:
				tok += s[i]
				i += 1
				nd += 1
			if i < len(s) and s[i] == ".":
				tok += s[i]
				i += 1
			# Merge tie + next note into same token so g1&g2 is one token (cannot split)
			while i < len(s) and s[i] in "&^":
				tok += s[i]
				i += 1
				if i >= len(s) or s[i] not in "rcdefgab":
					break
				tie_note = s[i]
				tok += tie_note
				i += 1
				if i < len(s) and s[i] in "+#":
					tok += s[i]
					i += 1
				nd = 0
				while i < len(s) and s[i].isdigit() and nd < 3:
					tok += s[i]
					i += 1
					nd += 1
				if i < len(s) and s[i] == ".":
					tok += s[i]
					i += 1
			tokens.append(tok)
			continue

		if c == "o":
			tok = "o"
			i += 1
			while i < len(s) and s[i].isdigit():
				tok += s[i]
				i += 1
			tokens.append(tok)
			continue

		if c in "<>":
			tokens.append(c)
			i += 1
			continue

		if c in "v@t":
			tok = c
			i += 1
			while i < len(s) and s[i].isdigit():
				tok += s[i]
				i += 1
			tokens.append(tok)
			continue

		if c in "KsF":
			tok = c
			i += 1
			if i < len(s) and s[i] == "-":
				tok += s[i]
				i += 1
			while i < len(s) and s[i].isdigit():
				tok += s[i]
				i += 1
			tokens.append(tok)
			continue

		if c == "s":
			tok = "s"
			i += 1
			if i < len(s) and s[i] == "-":
				tok += s[i]
				i += 1
			while i < len(s) and s[i].isdigit():
				tok += s[i]
				i += 1
			tokens.append(tok)
			continue

		# Standalone &/^ (e.g. after v8): consume with following note so we get "&g2" as one token
		if c in "&^":
			tok = c
			i += 1
			if i < len(s) and s[i] in "rcdefgab":
				note_char = s[i]
				tok += note_char
				i += 1
				if i < len(s) and s[i] in "+#":
					tok += s[i]
					i += 1
				nd = 0
				while i < len(s) and s[i].isdigit() and nd < 3:
					tok += s[i]
					i += 1
					nd += 1
				if i < len(s) and s[i] == ".":
					tok += s[i]
					i += 1
			tokens.append(tok)
			continue

		# Loop: [N ... ] is one indivisible token (pattern cannot split a loop)
		if c == "[":
			start_loop = i
			i += 1
			while i < len(s) and s[i].isdigit():
				i += 1
			depth = 1
			while i < len(s) and depth > 0:
				if s[i] == "[":
					depth += 1
				elif s[i] == "]":
					depth -= 1
				i += 1
			tokens.append(s[start_loop:i])
			continue
		if c == "]":
			i += 1
			continue

		if c == "p":
			tok = "p"
			i += 1
			while i < len(s) and s[i].isdigit():
				tok += s[i]
				i += 1
			tokens.append(tok)
			continue

		if c == "i":
			tok = "i"
			i += 1
			while i < len(s) and s[i].isdigit():
				tok += s[i]
				i += 1
			tokens.append(tok)
			continue

		i += 1

	return tokens


def tokens_to_string(tokens: list[str]) -> str:
	"""Serialize token list back to 4ML (no spaces; caller can add for readability)."""
	return " ".join(tokens)


# --- Repeat detection and pattern extraction ---

def find_non_overlapping_occurrences(
	seq: tuple[str, ...],
	channel_tokens: list[list[str]],
) -> list[tuple[int, int]]:
	"""Return list of (channel_idx, start_index) for non-overlapping occurrences of seq."""
	L = len(seq)
	occurrences: list[tuple[int, int]] = []
	# Track end of last used occurrence per channel
	last_end: dict[int, int] = defaultdict(lambda: -1)

	for ch_idx, toks in enumerate(channel_tokens):
		i = 0
		while i <= len(toks) - L:
			if tuple(toks[i : i + L]) == seq:
				if i >= last_end[ch_idx]:
					occurrences.append((ch_idx, i))
					last_end[ch_idx] = i + L
				i += L
			else:
				i += 1
	return occurrences


def compute_savings(
	seq: tuple[str, ...],
	occurrences: list[tuple[int, int]],
	next_pattern_num: int,
) -> int:

	"""Savings in compiled bytes if we replace these occurrences with one pattern + refs."""
	K = len(occurrences)
	if K < 2:
		return 0
	seq_str = tokens_to_string(list(seq))
	compiled_bytes = process_mmml_string(seq_str, False)
	orig = K * len(compiled_bytes)
	pattern_ref = 2  # 2 bytes per pattern call
	pattern_def = 2 + len(compiled_bytes)  # 2 bytes for the necessary header entry
	new_total = pattern_def + K * pattern_ref
	return orig - new_total


def total_scan_work(channel_tokens: list[list[str]], min_seq_len: int = 2, max_seq_len: int = 80) -> int:
	"""Total number of (ch, L, start) iterations in the scan phase (for progress/estimate)."""
	work = 0
	for toks in channel_tokens:
		n = len(toks)
		L_max = min(max_seq_len, n)
		if L_max < min_seq_len:
			continue
		# For each L in [min_seq_len, L_max]: (n - L + 1) starts
		work += sum(n - L + 1 for L in range(min_seq_len, L_max + 1))
	return work


def find_best_repeat(
	channel_tokens: list[list[str]],
	next_pattern_num: int,
	min_seq_len: int = 2,
	max_seq_len: int = 80,
	progress_fn: Callable[[str, int, int], None] | None = None,
) -> tuple[tuple[str, ...], list[tuple[int, int]], int] | None:
	"""Find the repeated token sequence that gives the most savings. Returns (seq, occurrences, savings) or None.
	progress_fn(phase, current, total) is called with phase in ('scan', 'eval'), current/total for progress.
	"""
	seq_to_positions: dict[tuple[str, ...], list[tuple[int, int]]] = defaultdict(list)
	total_work = total_scan_work(channel_tokens, min_seq_len, max_seq_len)
	done = 0

	for ch_idx, toks in enumerate(channel_tokens):
		n = len(toks)
		L_max = min(max_seq_len, n)
		for L in range(min_seq_len, L_max + 1):
			for start in range(n - L + 1):
				# Pattern must start with a,b,c,d,e,f,g,r,o,v (not &, ^, t, p, etc.)
				first_tok = toks[start]
				if not first_tok or first_tok[0] not in VALID_PATTERN_FIRST_CHARS:
					done += 1
					continue
				if first_tok.startswith("&") or first_tok.startswith("^"):
					done += 1
					continue
				seq = tuple(toks[start : start + L])
				# Pattern cannot contain another pattern (no pN in body)
				if any(len(t) > 1 and t[0] == "p" and t[1:].isdigit() for t in seq):
					done += 1
					continue
				seq_to_positions[seq].append((ch_idx, start))
				done += 1
				if progress_fn and done % PROGRESS_SCAN_INTERVAL == 0:
					progress_fn("scan", done, total_work)

	num_seqs = len(seq_to_positions)
	best_savings = 0
	best_seq: tuple[str, ...] | None = None
	best_occurrences: list[tuple[int, int]] = []
	evaluated = 0

	for seq, positions in seq_to_positions.items():
		if progress_fn and evaluated > 0 and evaluated % PROGRESS_EVAL_INTERVAL == 0:
			progress_fn("eval", evaluated, num_seqs)
		evaluated += 1
		# Pattern must start with a note (a-g), rest (r), octave (o), or volume (v)
		if not seq[0] or seq[0][0] not in VALID_PATTERN_FIRST_CHARS:
			continue
		# 4ML patterns cannot begin with & or ^ (tie extends previous note)
		if seq[0].startswith("&") or seq[0].startswith("^"):
			continue
		# Pattern cannot include another pattern (no pN inside a pattern body)
		if any(len(t) > 1 and t[0] == "p" and t[1:].isdigit() for t in seq):
			continue
		if len(positions) < 2:
			continue
		positions = sorted(positions, key=lambda p: (p[0], p[1]))
		chosen: list[tuple[int, int]] = []
		last_end: dict[int, int] = defaultdict(lambda: -1)
		L_seq = len(seq)
		for ch_idx, start in positions:
			end = start + L_seq
			if start >= last_end[ch_idx]:
				# Cannot have pN followed by &/^ token (invalid: tie would have no prior note in pattern)
				toks = channel_tokens[ch_idx]
				if end < len(toks) and (toks[end].startswith("&") or toks[end].startswith("^")):
					continue
				chosen.append((ch_idx, start))
				last_end[ch_idx] = end
		if len(chosen) < 2:
			continue
		savings = compute_savings(seq, chosen, next_pattern_num)
		if savings > best_savings:
			best_savings = savings
			best_seq = seq
			best_occurrences = chosen

	if progress_fn:
		progress_fn("eval", num_seqs, num_seqs)
	if best_seq is None or best_savings <= 0:
		return None
	return (best_seq, best_occurrences, best_savings)


def replace_occurrences_with_pattern(
	channel_tokens: list[list[str]],
	seq: tuple[str, ...],
	occurrences: list[tuple[int, int]],
	pattern_num: int,
) -> None:
	"""Mutate channel_tokens: replace each occurrence with a single token 'pN'."""
	ref_tok = f"p{pattern_num}"
	# Sort reverse by (ch, start) so we don't shift indices
	for ch_idx, start in sorted(occurrences, key=lambda p: (p[0], -p[1])):
		toks = channel_tokens[ch_idx]
		L = len(seq)
		toks[start : start + L] = [ref_tok]


def format_channel_line(ch_idx: int, token_list: list[str]) -> str:
	"""Format one channel as 'Ck token token token...'."""
	raw = tokens_to_string(token_list)
	return f"C{ch_idx + 1} {raw}"


def main() -> None:
	parser = argparse.ArgumentParser(
		description="Detect recurring sequences in 4ML and extract them as numbered patterns (P1, p1, ...).",
	)
	parser.add_argument(
		"--max-rounds",
		type=int,
		default=None,
		metavar="N",
		help=f"Stop after at most N extraction rounds (default: no limit). Total patterns cannot exceed {MAX_PATTERNS} (0-255).",
	)
	parser.add_argument(
		"--progress",
		choices=("tty", "line"),
		default="tty",
		help="Progress style: 'tty' = update same line when stderr is a TTY; 'line' = one line per update (use if in-place updates don't work).",
	)
	parser.add_argument("file", metavar="file.4ml", help="Input 4ML file")
	args = parser.parse_args()
	path = args.file
	max_rounds = args.max_rounds
	progress_style = args.progress

	print(f"Parsing {path}...", file=sys.stderr)
	try:
		with open(path, "r") as f:
			content = f.read()
	except FileNotFoundError:
		print(f"File not found: {path}", file=sys.stderr)
		sys.exit(1)

	t0 = time.perf_counter()
	channel_strings, pattern_data = parse_and_strip(content)
	print(f"  Found {len(channel_strings)} channels, {len(pattern_data)} patterns.", file=sys.stderr)

	print("Expanding and tokenizing channels...", file=sys.stderr)
	channel_tokens: list[list[str]] = []
	for ch_idx, ch_str in enumerate(channel_strings):
		expanded = expand_patterns(ch_str, pattern_data)
		# Do not expand loops here: loops stay as one token so we never split a loop across a pattern
		toks = tokenize(expanded)
		channel_tokens.append(toks)
		print(f"  Channel {ch_idx + 1}/{len(channel_strings)}: {len(toks)} tokens", file=sys.stderr)
	total_tokens = sum(len(t) for t in channel_tokens)
	total_chars_before = sum(len(tokens_to_string(t)) for t in channel_tokens)
	print(f"  Total: {total_tokens} tokens ({total_chars_before} chars).", file=sys.stderr)

	num_existing = len(pattern_data)
	next_pattern_num = num_existing + 1
	max_new_patterns = MAX_PATTERNS - num_existing
	if max_rounds is not None and max_rounds > max_new_patterns:
		max_rounds = max_new_patterns
		print(f"  (--max-rounds capped to {max_rounds} so total patterns ≤ {MAX_PATTERNS}.)", file=sys.stderr)
	if max_rounds is not None:
		print(f"  Max extraction rounds: {max_rounds}.", file=sys.stderr)
	total_work = total_scan_work(channel_tokens)
	# Rough runtime estimate: sample first ESTIMATE_SAMPLE iterations
	estimate_sec_per_iter = None
	if total_work > ESTIMATE_SAMPLE:
		print("  Estimating runtime (sampling)...", file=sys.stderr)
		sample_start = time.perf_counter()
		_ = total_scan_work(channel_tokens)  # no-op for count
		seq_to_positions: dict = {}
		done = 0
		for ch_idx, toks in enumerate(channel_tokens):
			n = len(toks)
			L_max = min(80, n)
			for L in range(2, L_max + 1):
				for start in range(n - L + 1):
					seq = tuple(toks[start : start + L])
					seq_to_positions[seq] = seq_to_positions.get(seq, 0) + 1
					done += 1
					if done >= ESTIMATE_SAMPLE:
						break
				if done >= ESTIMATE_SAMPLE:
					break
			if done >= ESTIMATE_SAMPLE:
				break
		sample_elapsed = time.perf_counter() - sample_start
		estimate_sec_per_iter = sample_elapsed / done
		est_total_sec = estimate_sec_per_iter * total_work
		print(f"  Approx. scan work: {total_work} sequence positions.", file=sys.stderr)
		print(f"  Estimated time for this round: {_format_eta(est_total_sec)}.", file=sys.stderr)

	new_patterns: list[tuple[int, list[str]]] = []
	total_savings = 0
	round_num = 0
	last_progress = [0.0]  # mutable for closure

	use_in_place = progress_style == "tty" and (hasattr(sys.stderr, "isatty") and sys.stderr.isatty())

	def progress_fn(phase: str, current: int, total: int) -> None:
		now = time.perf_counter()
		if now - last_progress[0] < 0.5 and current != total:
			return
		last_progress[0] = now
		pct = 100 * current / total if total else 0
		msg = f"	[{phase}] {current:,} / {total:,} ({pct:.1f}%)"
		if phase == "scan" and estimate_sec_per_iter and total:
			remaining = (total - current) * estimate_sec_per_iter
			msg += f"  ETA {_format_eta(remaining)}"
		padded = msg.ljust(PROGRESS_LINE_WIDTH)
		if current == total:
			# End of phase: show final state then newline so next output is on its own line
			if use_in_place:
				sys.stderr.write("\r" + padded + "\n")
				sys.stderr.flush()
			else:
				print(padded.rstrip(), file=sys.stderr, flush=True)
		elif use_in_place:
			# In-place update: \r at start moves cursor to line start, then overwrite
			sys.stderr.write("\r" + padded)
			sys.stderr.flush()
		else:
			# Line mode or not a TTY: one progress line per update
			print(padded.rstrip(), file=sys.stderr, flush=True)

	print("Finding repeated sequences (may take a while)...", file=sys.stderr)
	while True:
		round_num += 1
		if max_rounds is not None and round_num > max_rounds:
			print(f"  Stopping after {max_rounds} rounds (--max-rounds).", file=sys.stderr)
			break
		if next_pattern_num > MAX_PATTERNS:
			print(f"  Stopping: pattern limit reached ({MAX_PATTERNS} patterns).", file=sys.stderr)
			break
		print(f"  Round {round_num}: scanning...", file=sys.stderr)
		cand = find_best_repeat(channel_tokens, next_pattern_num, progress_fn=progress_fn)
		if cand is None:
			break
		seq, occurrences, savings = cand
		total_savings += savings
		replace_occurrences_with_pattern(channel_tokens, seq, occurrences, next_pattern_num)
		new_patterns.append((next_pattern_num, list(seq)))
		next_pattern_num += 1
		print(f"  Round {round_num}: extracted pattern P{next_pattern_num - 1} ({savings} chars saved).", file=sys.stderr)
		# Re-estimate for next round (fewer tokens)
		total_work = total_scan_work(channel_tokens)
		if total_work > ESTIMATE_SAMPLE and estimate_sec_per_iter:
			print(f"	Next round ~{_format_eta(estimate_sec_per_iter * total_work)}.", file=sys.stderr)

	total_chars_after = sum(len(tokens_to_string(t)) for t in channel_tokens)
	elapsed = time.perf_counter() - t0
	print(f"Done in {_format_eta(elapsed)}.", file=sys.stderr)

	# Statistics to stderr
	print("4ML pattern extraction statistics:", file=sys.stderr)
	print(f"  Channels processed:	  {len(channel_tokens)}", file=sys.stderr)
	print(f"  New patterns created:   {len(new_patterns)}", file=sys.stderr)
	print(f"  Estimated char savings: {total_savings}", file=sys.stderr)
	print(f"  Channel content length (before): {total_chars_before}", file=sys.stderr)
	print(f"  Channel content length (after):  {total_chars_after}", file=sys.stderr)

	# Output 4ML: channels (with new pN refs), then original P1..Pm, then new patterns P(m+1)...
	# Emit channel lines (one C per original channel); compress repeated rests to [N rX]
	for ch_idx, toks in enumerate(channel_tokens):
		print(format_channel_line(ch_idx, toks))

	# Emit original pattern definitions first (P1 .. Pn) so any p1..pn in output still refer to them
	for idx, body in enumerate(pattern_data):
		print(f"P{idx + 1} {body}")

	# Emit new pattern definitions (pattern numbers after existing); compress repeated rests
	for pattern_num, toks in new_patterns:
		body = tokens_to_string(toks)
		print(f"P{pattern_num} {body}")


if __name__ == "__main__":
	main()
