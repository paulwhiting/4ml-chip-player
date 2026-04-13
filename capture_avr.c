#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <simavr/sim_avr.h>
#include <simavr/sim_elf.h>
#include <simavr/sim_io.h>

#define SAMPLE_RATE 44100
#define SAMPLE_INTERVAL_NS (1000000000ULL / SAMPLE_RATE)
#define OUTPUT_PIN 3
#define PORTB_ADDR 0x05

static void custom_sleep(struct avr_t * avr, avr_cycle_count_t howLong) {
}

int main(int argc, char *argv[])
{
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <firmware.elf>\n", argv[0]);
        return 1;
    }

    const char *firmware_path = argv[1];

    elf_firmware_t firmware;
    if (elf_read_firmware(firmware_path, &firmware) < 0) {
        fprintf(stderr, "Error loading firmware: %s\n", firmware_path);
        return 1;
    }

    const char *mmcu = firmware.mmcu[0] ? firmware.mmcu : "atmega328p";

    avr_t *avr = avr_make_mcu_by_name(mmcu);
    if (!avr) {
        fprintf(stderr, "Error creating AVR instance\n");
        return 1;
    }

    avr_init(avr);
    avr_load_firmware(avr, &firmware);

    if (firmware.frequency > 0) {
        avr->frequency = firmware.frequency;
    } else {
        avr->frequency = 16000000;
    }

    avr->sleep = custom_sleep;
    if (!avr->run) {
        avr->run = avr_callback_run_raw;
    }

    avr->pc = 0;

    uint64_t last_sample_time = 0;
    uint8_t last_pin_state = 0;
    uint32_t total_samples = 0;

    while (1) {
        avr_run(avr);
        uint64_t now = avr_get_time_stamp(avr);
        
        if (avr->state == cpu_Done || avr->state == cpu_Crashed) {
            break;
        }
        
        while (now - last_sample_time >= SAMPLE_INTERVAL_NS) {
            uint8_t portb = avr->data[PORTB_ADDR];
            uint8_t pin_state = (portb >> OUTPUT_PIN) & 1;
            uint8_t sample = pin_state ? 255 : 0;
            fwrite(&sample, 1, 1, stdout);
            last_sample_time += SAMPLE_INTERVAL_NS;
            last_pin_state = pin_state;
            total_samples++;
        }
    }

    uint64_t final_time = avr_get_time_stamp(avr);
    while (last_sample_time + SAMPLE_INTERVAL_NS <= final_time) {
        uint8_t sample = last_pin_state ? 255 : 0;
        fwrite(&sample, 1, 1, stdout);
        last_sample_time += SAMPLE_INTERVAL_NS;
        total_samples++;
    }

    return 0;
}