/*H*****************************************************************************
*  FILENAME:     4ml-avr-player.c
*  DESCRIPTION:  Mega Micro Music Macro Language (4ML) Player for AVR
*                microcontrollers.
*
*  NOTES:        To be compiled with AVR C.
*
*                Make sure you include exactly 4 channels worth of material.
*
*                A four-channel MML inspired 1-bit music player. Three channels
*                of harmonic pulse wave and a percussive sampler or noise
*                generator.
*
*                Eight different duty cycles possible:
*                50%, 25%, 12.5%, 6.25%, 3.125%, 1.5625%, 0.78125% and 0.390625%
*
*                The 'thinner' pulse widths are perceived as a change in
*                waveform power (volume) as opposed to a change in timbre.
*
*                Tested on:
*                  * Attiny13/45/85 @ 8MHz
*                  * Atmega168/328  @ 8MHz
*
*  AUTHOR:       Blake 'PROTODOME' Troise
*  DATE:         20th December 2017 (Original)
*                28th January 2024 (Update)
*****************************************************************************H*/


#include <avr/io.h>         // core avr functionality
#include <avr/pgmspace.h>   // * * *
#include <util/delay.h>

#include "4ml-data.h"       // holds the _4ml_data[] arrays

#ifdef DEBUG
#include <stdio.h>
#endif

// stuff you can mess with
//#define OUTPUT         0    // the PORTB hardware output pin
#define OUTPUT         3    // the PORTB hardware output pin

// stuff you shouldn't really mess with
#define SAMPLE_SPEED   5    // the sampler playback rate
#define SAMPLE_LENGTH  127  // the length of the sample array
#define MAXLOOPS       5    // the maximum number of nested loops


#define CMD_REST    0
#define CMD_OCTAVE 13
#define CMD_VOLUME 14
#define CMD_FN     15
#define CMD_FN_LOOP_START 0
#define CMD_FN_LOOP_END   1
#define CMD_FN_MACRO      2
#define CMD_FN_TEMPO      3
#define CMD_FN_TRANSPOSE  4
#define CMD_FN_INSTRUMENT 5
#define CMD_FN_TIE        6
#define CMD_FN_PAN        7
#define CMD_FN_PERCUSSION 8
#define CMD_FN_PERCUSSION_OFF 9
#define CMD_FN_MISC       14
#define CMD_FN_END        15

// throw a compile-time error if the 4ML data isn't AVR compatible

// note table (times 4 to compensate for octave nibble+1 encoding)
const uint16_t note[13] /*PROGMEM*/ = 
{
	// the rest command is technically note 0 and thus requires a frequency 
	255,
	// one octave of notes, equal temperament in Gb (multiplied by 4)
	4096,3868,3648,3444,3252,3068,2896,2732,2580,2436,2300,2168
};

// location of individual samples in sample array
const uint8_t sample_index[6] PROGMEM =
{
	0,19,34,74,118,126
};

// raw PWM sample data
const uint8_t sample[SAMPLE_LENGTH] PROGMEM =
{
	// bwoop (0)
	0b10101010,0b10110110,0b10000111,0b11111000,
	0b10000100,0b00110111,0b11101000,0b11000001,
	0b00000111,0b00111101,0b11111000,0b11100000,
	0b10010001,0b10000111,0b00000111,0b00001111,
	0b00001111,0b00011011,0b00011110,
	// beep (19)
	0b10101010,0b00101010,0b00110011,0b00110011,
	0b00110011,0b00110011,0b00110011,0b11001101,
	0b11001100,0b11001100,0b11001100,0b10101100,
	0b10011001,0b00110001,0b00110011,
	// kick (34)
	0b10010101,0b10110010,0b00000000,0b11100011,
	0b11110000,0b00000000,0b11111111,0b00000000,
	0b11111110,0b00000000,0b00000000,0b00000000,
	0b11111111,0b11111111,0b11111111,0b00100101,
	0b00000000,0b00000000,0b00000000,0b00000000,
	0b11111111,0b11110111,0b11111111,0b11111111,
	0b11111111,0b10111111,0b00010010,0b00000000,
	0b10000000,0b00000000,0b00000000,0b00000000,
	0b00000000,0b11101110,0b11111111,0b11111111,
	0b11111111,0b11110111,0b11111111,0b11111110,
	// snare (74)
	0b10011010,0b10011010,0b10101010,0b10010110,
	0b01110100,0b10010101,0b10001010,0b11011110,
	0b01110100,0b10100000,0b11110111,0b00100101,
	0b01110100,0b01101000,0b11111111,0b01011011,
	0b01000001,0b10000000,0b11010100,0b11111101,
	0b11011110,0b00010010,0b00000100,0b00100100,
	0b11101101,0b11111011,0b01011011,0b00100101,
	0b00000100,0b10010001,0b01101010,0b11011111,
	0b01110111,0b00010101,0b00000010,0b00100010,
	0b11010101,0b01111010,0b11101111,0b10110110,
	0b00100100,0b10000100,0b10100100,0b11011010,
	// hi-hat (118)
	0b10011010,0b01110100,0b11010100,0b00110011,
	0b00110011,0b11101000,0b11101000,0b01010101,
	0b01010101,
	// end (126)
};


// for some reason the code plays faster if this is global rather than local
uint8_t  song_voices;

// channel variables (grouped in arrays)
uint8_t  out              [MAX_VOICES],
		 octave           [MAX_VOICES],
		 length           [MAX_VOICES],
		 volume           [MAX_VOICES],
		 loops_active     [MAX_VOICES],
		 is_percussion    [MAX_VOICES],
		 instrument       [MAX_VOICES];

uint16_t data_pointer     [MAX_VOICES],
		 waveform         [MAX_VOICES],
		 pitch_counter    [MAX_VOICES],
		 frequency        [MAX_VOICES],
		 loop_duration    [MAXLOOPS][MAX_VOICES],
		 loop_point       [MAXLOOPS][MAX_VOICES],
		 pointer_location [MAX_VOICES];

int play_song(uint8_t xxxsong_voices, uint16_t song_idx)
{
//#ifndef song_voices
	song_voices = xxxsong_voices;
	//printf("Track voices: %d\n", song_voices);
	//printf("Track offset: 0x%x\n", song_idx);

//#endif
	//uint8_t song_voices = xxxsong_voices;
    //CLKPR = _BV(CLKPCE);
    //CLKPR = _BV(CLKPS0);
    //interrupts();

	// sampler variables
	uint8_t  currentByte     = 0,
	         currentBit      = 0,
	         sample_counter  = 0,
	         current_sample  = 0;

	// temporary data storage variables
	uint8_t  buffer1         = 0,
	         buffer2         = 0,
	         buffer3         = 0;
	uint16_t buffer4         = 0;

	// main timer variables
	uint16_t tick_counter    = 0,
	         tick_speed      = 1024; // default tempo

	/* Set each channel's data pointer to that channel's data location in the core data array.
	 * Initialize each channel's frequencies. By default they're set to zero which causes out of
	 * tune notes (due to timing errors) until every channel is assigned frequency data.
	 * Additionally, default values are set should no volume or octave be specified */

	for(uint8_t i = 0; i < song_voices; i++)
	{
		data_pointer[i] = pgm_read_byte(_4ml_data + ((i*2)+song_idx));
		data_pointer[i] = data_pointer[i] << 8;
		data_pointer[i] = data_pointer[i] | pgm_read_byte(&_4ml_data[(i*2)+1+song_idx]);

		frequency[i]       = 255; // random frequency (won't ever be sounded)
		volume[i]          = 1;
		octave[i]          = 3;   // default octave : o3
		is_percussion[i]   = 0;   // default: not percussion
		out[i]             = 0;
		length[i]          = 0;
		loops_active[i]    = 0;

		waveform[i]      = 0;
		pitch_counter[i] = 0;
		pointer_location[i] = 0;

		//TODO: initialize
		//loop_duration    [MAXLOOPS][MAX_VOICES],
		//loop_point       [MAXLOOPS][MAX_VOICES],
	}

	while(1)
	{
		/**********************
		 *  Synthesizer Code  *
		 **********************/

		/* Port changes (the demarcated 'output' commands) are carefully interleaved with
		 * generation code to balance volume of outputs. */

        /* One branch per voice: out = (pitch_counter < waveform) ? high : 0 */
        for(uint8_t voice = 0; voice < song_voices; voice++) {
			if (is_percussion[voice] == 0) {
				PORTB = out[voice];
				pitch_counter[voice] += octave[voice];
				if(pitch_counter[voice] >= frequency[voice])
					pitch_counter[voice] -= frequency[voice];
				out[voice] = (pitch_counter[voice] < waveform[voice]) ? (1 << OUTPUT) : 0;
			}

			else if(sample_counter-- == 0)
			{
				PORTB = out[voice];
				if(currentByte < current_sample - 1)
				{
					// read individual bits from the sample array
					out[voice] = ((pgm_read_byte(&sample[currentByte]) >> currentBit++) & 1) << OUTPUT;
				}
				else
				{
					/* Waste the same number of clock cycles as it takes to process the above to
					 * prevent the pitch from changing when the sampler isn't playing. */
					for(uint8_t i = 0; i < 8; i++)
						asm("nop;nop;");

					// silence the channel when the sample is over
					out[voice] = 0;
				}

				// move to the next byte on bit pointer overflow
				if(currentBit > 7)
				{
					currentByte ++;
					currentBit = 0;
				}
				sample_counter = SAMPLE_SPEED;
			}
        }
		PORTB = 0;


		/**************************
		 *  Data Processing Code  *
		 **************************/

		if(tick_counter-- == 0)
		{
			// variable tempo, sets the fastest / smallest possible clock event
			tick_counter = tick_speed;

			for(uint8_t voice = 0; voice < song_voices; voice++)
			{
				// if the note ended, start processing the next byte of data
				if(length[voice] == 0)
				{
					LOOP: // yup, a goto, I know

					// single PROGMEM read for both nibbles
					buffer1 = pgm_read_byte(&_4ml_data[data_pointer[voice]]);
					buffer2 = buffer1 & 15;
					buffer1 = buffer1 >> 4;

					if(buffer1 == CMD_FN)
					{
						// another buffer for commands that require an additional byte
						buffer3 = pgm_read_byte(&_4ml_data[data_pointer[voice]+1]);
						uint8_t la; /* cache loop index to avoid repeated loops_active[voice]-1 */

						// loop start
						if(buffer2 == CMD_FN_LOOP_START)
						{
							la = loops_active[voice]++;
							loop_point[la][voice] = data_pointer[voice] + 2;
							loop_duration[la][voice] = buffer3 - 1;
							data_pointer[voice] += 2;
						}

						// loop end
						else if(buffer2 == CMD_FN_LOOP_END)
						{
							// if we reach the end of the loop and the duration isn't 0, decrement our counter and start again
							la = loops_active[voice] - 1;
							if(loop_duration[la][voice] > 0)
							{
								data_pointer[voice] = loop_point[la][voice];
								loop_duration[la][voice]--;
							}
							else
							{
								loops_active[voice]--;
								data_pointer[voice]++;
							}
						}

						// macro
						else if(buffer2 == CMD_FN_MACRO)
						{
							uint16_t off = song_idx + (uint16_t)(buffer3 + song_voices) * 2;
							pointer_location[voice] = data_pointer[voice] + 2;
							data_pointer[voice] = (uint16_t)pgm_read_byte(&_4ml_data[off]) << 8;
							data_pointer[voice] |= pgm_read_byte(&_4ml_data[off + 1]);
						}
						// tempo
						else if(buffer2 == CMD_FN_TEMPO)
						{
							tick_speed = buffer3 << 4;
							/* // for testing tempos...
							switch (song_voices) {
								case 1:
									tick_speed = 2150; // 1 channel 60 bpm
									break;
								case 2:
									tick_speed = 725; // 2 channel 60 bpm
									break;
								case 3:
									tick_speed = 540; // 3 channel 60 bpm
									break;
							}*/
							data_pointer[voice] += 2;
						}

						// transpose (currently unused)
						else if(buffer2 == CMD_FN_TRANSPOSE) {
							data_pointer[voice] += 2; // skip data
						}

						// instrument
						else if(buffer2 == CMD_FN_INSTRUMENT) {
							instrument[voice] = buffer3;
							data_pointer[voice] += 2; // skip data
						}

						// tie command (currently unused)
						else if(buffer2 == CMD_FN_TIE) {
							data_pointer[voice]++; // skip data
						}

						// panning command (currently unused)
						else if(buffer2 == CMD_FN_PAN) {
							data_pointer[voice] += 2; // skip data
						}

						// percussion on (x command)
						else if(buffer2 == CMD_FN_PERCUSSION) {
							is_percussion[voice] = 1;
							data_pointer[voice]++;
						}

						// percussion off (x0 command)
						else if(buffer2 == CMD_FN_PERCUSSION_OFF) {
							is_percussion[voice] = 0;
							data_pointer[voice]++;
						}

						// expanded functionality command (currently unused)
						else if(buffer2 == CMD_FN_MISC) {
							data_pointer[voice] += 2; // skip data
						}

						else if(buffer2 == CMD_FN_END)
						{
							// (END OF MACRO) if we've got a previous position saved, go to it...
							if(pointer_location[voice] != 0)
							{
								data_pointer[voice] = pointer_location[voice];
								pointer_location[voice] = 0;
							}
							// (END OF CHANNEL) ...if not, go back to the start
							else
							{
								// Go to the next song in the album
								// NOTE: this happens when the shortest channel is reached,
								// so each channel needs to be padded out to the end of the song
								// or it will end early  
								return 0;

								// Old behavior to loop the channel indefinitely
								//data_pointer[voice] = pgm_read_byte(&_4ml_data[(voice*2)]) << 8;
								//data_pointer[voice] |= pgm_read_byte(&_4ml_data[(voice*2)+1]);
							}
						}

						/* For any command that should happen 'instantaneously' (e.g. anything
						 * that isn't a note or rest - in mmml notes can't be altered once
						 * they've started playing), we need to keep checking this loop until we
						 * find an event that requires waiting. */

						goto LOOP;
					}

					if(buffer1 == CMD_OCTAVE || buffer1 == CMD_VOLUME)
					{
						// octave
						if(buffer1 == CMD_OCTAVE)
							octave[voice] = 1 << buffer2;
						// volume
						if(buffer1 == CMD_VOLUME) {
							// volume can be 1-16 in 4ml (0-15 encoded) but we only have 8 choices, so divide by 2
							volume[voice] = 8 - (buffer2/2);
						}

						data_pointer[voice]++;
						goto LOOP; // see comment above previous GOTO
					}

					// note value
					if(buffer1 != CMD_REST && buffer1 < CMD_OCTAVE)
					{
						if (is_percussion[voice] == 0) {
							//buffer4 = pgm_read_word(&note[buffer1]);
							buffer4 = note[buffer1];
							frequency[voice] = buffer4;

							// calculate the waveform duty cycle by dividing the frequency by powers of 2
							waveform[voice] = buffer4 >> volume[voice];
						}
						else
						{
							// map percussion to "beep" if not otherwise in range
							if (buffer1 > 5) {
								buffer1 = 2;
							}
							// reset the sampler
							currentBit     = 0;
							currentByte    = pgm_read_byte(&sample_index[buffer1 - 1]);
							current_sample = pgm_read_byte(&sample_index[buffer1]);
						}
					
					}
					else {
						// rest
						waveform[voice] = 0;
					}

					// note / rest duration value
					// Duration is in "ticks": each tick the main loop decrements length[voice];
					// when it reaches 0 we advance to the next event. Whole note = 128 ticks
					// A value of 0 here will run for one cycle, which is the definition of a 128th note.
					if(buffer2 == 15)
					{
						// Extended duration (AVR-specific): next byte = 128th-note count.
						uint8_t ext_len = pgm_read_byte(&_4ml_data[data_pointer[voice]+1]);
						// the -1 accounts for length[voice] counting "0" as 1 128th note, "1" as 2 128th notes, etc.
						length[voice] = ext_len - 1;
						data_pointer[voice] += 2;
					}
					else
					{
						if(buffer2 < 8)
						{
							// Standard duration: nibble 0..7 = 1, 2, 4, 8, 16, 32, 64, 128.
							// length = 127 >> buffer2 => 127, 63, 31, 15, 7, 3, 1, 0.
							// Again, the oddity here is that 0 counts as the first 128th tick rather than nothingness
							// so length[voice] has all durations -1
							length[voice] = 127 >> buffer2;
						}
						else
						{
							// Dotted duration: nibble 8..13 = 2., 4., 8., 16., 32., 64.
							// "Dotted" = note + half again = 3/2 of the undotted length.
							// 2 is 64 ticks (or 64 128th notes)
							// 2. is 96 ticks (or 96 128th notes)
							// we subtract 1 to get 95 because a value of 0 counts as a 128th note also
							// Then 95 >> (buffer2&7) gives dotted quarter (47), eighth (23), etc.
							length[voice] = 95 >> (buffer2 & 7);
						}

						// next element in data
						data_pointer[voice]++;
					}
				}
				// keep waiting until the note is over
				else
					length[voice]--;
			}
		}
	}
}

/*******************************************************************************/

#ifdef DEBUG
#include <avr/io.h>

#ifndef F_CPU
#define F_CPU 8000000UL // Define CPU frequency (e.g., 8MHz)
#endif
#define BAUD 9600
#include <util/setbaud.h> // Helper to calculate UBRR values

// Function to transmit a character
int uart_putchar(char c, FILE *stream) {
    if (c == '\n') {
        uart_putchar('\r', stream); // Add carriage return for newlines
    }
    // Wait for the transmit buffer to be empty (specific register names vary by model)
    // For general ATtiny, this part must be a software serial implementation
    loop_until_bit_is_set(UCSR0A, UDRE0); 
    UDR0 = c; // Put character in transmit buffer
    return 0;
}

// Setup the standard output stream to use uart_putchar
FILE output = FDEV_SETUP_STREAM(uart_putchar, NULL, _FDEV_SETUP_WRITE);

void uart_init(void) {
    // Hardware UART init (if available, e.g., ATtiny1634)
    UBRR0H = UBRRH_VALUE;
    UBRR0L = UBRRL_VALUE;
    UCSR0C = (1 << UCSZ01) | (1 << UCSZ00); // 8-bit data
    UCSR0B = (1 << TXEN0); // Enable TX
    stdout = &output; // Redirect stdout
}
#endif

int main(void)
{
#ifdef DEBUG
    // set clock to 8mhz for atmega328p
    //CLKPR = _BV(CLKPCE);
    //CLKPR = _BV(CLKPS0);
    uart_init();
#endif

	// initialize output pin
	DDRB = 0b00000001 << OUTPUT;

	uint8_t album_idx = 0;

	//printf("Total tracks: %d\n", TOTAL_TRACKS);

	for(; album_idx < TOTAL_TRACKS; album_idx++)
	{
		play_song(TRACK_VOICES[album_idx], TRACK_OFFSET[album_idx]);
        _delay_ms(1500);
	}

	return 0;
}

