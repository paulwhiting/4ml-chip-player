################################################################################
#  FILENAME:     compiler.py
#  DESCRIPTION:  Mega Micro Music Macro Language (4ML) Compiler
#
#  NOTES:        A quick 'n dirty python-based compiler for the 4ML language.
#                It works, but I don't trust the regex. In fact, I don't really
#                trust any of this. See 4ml.md in the 'docs' directory for a
#                full explanation.
# 
#                An upgrade of:
#                https://github.com/protodomemusic/mmml
#
#                BUGS:
#                - If you don't have any patterns, it won't compile. Dumb.
#                - Find a neat way of unifying tempos across platforms.
#                - Putting multiple > or < commands together will write multiple
#                  octaves. Should really just do one.
#                - 'p' commands should be paired with the pattern 'P' to which
#                  they refer. For example p10 should refer to P10, even if
#                  there are ultimately fewer than 10 patterns and all the
#                  indexes change.
#                - Handle error for durations like 'r1.' (which is invalid).
#                - Handle error for r+. Or should you be allowed to sharpen a
#                  rest? Probably. It's doing no harm.
#                - Handle error when you write something like 'g364' (so like
#                  when the value isn't in the lookup table).
#
#  AUTHOR:       Blake 'PROTODOME' Troise
#  PLATFORM:     Command Line Application
#  DATE:         29th July 2023
################################################################################

#############
# libraries #
#############

import sys
import re
import struct

#################
# global values #
#################

# reduces all volume commands by 1 step out of 16
#volume_reduction = 2
volume_reduction = 0

# the output needs to be tweaked a bit depending on the platform
# possible targets: 'AVR' for AVR microcontroller code, or blank for anything else
target_platform = 'GB'

###################
# terminal colors #
###################

# Thanks to Peter Mortensen for the code:
# https://stackoverflow.com/questions/287871/how-do-i-print-colored-text-to-the-terminal

class bcolors:
	HEADER    = '\033[95m'
	OKBLUE    = '\033[94m'
	OKCYAN    = '\033[96m'
	OKGREEN   = '\033[92m'
	WARNING   = '\033[93m'
	FAIL      = '\033[91m'
	ENDC      = '\033[0m'
	BOLD      = '\033[1m'
	UNDERLINE = '\033[4m'

##################
# oh no an error #
##################

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
			print("Miscellaneous error! The worst kind!", file=sys.stderr)
	sys.exit()

##################
# hmmm a warning #
##################

def throw_warning(warning_number,additional_info):
	print(f"{bcolors.WARNING}WARNING: {bcolors.ENDC}", end = '', file=sys.stderr)
	match warning_number:
		case 0:
			print(f"Additional definition of pattern #{additional_info}. Combining them.", file=sys.stderr)
		case 1:
			print(f"Skipped unexpected symbol '{additional_info}'.", file=sys.stderr)
		case 2:
			print(f"Your patterns aren't sequential, or don't begin at P1."
			"\nYour 'p' commands may not refer to the expected pattern.", file=sys.stderr)
		case _:
			print("Miscellaneous warning! The worst kind!", file=sys.stderr)


#############################
# construct the output file #
#############################

total_size       = 0
album_max_channels   = 0

def write_mmml_header(array, output_file):
	current_column = 0

	for num in array:

		if current_column == 0:
			output_file.write("\t")

		# convert each element to a 16-bit number (unsigned short, 'H')
		# using struct.pack and then get the hexadecimal representation.
		hex_bytes = struct.pack('H', num)
		
		# unpack the two bytes from the resulting bytes object
		byte1, byte2 = hex_bytes

		# visual thing, just make the output file look nice
		
		# print the bytes in hexadecimal format
		output_file.write(f"0x{byte2:02X},0x{byte1:02X},")

		current_column += 2
		if current_column == 16:
			output_file.write("\n")
			current_column = 0


def write_mmml_body(byte_array_list, output_file):
	current_column = 0

	for byte_array in byte_array_list:
		for num_str in byte_array:

			if current_column == 0:
				output_file.write("\t")

			# convert the string element to an integer
			num = int(num_str)

			# check if the number is within the valid range (0-255)
			if num < 0 or num > 255:
				throw_error(9,num,0)
			else:
				# convert the integer to a single byte using struct.pack
				hex_byte = struct.pack('B', num)
				
				# unpack the single byte from the resulting bytes object
				byte = hex_byte[0]

				# print the byte in hexadecimal format
				output_file.write(f"0x{byte:02X},")

				current_column += 1
				# visual thing, just make the output file look nice
				if current_column == 16:
					output_file.write("\n")
					current_column = 0
	if current_column != 0:
		output_file.write("\n")


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
		'f+':0x07, 'g': 0x08, 'g+':0x09, 'a': 0x0A, 'a+':0x0B, 'b': 0x0C, 'b+':0x01, 'o': 0x0D,
		'v': 0x0E, 'p': 0xF2, 't': 0xF3, '@': 0xF5, 'i': 0xF5, '[': 0xF0, ']': 0xF1, '&': 0xF6,
		'^': 0xF6, 'K': 0xF4, 's': 0xF7, 'F': 0xFE
	}

	duration_lookup = {
		'1':   0x00, '2':  0x01, '4':  0x02, '8':  0x03, '16':  0x04, '32':  0x05, '64':  0x06,
		'128': 0x07, '2.': 0x08, '4.': 0x09, '8.': 0x0A, '16.': 0x0B, '32.': 0x0C, '64.': 0x0D
	}

	# duration (as written) to length in 128th-note units
	duration_to_128th = {
		'1':   128,
		'2':    64,
		'4':    32,
		'8':    16,
		'16':    8,
		'32':    4,
		'64':    2,
		'128':   1,
		'2.':   96,
		'4.':   48,
		'8.':   24,
		'16.':  12,
		'32.':   6,
		'64.':   3,
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
			note_duration   = ''
			note_nibble     = 0
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
			note_nibble     = command_lookup  [current_char]
			duration_nibble = duration_lookup [note_duration]

			# check if in bounds
			if duration_nibble > 16 or duration_nibble < 0:
				throw_error(5, current_char, note_duration)

			# Collapse tied/successive same-note durations into minimal byte sequence
			# base duration in 128th-note units
			if note_duration not in duration_to_128th:
				throw_error(5, current_char, note_duration)
			total_128 = duration_to_128th[note_duration]
			last_duration = note_duration
			base_letter = current_char[0]

			scan_index = index

			# consume any following &/^ and same-note tokens, accumulating duration
			while scan_index < len(input_string):
				tmp = scan_index

				# skip explicit tie/slur symbols
				while tmp < len(input_string) and input_string[tmp] in ('&', '^'):
					tmp += 1

				if tmp >= len(input_string):
					break

				# must be same base note letter
				if input_string[tmp] != base_letter:
					break

				tmp2 = tmp + 1
				next_char = base_letter

				# optional sharpening
				if tmp2 < len(input_string) and input_string[tmp2] in ('+', '#'):
					next_char = next_char + '+'
					tmp2 += 1

				# different accidental = different note, stop collapsing
				if next_char != current_char:
					break

				# parse optional duration for this subsequent note
				next_duration = ''
				while tmp2 < len(input_string) and input_string[tmp2].isdigit() and len(next_duration) < 3:
					next_duration += input_string[tmp2]
					tmp2 += 1

				if tmp2 < len(input_string) and input_string[tmp2] == '.':
					next_duration = next_duration + '.'
					tmp2 += 1

				# if no duration given, repeat the last one
				if next_duration:
					last_duration = next_duration
					previous_duration = next_duration
				else:
					next_duration = last_duration

				if next_duration not in duration_to_128th:
					throw_error(5, current_char, next_duration)

				total_128 += duration_to_128th[next_duration]
				scan_index = tmp2

			# advance main index past everything we collapsed
			index = scan_index

			# encode the accumulated duration using the smallest number of command bytes
			# First preference: a single built-in duration
			if total_128 in duration_128th_to_nibble:
				final_duration_nibble = duration_128th_to_nibble[total_128]
				output_byte = (note_nibble << 4) | final_duration_nibble
				output_bytecode.append(output_byte)
			else:
				remaining = total_128

				# if it fits in a single extended-duration command, use that
				if remaining <= 0xFF:
					output_bytecode.append((note_nibble << 4) | 0x0F)
					output_bytecode.append(remaining)
				else:
					# chunk into 0xFF-sized pieces, then a final chunk for the remainder
					while remaining > 0xFF:
						output_bytecode.append((note_nibble << 4) | 0x0F)
						output_bytecode.append(0xFF)
						remaining -= 0xFF

					if remaining:
						# if the remainder matches a built-in duration, we can save a byte
						if remaining in duration_128th_to_nibble:
							final_duration_nibble = duration_128th_to_nibble[remaining]
							output_byte = (note_nibble << 4) | final_duration_nibble
							output_bytecode.append(output_byte)
						else:
							output_bytecode.append((note_nibble << 4) | 0x0F)
							output_bytecode.append(remaining)

		# process single byte commands with values
		elif current_char in ('o', 'v'):
			function_value  = ''
			command_nibble  = 0
			function_nibble = 0

			index += 1

			# check for the next characters after the letter
			while index < len(input_string) and input_string[index].isdigit() and len(function_value) < 3:
				function_value += input_string[index]
				index += 1

			# you've got to have a value with it!
			if not function_value:
				throw_error(3,current_char,0)

			# if it's an octave, store the value for the '<' and '>' commands
			if current_char == 'o':
				previous_octave = int(function_value) - 1

			# get the right command byte
			command_nibble = command_lookup[current_char]

			# convert string to int, check if in bounds
			function_nibble = int(function_value)
			if function_nibble > 16 or function_nibble < 1:
				throw_error(4, current_char, function_nibble)

			# volume-specific conditions
			if current_char == 'v':
				# 4ML has a 1-16 range, but there are only 8 possible states for the AVR player

				# reduce volume (useful if you want to do this globally)
				if function_nibble > 16:
					function_nibble = 16
				if function_nibble < 1:
					function_nibble = 1

			# squash the command and value to a single byte and output
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
				throw_error(3, current_char, 0)

			# you've got to have a value with it!
			if not function_value:
				throw_error(3, current_char, 0)

			# convert to byte code
			command_byte = command_lookup[current_char]
			function_byte = int(function_value)

			# apply negative sign if necessary
			if is_negative:
				function_byte *= -1

			# transpose and panning can be negative (-100 to 100)
			if current_char in ('K', 's'):
				if function_byte > 100 or function_byte < -100 :
					throw_error(12, current_char, function_byte)
				else:
					function_byte += 100 + 1
			# other values cannot be negative
			elif function_byte < 0:
				throw_error(8, current_char, function_byte)

			# let's start a loop to see if it'll end
			if current_char == '[':
				matching_loop += 1
				if abs(function_byte) < 2:
					throw_error(10, current_char, function_value)
				function_byte += 1

			# check if the function value is out of bounds
			if function_byte > 256 or function_byte < -256:
				throw_error(8, current_char, function_value)

			# add to data array
			output_bytecode.append(command_byte)
			output_bytecode.append(function_byte - 1)

			if function_byte -1 < 0:
				print(f"LOOK: {current_char}{function_byte - 1}", file=sys.stderr)

		# process relative octave jumps
		elif current_char in ('<', '>'):
			octave_nibble = 0
			if current_char == '<':
				octave_nibble = int(previous_octave) - 1
			elif current_char == '>':
				octave_nibble = int(previous_octave) + 1
			previous_octave = str(octave_nibble)

			# squash the command and value to a single byte and output
			output_byte = (command_lookup['o'] << 4) | octave_nibble
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
			if current_char == ']' or target_platform != 'AVR':
				output_byte = command_lookup[current_char]
				output_bytecode.append(output_byte)

			index += 1

		# move to the next character
		else:
			if current_char != ' ':
				throw_warning(1,current_char)
			index += 1

	# just double check that the loop commands match up
	if matching_loop > 0:
		throw_error(6,0,0)
	elif matching_loop < 0:
		throw_error(7,0,0)

	if output_end_channel_byte:
		# end the sequence with a secret channel/pattern end event
		output_bytecode.append(0xFF)

	return output_bytecode


###################
# import the file #
###################

def process_file(input_file):
	global total_size
	global album_max_channels

	try:
		# open the text file in read mode
		with open(input_file, 'r') as f:

			# read the contents of the file
			mmml_data_string = f.read()

			# delete ; comments
			mmml_data_string = re.sub(';.*?\n', '', mmml_data_string)
			mmml_data_string = re.sub(';.*?\Z', '', mmml_data_string)

			# delete /* */ comments
			mmml_data_string = re.sub('/\\*([\s\S]*?)\\*/', '', mmml_data_string, re.MULTILINE)

			# remove all remaining whitespace
			mmml_data_string = re.sub(r'\s', '', mmml_data_string)

	except FileNotFoundError:
		throw_error(0,0,0)

	####################
	# get channel data #
	####################

	print(f"{bcolors.OKBLUE}Detecting 4ML document structure...\n{bcolors.ENDC}", file=sys.stderr)

	# get highest number after C
	# the highest number is the total number of channels
	pattern        = r'C(\d+)'
	matches        = re.findall(pattern, mmml_data_string)
	max_channel    = max(map(int, matches))
	track_channels = 0

	# put channel data together contiguously
	channel_data = []

	for x in range(max_channel + 1):
		# match from Cx to the next C or P
		matches = re.findall(fr'C{x}([^CP]+)', mmml_data_string)

		# C30 will match for both C3 and C30, so remove any data that starts with a
		# digit. Not sure the best way of doing this in the regex - which would have
		# been simpler.
		matches = [match for match in matches if not match[0].isdigit()]
		results = "".join(matches)
		channel_data.append(results)

	# we need the blank results for ordering channels hierarchically
	# but they need to be removed to get the actual amount
	while '' in channel_data:
		channel_data.remove('')

	# how many channels are we left with?
	track_channels = len(channel_data)

	print(f"Found {track_channels} channel(s).", file=sys.stderr)

	# 4ml players use 8-bit numbers
	if track_channels > 256:
		throw_error(1,0,0)

	if track_channels > album_max_channels:
		album_max_channels = track_channels

	####################
	# get pattern data #
	####################

	# get highest number after P
	# the highest number is the total number of patterns
	pattern         = r'P(\d+)'
	matches         = re.findall(pattern, mmml_data_string)
	pattern_numbers = []

	for match in matches:
		current_pattern = int(match)

		# 4ml players use 8-bit numbers
		if current_pattern > 256:
			throw_error(2,0,0)

		if current_pattern == 0:
			throw_error(11,0,0)

		if current_pattern in pattern_numbers:
			# if the pattern number is already in the list, then it's a repeated
			# pattern, so throw a warning.
			throw_warning(0,current_pattern)
		else:
			pattern_numbers.append(current_pattern)

	if pattern_numbers:
		max_patterns = max(pattern_numbers)
	else:
		max_patterns = 0

	# put pattern data together contiguously
	pattern_data = []

	for x in range(max_patterns + 1):
		# match from PX to the next C or P
		matches = re.findall(fr'P{x}([^PC]+)', mmml_data_string)

		# Filter out matches that start with a digit
		matches = [match for match in matches if not match[0].isdigit()]

		results = "".join(matches)
		pattern_data.append(results)

	# we need the blank results for ordering channels hierarchically
	# but they need to be removed to get the actual amount
	while '' in pattern_data:
		pattern_data.remove('')

	# how many channels are we left with?
	total_patterns = len(pattern_data)

	print(f"Found {total_patterns} pattern(s).", file=sys.stderr)

	# hmm, the patterns are no longer synced 1 to 1
	if total_patterns != max_patterns:
		throw_warning(2,0)

	# combine channel and pattern data
	mmml_data_string = channel_data + pattern_data

	print(f"{track_channels + total_patterns} sequences total.", file=sys.stderr)

	########################
	# start the conversion #
	########################

	print(f"{bcolors.OKBLUE}\nBeginning compilation...\n{bcolors.ENDC}", file=sys.stderr)

	# where we'll put our data
	mmml_data_header = []
	mmml_data_bytes  = []

	track_offset = total_size
	# calculate the total size of the header
	total_size += (track_channels + total_patterns) * 2

	# loop through each string in the array to build our data file
	for index, string in enumerate(mmml_data_string):
		print(f"Sequence {index + 1} of {len(mmml_data_string)}", file=sys.stderr)

		# add the first sequence data to the output array
		mmml_data_bytes.append(process_mmml_string(string))

		# update the header with the offset to this track
		mmml_data_header.append(total_size)

		# show the length of the data and update total length
		#print(f"({len(mmml_data_bytes[index])} bytes)", file=sys.stderr)
		total_size += len(mmml_data_bytes[index])

		# debug: print input string and print compiled byte code
		#print(string, file=sys.stderr)
		#print(mmml_data_bytes[index], file=sys.stderr)

	return {"file":input_file, "header": mmml_data_header, "data": mmml_data_bytes, "channels": track_channels, "offset": track_offset}


#####################
# start the program #
#####################

def main():
	print(f"\nHello! Welcome to the Mega Micro Music Macro Language (4ML) compiler!\n", file=sys.stderr)

	if '--avr' in sys.argv:
		target_platform = 'AVR'
		sys.argv.remove('--avr')

	# if we don't have enough arguments, shut it down!
	if len(sys.argv) < 2:
		print("to run use: python compiler.py <filename> (<filename> ...)", file=sys.stderr)
		sys.exit()

	files = sys.argv[1:]

	album = []

	for file in files:
		album.append(process_file(file))

	print(f"{bcolors.OKBLUE}\nWriting to output file...{bcolors.ENDC}", file=sys.stderr)

	# write to output file

	print("\n/*\n\ttrack list:")
	for track in album:
		hlen = 2*len(track['header'])
		dlen = sum([len(t) for t in track['data']])
		print(f"\t {hlen} + {dlen} = {hlen+dlen} bytes - {track['file']}")
	print("*/\n")

	print(f"#define TOTAL_TRACKS {len(album)}")
	print(f'const uint8_t TRACK_VOICES[] = {{{", ".join([str(track['channels']) for track in album])}}};')
	print(f'const uint16_t TRACK_OFFSET[] = {{{", ".join([str(track["offset"]) for track in album])}}};\n')

	print(f"#define MAX_VOICES {album_max_channels}")

	# if it's AVR, we'll need to store it in program memory
	if target_platform == 'AVR':
		print("const unsigned char _4ml_data[] PROGMEM = {")
	else:
		print("const unsigned char _4ml_data[] = {")

	for track in album:
		print(f"\n\t// {track['file']}")
		print("\n\t// header")
		write_mmml_header(track["header"], sys.stdout)
		print("\n\n\t// data")
		write_mmml_body  (track["data"], sys.stdout)

	print("\n};")


	print(f"\nFinished! Total size {total_size} bytes.", file=sys.stderr)

	# let's wrap up
	print(f"{bcolors.OKGREEN}\nCompilation complete!\n{bcolors.ENDC}", file=sys.stderr)

if __name__ == "__main__":
	main()
