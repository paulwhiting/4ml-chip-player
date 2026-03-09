#!/usr/bin/env python3
"""
Compare two 4ML files after normalizing them. Outputs a unified diff of the
normalized content.

By default, normalization unrolls patterns into channels (fully expanded,
no P/p in output). Use --keep-patterns to compare with pattern refs and
definitions kept. Diff is colorized by default; use --concise for shorter output.
"""

import argparse
import re
import sys
from pathlib import Path

# ANSI colors for diff (empty if disabled)
RED = "\033[31m"
GREEN = "\033[32m"
CYAN = "\033[36m"
DIM = "\033[2m"
RESET = "\033[0m"


def _color_diff_line(line: str, use_color: bool) -> str:
    if not use_color or not line:
        return line
    if line.startswith("---") or line.startswith("+++"):
        return f"{CYAN}{line}{RESET}"
    if line.startswith("@@"):
        return f"{DIM}{line}{RESET}"
    if line.startswith("-"):
        return f"{RED}{line}{RESET}"
    if line.startswith("+"):
        return f"{GREEN}{line}{RESET}"
    return line


def _truncate(line: str, max_len: int) -> str:
    if max_len <= 0 or len(line) <= max_len:
        return line
    return line[: max_len - 3] + "..."

MAX_LOOP_EXPAND = 256

# Rest token: r optionally followed by +/-, digits, and optional dot (e.g. r, r1, r4., r16)
_REST_PAT = re.compile(r"(r[+#]?\d*\.?)([&^])(r[+#]?\d*\.?)")


def _normalize_rest_ties(s: str) -> str:
    """Remove & and ^ between consecutive rest tokens so r1&r1 and r1r1 compare equal."""
    while True:
        t = _REST_PAT.sub(r"\1\3", s)
        if t == s:
            return s
        s = t


def expand_loops(s: str) -> str:
    """Expand [N ... ] to N copies of the inner content."""
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
    """Replace pN with pattern body (recursive). pattern_data[i] is the content of Pi."""
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
                if 0 <= idx < len(pattern_data):
                    body = expand_loops(pattern_data[idx])
                    body = expand_patterns(body, pattern_data, depth + 1)
                    out.append(body)
                i = j
                continue
        out.append(channel_str[i])
        i += 1
    return "".join(out)


def _parse_stripped(content: str) -> tuple[list[str], list[str]]:
    """Strip comments/whitespace and return (channel_strings, pattern_strings)."""
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

    pattern_nums = sorted(set(int(m.group(1)) for m in re.finditer(r"P(\d+)", s)))
    max_p = max(pattern_nums) if pattern_nums else -1
    pattern_data = []
    for x in range(max_p + 1):
        parts = re.findall(rf"P{x}(?!\d)([^PC]*)", s)
        pattern_data.append("".join(parts))

    return channel_data, pattern_data, max_c


def normalize_4ml(content: str, unroll_patterns: bool = True) -> str:
    """
    Normalize 4ML for comparison:
    - Strip ; and /* */ comments, remove whitespace
    - If unroll_patterns (default): expand all pN and loops in channels; output
      only C0..Cn (one line per channel), no pattern definitions
    - If not unroll_patterns: emit C0..Cn then P1..Pm in canonical order
    """
    channel_data, pattern_data, max_c = _parse_stripped(content)

    lines = []
    if unroll_patterns:
        for x in range(max_c + 1):
            if channel_data[x]:
                expanded = expand_patterns(channel_data[x], pattern_data)
                expanded = expand_loops(expanded)
                expanded = _normalize_rest_ties(expanded)
                lines.append(f"C{x}{expanded}")
    else:
        for x in range(max_c + 1):
            if channel_data[x]:
                lines.append(f"C{x}{_normalize_rest_ties(channel_data[x])}")
        for x in range(len(pattern_data)):
            if pattern_data[x]:
                lines.append(f"P{x}{_normalize_rest_ties(pattern_data[x])}")
    return "\n".join(lines) + ("\n" if lines else "")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare two 4ML files after normalizing. By default, patterns are unrolled into channels.",
    )
    parser.add_argument(
        "--keep-patterns",
        action="store_true",
        help="Do not unroll patterns; compare with P/p refs and definitions kept.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colorized diff output.",
    )
    parser.add_argument(
        "-c", "--concise",
        action="store_true",
        help="Shorter diff: no context lines, truncate long lines.",
    )
    parser.add_argument(
        "--max-line",
        type=int,
        default=120,
        metavar="N",
        help="When using --concise, truncate diff lines to N chars (0 = no truncation). Default 120.",
    )
    parser.add_argument(
        "--stat",
        action="store_true",
        help="Only list which lines differ (e.g. C1, C3, P2); no full diff.",
    )
    parser.add_argument("file1", type=Path, help="First 4ML file")
    parser.add_argument("file2", type=Path, help="Second 4ML file")
    args = parser.parse_args()

    path_a = args.file1
    path_b = args.file2

    if not path_a.is_file():
        print(f"Error: not a file: {path_a}", file=sys.stderr)
        sys.exit(1)
    if not path_b.is_file():
        print(f"Error: not a file: {path_b}", file=sys.stderr)
        sys.exit(1)

    text_a = path_a.read_text()
    text_b = path_b.read_text()

    unroll = not args.keep_patterns
    norm_a = normalize_4ml(text_a, unroll_patterns=unroll)
    norm_b = normalize_4ml(text_b, unroll_patterns=unroll)

    lines_a = norm_a.splitlines()
    lines_b = norm_b.splitlines()

    if lines_a == lines_b:
        print("No difference (normalized content is identical).")
        sys.exit(0)

    def _line_label(line: str, i: int) -> str:
        m = re.match(r"^([CP]\d+)", line)
        return m.group(1) if m else f"L{i + 1}"

    if args.stat:
        differing = []
        max_len = max(len(lines_a), len(lines_b))
        for i in range(max_len):
            la = lines_a[i] if i < len(lines_a) else None
            lb = lines_b[i] if i < len(lines_b) else None
            if la != lb:
                if la is not None and lb is not None:
                    differing.append(_line_label(la, i))
                elif la is not None:
                    differing.append(f"{_line_label(la, i)} (only in {path_a.name})")
                else:
                    differing.append(f"{_line_label(lb, i)} (only in {path_b.name})")
        print(f"{len(differing)} line(s) differ: {', '.join(differing)}")
        sys.exit(1)

    use_color = not args.no_color and sys.stdout.isatty()
    context_lines = 0 if args.concise else 3
    max_line = args.max_line if args.concise else 0

    try:
        import difflib
    except ImportError:
        for i, (la, lb) in enumerate(zip(lines_a, lines_b)):
            if la != lb:
                print(f"Line {i + 1}:")
                print(f"  - {la}")
                print(f"  + {lb}")
        if len(lines_a) != len(lines_b):
            print(f"Line count: {len(lines_a)} vs {len(lines_b)}")
        sys.exit(1)

    label_a = str(path_a)
    label_b = str(path_b)
    diff = difflib.unified_diff(
        lines_a,
        lines_b,
        fromfile=label_a,
        tofile=label_b,
        lineterm="",
        n=context_lines,
    )
    for line in diff:
        line = _truncate(line, max_line)
        print(_color_diff_line(line, use_color))
    sys.exit(1)


if __name__ == "__main__":
    main()
