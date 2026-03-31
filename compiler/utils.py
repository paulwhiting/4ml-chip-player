import sys
import re
from typing import Optional

from exceptions import (
    CompilerError, FileError, LimitError, SyntaxError, CompilerValueError,
    CompilerWarning, handle_error, handle_warning
)

def log(msg: str) -> None:
	print(msg, file=sys.stderr)


######################################
# convert data from string to binary #
######################################

def process_mmml_string(input_string, output_end_channel_byte = True):
	index = 0
	output_bytecode = []
	bytecode_length = 0

	# 4ml default values
	previous_duration = '8'
	previous_octave   = '3'

	# lookup tables so we can keep all the definitions in one place
	command_lookup = {
		'r': 0x00, 'c': 0x01, 'c+':0x02, 'd': 0x03, 'd+':0x04, 'e': 0x05, 'e+':0x06, 'f': 0x06,
		'f+':0x07, 'g': 0x08, 'g+': 0x09, 'a': 0x0A, 'a+':0x0B, 'b': 0x0C, 'b+':0x01, 'o': 0x0D,
		'v': 0x0E, 'p': 0xF2, 't': 0xF3, '@': 0xF5, 'i': 0xF5, '[': 0xF0, ']': 0xF1, '&': 0xF6,
		'^': 0xF6, 'K': 0xF4, 's': 0xF7, 'F': 0xFE
	}

	duration_lookup = {
		'1':   0x00, '2':  0x01, '4':  0x02, '8':  0x03, '16':	0x04, '32':  0x05, '64':  0x06,
		'128': 0x07, '2.': 0x08, '4.': 0x09, '8.': 0x0A, '16.': 0x0B, '32.': 0x0C, '64.': 0x0D
	}

	# duration (as written) to length in 128th-note units
	duration_to_128th = {
		'1':   128,
		'2':	64,
		'4':	32,
		'8':	16,
		'16':	 8,
		'32':	 4,
		'64':	 2,
		'128':	 1,
		'2.':	96,
		'4.':	48,
		'8.':	24,
		'16.':	12,
		'32.':	 6,
		'64.':	 3,
	}

	# inverse map: 128th-note length -> duration nibble
	duration_128th_to_nibble = {}
	for dstr, nib in duration_lookup.items():
		duration_128th_to_nibble[duration_to_128th[dstr]] = nib

	matching_loop = 0

	while index < len(input_string):
		current_char  = input_string[index]

		# process standard notes (r, c..b, with optional sharp)
		if current_char in ('r','c','c+','d','d+','e','e+','f','f+','g','g+','a','a+','b','b+',):
			note_duration	= ''
			note_nibble		= 0
			duration_nibble = 0

			index += 1

			# check for sharpening
			if index < len(input_string) and input_string[index] in ('+', '#'):
				current_char = current_char + '+'
				index += 1

			# check for the next characters after the letter
			while index < len(input_string) and input_string[index].isdigit() and len(note_duration) < 3:
				note_duration += input_string[index]
				index += 1

			# check for dots after duration
			if index < len(input_string) and input_string[index] == '.':
				note_duration = note_duration + '.'
				index += 1

			if note_duration:
				previous_duration = note_duration
			else:
				note_duration = previous_duration

			# fetch the correct command bytes
			note_nibble		= command_lookup  [current_char]
			duration_nibble = duration_lookup [note_duration]

			# check if in bounds
			if duration_nibble > 16 or duration_nibble < 0:
				raise CompilerValueError(f"Note '{current_char}{note_duration}' is an invalid duration.")

			# Collapse tied/successive same-note durations into minimal byte sequence
			# base duration in 128th-note units
			if note_duration not in duration_to_128th:
				raise CompilerValueError(f"Note '{current_char}{note_duration}' is an invalid duration.")
			total_128 = duration_to_128th[note_duration]
			base_letter = current_char[0]

			# check for next token: is there another note immediately after?
			# (if so, we can use the "play two notes at once" optimization)
			saved_index = index
			original_note = current_char[0]
			next_is_note = False

			while saved_index < len(input_string) and input_string[saved_index] == ' ':
				saved_index += 1

			if saved_index < len(input_string):
				next_char = input_string[saved_index]
				if next_char in "cdefgab":
					next_is_note = True

			# yep, there's another note right after so let's squash them into one bytecode
			if next_is_note:
				# skip whitespace
				while index < len(input_string) and input_string[index] == ' ':
					index += 1

				# there's a note here so get it
				if index < len(input_string):
					current_char2 = input_string[index]

					# check for sharpening
					if current_char2 in ('+', '#'):
						current_char2 = current_char2 + '+'
						index += 1

					# fetch the second note's nibble
					second_note_nibble = command_lookup[current_char2]

					# skip to the end of the second note
					index += 1

					while index < len(input_string) and input_string[index].isdigit():
						index += 1

					# we've now processed the second note, so append the single-byte two-note sequence
					output_bytecode.append((note_nibble << 4) | second_note_nibble)

			else:
				# there wasn't a second note, so output the single note with duration
				output_bytecode.append((note_nibble << 4) | duration_nibble)

			# count ticks
			tick_count += total_128

			continue

		# process single byte commands with values
		elif current_char in ('o', 'v'):
			function_value	= ''
			command_nibble	= 0
			function_nibble = 0

			index += 1

			# check for negative sign (needed for octave)
			is_negative = False
			if current_char == 'o' and index < len(input_string) and input_string[index] == '-':
				is_negative = True
				function_value += '-'
				index += 1

			# check for the next characters after the letter
			while index < len(input_string) and input_string[index].isdigit() and len(function_value) < 4:
				function_value += input_string[index]
				index += 1

			# check if it's a valid negative value
			if is_negative and not function_value:
				raise CompilerValueError(f"Command '{current_char}' must have a value.")

			# you've got to have a value with it!
			if not function_value or function_value == '-':
				raise CompilerValueError(f"Command '{current_char}' must have a value.")

			# if it's an octave, store the value for the '<' and '>' commands
			if current_char == 'o':
				previous_octave = function_value

			# get the right command byte
			command_nibble = command_lookup[current_char]

			# convert string to int, check if in bounds
			function_nibble = int(function_value)
			# octave: -1 to 14, volume: 1 to 16
			if current_char == 'o':
				if function_nibble > 14 or function_nibble < -1:
					raise CompilerValueError(f"Command '{current_char}' is {function_nibble}, must be 1 - 16.")
			elif current_char == 'v':
				if function_nibble > 16 or function_nibble < 1:
					raise CompilerValueError(f"Command '{current_char}' is {function_nibble}, must be 1 - 16.")

			# squash the command and value to a single byte and output
			# octave uses +1 encoding (new), volume uses -1 encoding (old)
			if current_char == 'o':
				output_byte = (command_nibble << 4) | (function_nibble + 1)
			else:
				output_byte = (command_nibble << 4) | (function_nibble - 1)
			output_bytecode.append(output_byte)

		# process two-byte commands with values
		elif current_char in ('p', 't', '@', 'i', '[', 'K', 's','F'):
			function_value = ''
			command_byte = 0
			function_byte = 0

			index += 1

			# check for negative sign
			is_negative = False
			if index < len(input_string) and input_string[index] == '-':
				is_negative = True
				index += 1

			# check for the next characters after the letter
			while index < len(input_string) and input_string[index].isdigit() and len(function_value) < 3:
				function_value += input_string[index]
				index += 1

			# check if it's a valid negative value
			if is_negative and not function_value:
				raise CompilerValueError(f"Command '{current_char}' must have a value.")

			# you've got to have a value with it!
			if not function_value:
				raise CompilerValueError(f"Command '{current_char}' must have a value.")

			# convert to byte code
			command_byte = command_lookup[current_char]
			function_byte = int(function_value)

			if current_char == 't':
				pass

			# squash the two bytes into a three-byte command and output
			output_bytecode.append(command_byte)
			output_bytecode.append(function_byte - 1)

			if function_byte -1 < 0:
				print(f"LOOK: {current_char}{function_byte - 1}", file=sys.stderr)

		# process relative octave jumps
		elif current_char in ('<', '>'):
			# TODO: review - does this work correctly with new octave +1 encoding?
			octave_nibble = 0
			if current_char == '<':
				octave_nibble = int(previous_octave) - 1
			elif current_char == '>':
				octave_nibble = int(previous_octave) + 1
			previous_octave = str(octave_nibble)

			# squash the command and value to a single byte and output
			# TODO: review - changed from octave_nibble to octave_nibble + 1 for consistency
			output_byte = (command_lookup['o'] << 4) | (octave_nibble + 1)
			output_bytecode.append(output_byte)

			index += 1

		# process single byte commands
		elif current_char in ('&', '^', ']'):
			output_byte = 0
			
			# let's end a loop and hope it's zero by the end...
			if current_char == ']':
				matching_loop -= 1

			# AVR doesn't support ties (& and ^)
			# so don't output it to save space
			if current_char == ']':
				output_byte = command_lookup[current_char]
				output_bytecode.append(output_byte)

			index += 1

		# process percussion commands: x (on), x+ (on), x1 (on), x0 (off), x- (off)
		elif current_char == 'x':
			index += 1
			# check for modifiers
			if index < len(input_string) and input_string[index] in ('0', '-'):
				# percussion off: 0xF9
				output_bytecode.append(0xF9)
				index += 1
			else:
				# percussion on: 0xF8
				# handles x, x+, x1
				output_bytecode.append(0xF8)

		# move to the next character
		else:
			if current_char != ' ':
				raise CompilerWarning(f"Unknown command '{current_char}', ignoring.")
			index += 1

	return {'bytes': output_bytecode}


#####################################
# error and warning message handler #
#####################################

class bcolors:
	HEADER = '\033[95m'
	OKBLUE = '\033[94m'
	OKCYAN = '\033[96m'
	OKGREEN = '\033[92m'
	WARNING = '\033[93m'
	FAIL = '\033[91m'
	ENDC = '\033[0m'
	BOLD = '\033[1m'
	UNDERLINE = '\033[4m'

def throw_error(error_number,additional_info_1,additional_info_2):
	print(f"{bcolors.FAIL}ERROR: {bcolors.ENDC}", end = '', file=sys.stderr)
	match error_number:
		case 0:
			print("File not found.", file=sys.stderr)
		case 1:
			print("Too many channels (255 maximum).", file=sys.stderr)
		case 2:
			print("Too many patterns (255 maximum).", file=sys.stderr)
		case 3:
			print(f"Command '{additional_info_1}' must have a value.", file=sys.stderr)
		case 4:
			# Show appropriate range based on command
			if additional_info_1 == 'o':
				print(f"Command '{additional_info_1}' is {additional_info_2}, must be -1 - 14.", file=sys.stderr)
			else:
				print(f"Command '{additional_info_1}' is {additional_info_2}, must be 1 - 16.", file=sys.stderr)
		case 5:
			print(f"Note '{additional_info_1}{additional_info_2}' is an invalid duration.", file=sys.stderr)
		case 6:
			print("A loop has been opened but is missing a corresponding close event (']').", file=sys.stderr)
		case 7:
			print("There are too many closed loop commands (']').", file=sys.stderr)
		case 8:
			print(f"Command '{additional_info_1}' is {additional_info_2}, must be 1 - 256.", file=sys.stderr)
		case 9:
			print(f"Invalid value on export: {additional_info_1}. Each element should be a single byte (0-255).", file=sys.stderr)
		case 10:
			print(f"Command '{additional_info_1}{additional_info_2}' must be 2 - 256.", file=sys.stderr)
		case 11:
			print(f"Pattern is 'P0', must be 1- 256.", file=sys.stderr)
		case 12:
			print(f"Command '{additional_info_1}' is {additional_info_2}, must be -100 - 100.", file=sys.stderr)
		case _:
			print("Miscellaneous warning! The worst kind!", file=sys.stderr)
	sys.exit()

def throw_warning(warning_number,additional_info_1):
	print(f"{bcolors.WARNING}WARNING: {bcolors.ENDC}", end = '', file=sys.stderr)
	match warning_number:
		case 1:
			print(f"'{additional_info_1}' is an unknown command, ignoring.", file=sys.stderr)
		case _:
			print("Miscellaneous warning! The worst kind!", file=sys.stderr)


# --- Tokenizer: one 4ML element per token  ---

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
			if i < len(s) and s[i] == '-':
				tok += s[i]
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

		# Percussion toggle: x, x0, x-, x1, x+
		if c == "x":
			tok = "x"
			i += 1
			if i < len(s) and s[i] in "0+-":
				tok += s[i]
				i += 1
			tokens.append(tok)
			continue

		i += 1

	return tokens


def tokens_to_string(tokens: list[str]) -> str:
	"""Serialize token list back to 4ML (no spaces; caller can add for readability)."""
	return " ".join(tokens)


def decompose_notes(total_128th_notes):
	note_values = {
		"1": 128,
		"2":  64,
		"4":  32,
		"8":  16,
		"16":  8,
		"32":  4,
		"64":  2,
		"128": 1
	}
	result = []
	for note, value in note_values.items():
		while total_128th_notes >= value:
			total_128th_notes -= value
			result.append(note)
	return result
