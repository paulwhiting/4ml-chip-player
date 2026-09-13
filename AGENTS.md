# AGENTS.md - Guidelines for AI Coding Agents

This file provides guidelines for AI coding agents operating in this repository.

## 1. Build/Lint/Test Commands

### Python Compiler
```bash
# Compile 4ML to C header (desktop)
python3 compiler/compiler.py input.4ml

# Compile 4ML for AVR microcontroller
python3 compiler/compiler.py --avr input.4ml

# Reduce channels (remove duplicate notes)
python3 compiler/4ml-reduce-channels.py input.4ml

# Extract patterns for compression
python3 compiler/4ml-extract-patterns.py input.4ml
```

### AVR Build (requires avr-gcc toolchain)
```bash
# Build for ATmega328P
make ninjagaiden.atmega.bin

# Build for ATtiny85
make ninjagaiden.attiny.bin

# Flash to device (requires avrdude)
make ninjagaiden
```

### Flipper Zero Build
```bash
# Requires Flipper SDK (fbt) - set FLIPPER_SDK path if non-default
make flipper/4ml.fap

# Or specify SDK location
FLIPPER_SDK=/path/to/flipperzero-firmware make flipper/4ml.fap
```

### Testing
```bash
# NES parser tests (JavaScript)
cd nes && npm test

# No Python test framework currently configured
```

### Running Single Test (NES)
```bash
cd nes && npm test -- --grep "test name"
```

## 2. Code Style Guidelines

### Python (compiler/)

**Imports:**
- Standard library first (`sys`, `re`, `struct`)
- Third-party (none currently)
- Local modules last (`from compiler import ...`, `from utils import ...`)

**Naming Conventions:**
- Functions: `snake_case` (e.g., `process_mmml_string`, `tokenize`)
- Classes: `PascalCase` (e.g., `NoteEvent`, `bcolors`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `DEFAULT_OCTAVE`, `DURATION_128THS`)
- Variables: `snake_case`

**Types:**
- Use `typing` module for type hints (e.g., `Optional[int]`, `list[NoteEvent]`)
- Use `dataclass` for structured data objects
- Use `defaultdict` from collections for dictionaries with default values

**Error Handling:**
- Use `throw_error(error_number, info1, info2)` for compiler errors
- Use `throw_warning(warning_number, info)` for warnings
- Print errors to stderr with color codes (see `bcolors` class)

**Formatting:**
- Indent with 4 spaces
- Max line length: ~100 characters (flexible)
- Blank lines between function definitions
- Comment blocks for file headers (see compiler.py lines 1-31 as example)

**Code Organization:**
- Keep related functions together
- Use helper functions in `utils.py` to avoid duplication
- `tokenize` and `tokens_to_string` in utils.py are used by multiple scripts

### C (bonus/player-avr/)

**Types:**
- Use AVR standard types: `uint8_t`, `uint16_t`, `int8_t`, `int16_t`
- Use `PROGMEM` for program memory storage
- Use `pgm_read_byte()` for reading from PROGMEM

**Naming:**
- Functions: `snake_case` (e.g., `play_song`, `expand_patterns`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `CMD_FN`, `MAX_VOICES`)
- Macros: `UPPER_SNAKE_CASE`

**Code Style:**
- Indent with tabs ( AVR code uses tabs)
- Comment blocks for function headers
- Use `goto` for specific patterns (see note in code)

### General Guidelines

**4ML Parsing:**
- The tokenizer in `utils.py` must handle negative octaves (`o-1`, `o0`)
- Bytecode length calculations should use compiled bytes, not string length
- Tempo is global - don't output per-channel

**AVR Specific:**
- Note table values scaled to support octave range -1 to 14
- Remember to account for data pointer advancement after command bytes
- Percussion uses sample playback, not pitch synthesis

**Git Workflow:**
- Make focused commits with descriptive messages
- Test changes with actual 4ML files before committing
- Check Makefile for build targets

## 3. Key Files

| File | Purpose |
|------|---------|
| `compiler/compiler.py` | Main 4ML to bytecode compiler |
| `compiler/utils.py` | Shared utilities (tokenize, process_mmml_string) |
| `compiler/4ml-reduce-channels.py` | Remove duplicates, pack notes |
| `compiler/4ml-extract-patterns.py` | Extract repeating patterns |
| `bonus/player-avr/4ml-avr-player.c` | AVR microcontroller player |
| `nes/parser.js` | Web-based 4ML parser |

## 4. Common Tasks

**Adding a new 4ML command:**
1. Add to `command_lookup` in both `compiler.py` and `utils.py`
2. Add handling in `process_mmml_string` in both files
3. Add decoder in AVR player if applicable

**Fixing AVR player:**
- Check data pointer advancement after commands
- Verify note table matches encoder expectations
- Test with simple 4ML files

**Testing changes:**
```bash
# Compile and verify output
python3 compiler/compiler.py test.4ml
python3 compiler/compiler.py --avr test.4ml > test.4ml.avr.h

# Reduce and extract
python3 compiler/4ml-reduce-channels.py test.4ml > reduced.4ml
python3 compiler/4ml-extract-patterns.py reduced.4ml > minimized.4ml
```
