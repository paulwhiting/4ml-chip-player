################################################################################
#  FILENAME:	 midi-to-4ml.py
#  DESCRIPTION:  MIDI to Mega Micro Music Macro Language (4ML) Converter
#
#  NOTES:		 Real bare-bones converter to convert MIDI files into something
#				 that 4ML players will be able to interpret. It's in such early
#				 stages that it's packed full of bugs and inaccuracies, plus the
#				 4ML it generates is pretty garbage.
#
#				 That said, it's been a really useful tool and works well enough
#				 if you're willing to cleanup the MIDI file before import and
#				 the converted code on export.
#
#				 Make sure your channels are free of overlapping notes and
#				 quantized to 128th notes minimum. The script should throw a
#				 warning if you mess this up somewhere, plus it'll go ahead and
#				 convert the rest anyway, but you might get timing issues.
#
#				 TO-DO:
#				 - Go though and comment stuff, because I rushed this for a
#				   project I'll forget how it works if I leave it too long.
#				 - Export the 4ML to a file, rather than just print to
#				   terminal.
#				 - The 4ML is ugly when printed too. Maybe add a space next to
#				   rests? Basically decide on a pretty format for the language.
#				 - FIX THE BUGZ
#
#				 BUGS:
#				 - Sometimes it will incorrectly interpret a 128th note as
#				   being shorter than it really is. Generally this is resolved
#				   automatically with no impact on MML timing, but you'll still
#				   get a warning. I think this is down to tick divisions not
#				   being 100% accurate over time, so I don't know how this is
#				   avoided in other conversion software.
#				 - Issue with removing repeated note lengths for tied durations.
#				   For example, g4&g32g4&g32 becomes g4&g32gg
#				 - Leading rests are ignored when processing any additional
#				   channels other than the first. For example if the MIDI went:
#				   C1 r4c8 C2 r4c8, it would processed as C1 r4c8 C2 c8
#				 - Newlines are incorrectly inserted one character after a new
#				   bar starts. So you get stuff like:
#				   C1 v4 o2 c4c4c4c4 v4 o2 c4
#				   c4c4c4
#				 - Bar numbers are wrong when reporting errors.
#
#  AUTHOR:		 Blake 'PROTODOME' Troise
#  PLATFORM:	 Command Line Application
#  DATE:		 8th January 2024
################################################################################

#############
# libraries #
#############

import mido
import sys
from collections import defaultdict

from utils import decompose_notes

# set this to 1 to enable printing, or to 0 to disable
debug = 0

# set this to split overlapping notes into a new channel
SUB_CHANNELS = True

# set this to 1 to enable velocity conversion
velocity_print = 1

# percussion detection (MIDI channel 9, notes 35-81)
GM_PERCUSSION_CHANNEL = 9
PERCUSSION_NOTE_MIN = 35
PERCUSSION_NOTE_MAX = 81

# set this to 1 to hide durations on repeat
duration_repeat = 0

# the number of 128th notes in a bar (mainly for printing bars cleanly and error messages)
# 4/4 = 128, 3/4 = 96
time_signature = 128

###################
# terminal colors #
###################

# Thanks to Peter Mortensen for the code:
# https://stackoverflow.com/questions/287871/how-do-i-print-colored-text-to-the-terminal

# only use color if printing to a terminal
if sys.stdout.isatty():
	class bcolors:
		HEADER	  = '\033[95m'
		OKBLUE	  = '\033[94m'
		OKCYAN	  = '\033[96m'
		OKGREEN   = '\033[92m'
		WARNING   = '\033[93m'
		FAIL	  = '\033[91m'
		ENDC	  = '\033[0m'
		BOLD	  = '\033[1m'
		UNDERLINE = '\033[4m'
else:
	class bcolors:
		HEADER	  = ''
		OKBLUE	  = ''
		OKCYAN	  = ''
		OKGREEN   = ''
		WARNING   = ''
		FAIL	  = ''
		ENDC	  = ''
		BOLD	  = ''
		UNDERLINE = ''

##################
# oh no an error #
##################

def throw_error(error_number,additional_info):
	print(f"{bcolors.FAIL}ERROR: {bcolors.ENDC}", end = '', file=sys.stderr)
	match error_number:
		case 0:
			print("File not found.", file=sys.stderr)
		case _:
			print("Miscellaneous error! The worst kind!", file=sys.stderr)

##################
# hmmm a warning #
##################

def throw_warning(warning_number,additional_info_1,additional_info_2):
	print(f"{bcolors.WARNING}WARNING: {bcolors.ENDC}", end = '', file=sys.stderr)
	match warning_number:
		case 0:
			print(f"Found a non 128th note duration in channel: {additional_info_2}, at bar: {additional_info_1}. This may not be your mistake, but be aware of timing issues.", file=sys.stderr)
		case 1:
			print(f"Found an overlapping note in channel: {additional_info_2}, at bar: {additional_info_1}.", file=sys.stderr)
		case _:
			print("Miscellaneous warning! The worst kind!", file=sys.stderr)

def midi_note_to_name(note_number):
	notes = ['c', 'c+', 'd', 'd+', 'e', 'f', 'f+', 'g', 'g+', 'a', 'a+', 'b']
	note_name = notes[note_number % 12]
	octave = note_number // 12 - 1
	return note_name, octave

def duration_to_128th_notes(ticks, ticks_per_beat):
	return (ticks * 32) / ticks_per_beat

def my_128th_notes_to_duration(my_128th_notes, ticks_per_beat):
	return (my_128th_notes * ticks_per_beat) / 32

def quantize_ticks(ticks, ticks_per_beat):
	d = duration_to_128th_notes(ticks, ticks_per_beat)
	return my_128th_notes_to_duration(round(d), ticks_per_beat)

def scale_volume(velocity):
	# Scale the volume from 0-127 to 1-16
	return int(velocity / 8) + 1

def process_midi_file(midi_file_path):
	global debug

	midi_file = mido.MidiFile(midi_file_path)

	# default tempo (120 BPM)
	tempo = 500000

	# track position
	total_128th_notes = 0
	total_ticks = 0
	current_bar = 0

	# array to store the MIDI data
	midi_data = []

	# dictionary to track the active note in each channel
	active_notes = {}
	last_note_off_time = {}

	# dictionary to track which channels are percussion
	percussion_channels = {}

	if debug:
		print(f'ticks_per_beat: {midi_file.ticks_per_beat}')

	for track in midi_file.tracks:
		current_time = 0

		for msg in track:
			if debug:
				print(msg)
			if not msg.is_meta:
				current_time += msg.time
				total_ticks  += msg.time

			current_time_q = quantize_ticks(current_time, midi_file.ticks_per_beat)

			if msg.type == 'set_tempo':
				tempo = msg.tempo

			elif msg.type == 'note_on' and msg.velocity > 0:
				# check for overlapping notes

				# use sub-channels for overlapping notes
				orig_channel = msg.channel
				sub_channel = 0
				the_channel = msg.channel
				if SUB_CHANNELS:
					while the_channel in active_notes:
						#print(f'Preventing Concern: {the_channel} in {active_notes}\n',file=sys.stderr)
						sub_channel += 1
						the_channel = f'{orig_channel}-{sub_channel}'

				# detect percussion: MIDI channel 9 with note in range 35-81
				is_percussion = (msg.channel == GM_PERCUSSION_CHANNEL and 
								 PERCUSSION_NOTE_MIN <= msg.note <= PERCUSSION_NOTE_MAX)
				if is_percussion:
					percussion_channels[orig_channel] = True

				if the_channel in active_notes:
					print(f'Concern: {the_channel} in {active_notes}\n',file=sys.stderr)

					# overlapping note detected
					throw_warning(1, round(total_128th_notes / time_signature, 2), track.name)

					# process the previous note
					prev_note, prev_start_time = active_notes[the_channel]
					note_duration = current_time_q - prev_start_time
					note_128th_notes = duration_to_128th_notes(note_duration, midi_file.ticks_per_beat)

					note_notes = decompose_notes(round(note_128th_notes))
					note_name, octave = midi_note_to_name(prev_note)

					if debug:
						print(f"{current_time_q-note_duration} {note_duration} {current_time} {current_time_q} {note_name}{octave} {note_128th_notes}\n")
					midi_data.append([str(the_channel), track.name, note_name, octave, note_notes, volume, f'{note_128th_notes:.2f}', f'{note_duration:.2f}', f'{current_bar:.2f}', current_time_q-note_duration, current_time_q])

					total_128th_notes += note_128th_notes
					del active_notes[the_channel]
					last_note_off_time[the_channel] = current_time_q

				# check for rest
				last_off = last_note_off_time.get(the_channel, 0)
				if current_time_q > last_off:
					rest_duration = current_time_q - last_off
					rest_128th_notes = duration_to_128th_notes(rest_duration, midi_file.ticks_per_beat)

					if debug:
						print(f"{current_time_q-rest_duration} {rest_duration} {current_time_q} {current_time_q} rest {rest_128th_notes}\n")

					if rest_128th_notes != 0:
						rest_notes = decompose_notes(round(rest_128th_notes))
						midi_data.append([str(the_channel), track.name, 'r', '-', rest_notes, '-', f'{rest_128th_notes:.2f}', f'{rest_duration:.2f}', f'{current_bar:.2f}', current_time_q-rest_duration, current_time_q])

						total_128th_notes += rest_128th_notes

				# start the new note
				note_start_time = current_time_q
				volume = scale_volume(msg.velocity)
				active_notes[the_channel] = (msg.note, note_start_time)

			elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):

				the_channel = msg.channel

				# find the active note, possibly in a sub-channel
				if SUB_CHANNELS:
					if msg.channel in active_notes and active_notes[msg.channel][0] == msg.note:
						the_channel = msg.channel
					else:
						for channel in active_notes:
							if str(channel).startswith(f"{msg.channel}-"):
								if active_notes[channel][0] == msg.note:
									the_channel = channel
									break

				if the_channel in active_notes and active_notes[the_channel][0] == msg.note:
					note_duration = current_time_q - active_notes[the_channel][1]
					note_128th_notes = duration_to_128th_notes(note_duration, midi_file.ticks_per_beat)

					# check for note smaller than a 128th note
					if not note_128th_notes.is_integer():
						print(f'Concern: {the_channel} in {active_notes} and {note_duration} and {note_128th_notes}\n', file=sys.stderr)
						throw_warning(0, round(total_128th_notes / time_signature, 2), track.name)

					note_notes = decompose_notes(round(note_128th_notes))
					note_name, octave = midi_note_to_name(msg.note)

					if debug:
						print(f"{current_time_q-note_duration} {note_duration} {current_time} {current_time_q} {note_name}{octave} {note_128th_notes}\n")

					midi_data.append([str(the_channel), track.name, note_name, octave, note_notes, volume, f'{note_128th_notes:.2f}', f'{note_duration:.2f}', f'{current_bar:.2f}', current_time_q-note_duration, current_time_q])

					total_128th_notes += note_128th_notes
					del active_notes[the_channel]

					last_note_off_time[the_channel] = current_time_q

	if debug:
		# determine column widths
		column_widths = [max(len(str(item[i])) for item in midi_data) for i in range(len(midi_data[0]))]

		# print the data with formatting
		for item in midi_data:
			formatted_line = ' '.join(str(field).ljust(column_widths[i]) for i, field in enumerate(item))
			print(formatted_line)


	# create the mml output
	else:
		previous_channel  = ''
		previous_note_name	   = ''
		previous_duration = 0
		previous_octave   = 0
		previous_volume   = 0
		max_128th_notes   = 0
		total_128th_notes = 0
		total_channels	  = 0
		channel_details = {}
		channel_data = ""

		midi_data.sort(key=lambda x: x[0])

		for i, item in enumerate(midi_data):
			mml_channel		  = item[0]
			mml_track_name	  = item[1]
			mml_note_name	  = item[2]
			mml_octave		  = item[3]
			mml_note_duration = f'&{mml_note_name}'.join(item[4])
			mml_volume		  = item[5]
			mml_128ths		  = float(item[6])

			if previous_channel != mml_channel:
				total_channels	 += 1
				channel_data = f'\n\n; {mml_channel} {mml_track_name}\n'
				channel_data += f'{bcolors.WARNING}C{total_channels} {bcolors.ENDC}'
				
				# add x command if this is a percussion channel
				if base_channel in percussion_channels:
					channel_data += f'x'

				# reset everything for new channel
				previous_duration = 0
				previous_octave   = 0
				previous_volume   = 0
				total_128th_notes = 0

			if previous_octave != mml_octave and mml_octave != '-':
				channel_data += f'{bcolors.FAIL}o{mml_octave}{bcolors.ENDC}'

			if velocity_print != 0:
				if previous_volume != mml_volume and mml_volume != '-':
					channel_data += f'{bcolors.OKBLUE}v{mml_volume}{bcolors.ENDC}'
			
			if mml_note_duration:
				channel_data += f'{mml_note_name}'

				if duration_repeat == 1:
					if previous_duration != mml_note_duration:
						channel_data += f'{mml_note_duration}'
				else:
					channel_data += f'{mml_note_duration}'

			# newline for every bar
			#if (int(total_128th_notes) % time_signature) == 0:
				#channel_data += '\n'

			# store values for recall next loop
			if mml_volume != '-':
				previous_volume = mml_volume

			if mml_octave != '-':
				previous_octave = mml_octave

			previous_duration  = mml_note_duration
			previous_channel   = mml_channel
			previous_note_name = mml_note_name
			total_128th_notes += round(mml_128ths)
			channel_details[total_channels] = {'name': mml_track_name, 'midi_channel': mml_channel, 'runtime': total_128th_notes, 'data': channel_data}
			if total_128th_notes > max_128th_notes:
				max_128th_notes = total_128th_notes

		# pad out the channels to the same length
		for item in channel_details:
			channel = channel_details[item]
			diff = max_128th_notes - channel['runtime']
			if diff:
				rests = decompose_notes(diff)
				channel['data'] += f'r{"r".join(rests)}'

		for item in channel_details:
			channel = channel_details[item]
			print(channel['data'])
			

# main()
midi_file_path = sys.argv[1]
process_midi_file(midi_file_path)
