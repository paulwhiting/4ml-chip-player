
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

#include <stdint.h>

// differential drive
#define USE_COMPLEMENTARY_OUTPUT 1

/*
 * --------------------------------------------------------------------------
 * Platform selection
 * --------------------------------------------------------------------------
 *
 * Define STM32C011 when compiling for the STM32.
 *
 * Otherwise the original AVR implementation is used.
 */

#if defined(STM32C011)
	#include "stm32c011xx.h"

	#define CPU_CLOCK_HZ 12000000UL

    /*
     * STM32C011J6M6
     *
     * Physical pin 5 = PA8 = TIM1_CH1
     */

    #define OUTPUT 0

    /*
	 * We use PA8 as a normal GPIO output for the 1-bit synthesizer.
     *
     * This is intentional: the 4ML engine produces a rapidly changing
     * 1-bit waveform. We are NOT converting the three voices into
     * independent hardware PWM channels.
     */

/*
    #define RCC_BASE        0x40021000UL
    #define RCC_IOPENR      (*(volatile uint32_t *)(RCC_BASE + 0x34))
	#define RCC_APBENR2     (*(volatile uint32_t *)(RCC_BASE + 0x40UL))

    #define RCC_IOPENR_GPIOAEN    (1UL << 0)
	#define RCC_APBENR2_SYSCFGEN  (1UL << 0)

    #define GPIOA->BASE      0x50000000UL
    #define GPIOA->MODER     (*(volatile uint32_t *)(GPIOA->BASE + 0x00))
    // ?? #define GPIOA->ODR       (*(volatile uint32_t *)(GPIOA->BASE + 0x14))
	#define GPIOA->BSRR      (*(volatile uint32_t *)(GPIOA->BASE + 0x18UL))


	//#define BUTTON_PIN    (1UL << 12)	// PA12 mapped to physical pin 6

	#define SYSCFG_BASE     0x40010000UL
	#define SYSCFG_CFGR3    (*(volatile uint32_t *)(SYSCFG_BASE + 0x3CUL))

	#define GPIOA->PUPDR     (*(volatile uint32_t *)(GPIOA->BASE + 0x0CUL))
	#define GPIOA->IDR       (*(volatile uint32_t *)(GPIOA->BASE + 0x10UL))
*/

	#define GPIOA_PIN0    (1UL << 0)   	// PA4 - physical pin 4
	#define GPIOA_PIN8    (1UL << 8)   	// PA5 - physical pin 5


////////////////////////////////////////
////// SWITCH CODE
//////

// STM32C011J6M6
// Physical pin 6 = PA12
// Button connected between PA12 and GND
// Button is active-low
//
// Behavior:
//   Falling edge -> start press debounce
//   Press confirmed -> wait for release
//   Rising edge -> immediately generate button event
//   After release -> debounce/lockout for 20 ms
//   After debounce -> ready for next press

#define BUTTON_PIN       12U
#define BUTTON_MASK      (1UL << BUTTON_PIN)
#define DEBOUNCE_MS      20U

enum
{
    BUTTON_WAITING = 0,
    BUTTON_DEBOUNCE_PRESS,
    BUTTON_PRESSED,
    BUTTON_DEBOUNCE_RELEASE
};

static volatile uint8_t button_state = BUTTON_WAITING;
static volatile uint8_t button_timer = 0;
static volatile uint8_t button_pressed = 0;


// Called immediately when the button is released.
// No debounce delay is added before this function is called.
static void button_pressed_event(void)
{
	// Handle button event here.
	button_pressed = 1;
}


// Initialize PA12 and EXTI12.
static void switch_init(void)
{
    // Enable GPIOA clock
    RCC->IOPENR |= RCC_IOPENR_GPIOAEN;

    // Enable SYSCFG clock
    RCC->APBENR2 |= RCC_APBENR2_SYSCFGEN;

    // PA12 = input
    GPIOA->MODER &= ~(3UL << (BUTTON_PIN * 2));

    // PA12 = pull-up
    GPIOA->PUPDR &= ~(3UL << (BUTTON_PIN * 2));
    GPIOA->PUPDR |=  (1UL << (BUTTON_PIN * 2));

    // EXTI12 source = PA12
    // EXTI12 is in EXTICR4.
    // Port A has selection value 0, so clear the field.
    EXTI->EXTICR[3] &= ~(0xFUL << 0);

    // Initially detect only falling edges.
    // Falling edge = button pressed.
    EXTI->RTSR1 &= ~BUTTON_MASK;
    EXTI->FTSR1 |=  BUTTON_MASK;

    // Clear any stale pending flags.
    EXTI->RPR1 = BUTTON_MASK;
    EXTI->FPR1 = BUTTON_MASK;

    // Enable EXTI12 interrupt.
    EXTI->IMR1 |= BUTTON_MASK;

    // EXTI4..15 share this interrupt vector.
    NVIC_EnableIRQ(EXTI4_15_IRQn);
}


// Initialize SysTick for a 1 ms interrupt.
static volatile uint32_t systick_ms = 0;

static void systick_init(void)
{
    SysTick->LOAD = (CPU_CLOCK_HZ / 1000UL) - 1UL;
    SysTick->VAL  = 0UL;

    SysTick->CTRL =
        SysTick_CTRL_CLKSOURCE_Msk |
        SysTick_CTRL_TICKINT_Msk   |
        SysTick_CTRL_ENABLE_Msk;
}

// EXTI4..15 interrupt handler.
void EXTI4_15_IRQHandler(void)
{
    uint32_t rising_pending;
    uint32_t falling_pending;

    rising_pending  = EXTI->RPR1;
    falling_pending = EXTI->FPR1;

    // Clear pending flags.
    EXTI->RPR1 = rising_pending;
    EXTI->FPR1 = falling_pending;

    // Falling edge = button pressed.
    if (falling_pending & BUTTON_MASK)
    {
        if (button_state == BUTTON_WAITING)
        {
            // Start press debounce.
            button_state = BUTTON_DEBOUNCE_PRESS;
            button_timer = DEBOUNCE_MS;

            // Ignore further falling edges while debouncing.
            EXTI->FTSR1 &= ~BUTTON_MASK;
        }
    }

    // Rising edge = button released.
    if (rising_pending & BUTTON_MASK)
    {
        if (button_state == BUTTON_PRESSED)
        {
            // The button has just been released.
            //
            // Generate the event immediately.
            button_pressed_event();

            // Now enter release debounce/lockout.
            button_state = BUTTON_DEBOUNCE_RELEASE;
            button_timer = DEBOUNCE_MS;

            // Ignore further rising edges during debounce.
            EXTI->RTSR1 &= ~BUTTON_MASK;
        }
    }
}

void SysTick_Handler(void)
{
    systick_ms++;

    if (button_timer == 0U)
        return;

    button_timer--;

    if (button_timer != 0U)
        return;

    switch (button_state)
    {
        case BUTTON_DEBOUNCE_PRESS:
            if ((GPIOA->IDR & BUTTON_MASK) == 0U)
            {
                button_state = BUTTON_PRESSED;

                // Clear any stale rising-edge pending flag
                EXTI->RPR1 = BUTTON_MASK;

                // Now allow rising edges (button release)
                EXTI->RTSR1 |= BUTTON_MASK;
            }
            else
            {
                // Button bounced back to released
                button_state = BUTTON_WAITING;

                // Clear any stale falling-edge pending flag
                EXTI->FPR1 = BUTTON_MASK;

                // Continue waiting for a press
                EXTI->FTSR1 |= BUTTON_MASK;
            }
            break;

        case BUTTON_DEBOUNCE_RELEASE:
            if ((GPIOA->IDR & BUTTON_MASK) != 0U)
            {
                button_state = BUTTON_WAITING;

                // Clear any stale falling-edge pending flag
                EXTI->FPR1 = BUTTON_MASK;

                // Now allow falling edges (button press)
                EXTI->FTSR1 |= BUTTON_MASK;
            }
            else
            {
                // Button bounced back to pressed
                button_state = BUTTON_PRESSED;

                // Clear any stale rising-edge pending flag
                EXTI->RPR1 = BUTTON_MASK;

                // Continue waiting for release
                EXTI->RTSR1 |= BUTTON_MASK;
            }
            break;

        default:
            button_state = BUTTON_WAITING;
            button_timer = 0U;

            // Clear any stale falling-edge pending flag
            EXTI->FPR1 = BUTTON_MASK;

            EXTI->FTSR1 |= BUTTON_MASK;
            break;
    }
}


/*
	static void switch_init(void)
	{
		// GPIOA clock
		RCC->IOPENR |= RCC_IOPENR_GPIOAEN;

		// PA5 = input
		// MODER[11:10] = 00
		GPIOA->MODER &= ~(3UL << (12 * 2));

		// PA5 = pull-up
		// PUPDR[11:10] = 01
		GPIOA->PUPDR &= ~(3UL << (12 * 2));
		GPIOA->PUPDR |=  (1UL << (12 * 2));
	}
*/

	static int switch_pressed(void)
	{
		return (GPIOA->IDR & BUTTON_MASK) == 0;
	}


    static inline void audio_init(void)
    {
        // Enable GPIOA
		RCC->IOPENR |= RCC_IOPENR_GPIOAEN;

		// Enable SYSCFG clock
		RCC->APBENR2 |= RCC_APBENR2_SYSCFGEN;

		/*
		* STM32C011 SO8 physical pin 4:
		*
		* PINMUX1[1:0]
		*
		* 00 = PF2-NRST
		* 01 = PA0
		* 10 = PA1
		* 11 = PA2
		*
		* Select PA0.
		*/
		SYSCFG->CFGR3 &= ~(3UL << 2);
		SYSCFG->CFGR3 |=  (1UL << 2);

		// PA8 = output
		GPIOA->MODER &= ~(3UL << 16);
		GPIOA->MODER |=  (1UL << 16);

		// PA0 = output
		GPIOA->MODER &= ~(3UL << 0);
		GPIOA->MODER |=  (1UL << 0);

		/* Start with both low */
		GPIOA->BSRR = (GPIOA_PIN8 << 16) |
					 (GPIOA_PIN0 << 16);
    }


    static inline void audio_write(uint8_t value)
    {
#ifdef USE_COMPLEMENTARY_OUTPUT
		if (value)
		{
			// Pin 5 PA8 = HIGH, pin 4 PA0 = LOW
			GPIOA->BSRR = GPIOA_PIN8 |
						 (GPIOA_PIN0 << 16);
		}
		else
		{
			// Pin 5 PA8 = LOW, pin 4 PA0 = HIGH
			GPIOA->BSRR = (GPIOA_PIN8 << 16) |
						 GPIOA_PIN0;
		}
#else
		// Pin 5 PA8 = audio, Pin 4 PA0 remains LOW
		if (value)
			GPIOA->BSRR = GPIOA_PIN8;
		else
			GPIOA->BSRR = GPIOA_PIN8 << 16;
#endif
    }

	static void stm32_delay_ms(uint32_t ms)
	{
	    uint32_t start = systick_ms;

	    while ((uint32_t)(systick_ms - start) < ms)
	    {
		/* wait */
	    }
	}

	#define _delay_ms(ms) stm32_delay_ms((uint32_t)(ms))


    /*
     * STM32 has no AVR PROGMEM.
     *
     * Data lives in normal flash, which the Cortex-M can read directly.
     */
    #define READ8(p)        (*(const uint8_t *)(p))
    #define READ16(p)       (*(const uint16_t *)(p))
	#define AVR_PROGMEM

#else

    /*
     * Original AVR implementation.
     */

    #include <avr/io.h>         // core avr functionality
    #include <avr/pgmspace.h>   // * * *

	#include <util/delay.h>


    // stuff you can mess with
    //#define OUTPUT 0
    #define OUTPUT         3    // the PORTB hardware output pin

	// initialize output pin
    #define audio_init() \
        do { DDRB = (uint8_t)(1U << OUTPUT); } while (0)

    #define audio_write(value) \
        do { PORTB = (value); } while (0)

    #define READ8(p)        pgm_read_byte((p))
    #define READ16(p)       pgm_read_word((p))

	#define AVR_PROGMEM PROGMEM

#endif


#include "4ml-data.h"       // holds the _4ml_data[] arrays

#ifdef DEBUG
#include <stdio.h>
#endif

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
const uint16_t note[13] = 
{
	// the rest command is technically note 0 and thus requires a frequency 
	255,
	// one octave of notes, equal temperament in Gb (multiplied by 4)
	4096,3868,3648,3444,3252,3068,2896,2732,2580,2436,2300,2168
};

// location of individual samples in sample array
const uint8_t sample_index[6] AVR_PROGMEM =
{
	0,19,34,74,118,126
};

// raw PWM sample data
const uint8_t sample[SAMPLE_LENGTH] AVR_PROGMEM =
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
		data_pointer[i] = READ8(_4ml_data + ((i*2)+song_idx));
		data_pointer[i] = data_pointer[i] << 8;
		data_pointer[i] = data_pointer[i] | READ8(&_4ml_data[(i*2)+1+song_idx]);

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

	while(!button_pressed)
	{
		/**********************
		 *  Synthesizer Code  *
		 **********************/

		/* Port changes (the demarcated 'output' commands) are carefully interleaved with
		 * generation code to balance volume of outputs. */

        /* One branch per voice: out = (pitch_counter < waveform) ? high : 0 */
        for(uint8_t voice = 0; voice < song_voices; voice++) {
			if (is_percussion[voice] == 0) {
				audio_write(out[voice]);
				pitch_counter[voice] += octave[voice];
				if(pitch_counter[voice] >= frequency[voice])
					pitch_counter[voice] -= frequency[voice];
				out[voice] = (pitch_counter[voice] < waveform[voice]) ? (1 << OUTPUT) : 0;
			}

			else if(sample_counter-- == 0)
			{
				audio_write(out[voice]);
				if(currentByte < current_sample - 1)
				{
					// read individual bits from the sample array
					out[voice] = ((READ8(&sample[currentByte]) >> currentBit++) & 1) << OUTPUT;
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
		audio_write(0);


		/**************************
		 *  Data Processing Code  *
		 **************************/

		if(tick_counter-- == 0)
		{
			// variable tempo, sets the fastest / smallest possible clock event
			tick_counter = tick_speed - 175;

			for(uint8_t voice = 0; voice < song_voices; voice++)
			{
				// if the note ended, start processing the next byte of data
				if(length[voice] == 0)
				{
					LOOP: // yup, a goto, I know

					// single PROGMEM read for both nibbles
					buffer1 = READ8(&_4ml_data[data_pointer[voice]]);
					buffer2 = buffer1 & 15;
					buffer1 = buffer1 >> 4;

					if(buffer1 == CMD_FN)
					{
						// another buffer for commands that require an additional byte
						buffer3 = READ8(&_4ml_data[data_pointer[voice]+1]);
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
							data_pointer[voice] = (uint16_t)READ8(&_4ml_data[off]) << 8;
							data_pointer[voice] |= READ8(&_4ml_data[off + 1]);
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
								//data_pointer[voice] = READ8(&_4ml_data[(voice*2)]) << 8;
								//data_pointer[voice] |= READ8(&_4ml_data[(voice*2)+1]);
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
							//buffer4 = READ16(&note[buffer1]);
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
							currentByte    = READ8(&sample_index[buffer1 - 1]);
							current_sample = READ8(&sample_index[buffer1]);
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
						uint8_t ext_len = READ8(&_4ml_data[data_pointer[voice]+1]);
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

	button_pressed = 0;

	return 0;
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

void uart_init_for_AT(void) {
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
	uint8_t album_idx = 0;

	// initialize the switch
	switch_init();

	// initilize systick
	systick_init();

	// initialize output pin
	audio_init();

	//while(!switch_pressed()) {
        //_delay_ms(50);
	//}

	//printf("Total tracks: %d\n", TOTAL_TRACKS);

	while(1) {
		for(album_idx = 0; album_idx < TOTAL_TRACKS; album_idx++)
		{
			play_song(TRACK_VOICES[album_idx], TRACK_OFFSET[album_idx]);
			_delay_ms(1500);
		}
	}

	return 0;
}

