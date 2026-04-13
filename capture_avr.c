#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <stdarg.h>
#include <simavr/sim_avr.h>
#include <simavr/sim_elf.h>
#include <simavr/sim_io.h>
#include <simavr/sim_time.h>
#include <simavr/sim_cycle_timers.h>

#define OUTPUT_PIN 3
#define PORTB_ADDR 0x25
#define SAMPLE_RATE 44100
#define SAMPLE_INTERVAL_USEC 23

static void custom_sleep(struct avr_t * avr, avr_cycle_count_t howLong) {
}

static void quiet_logger(struct avr_t *avr, int level, const char * format, va_list ap) {
    if (strstr(format, "Loaded") != NULL) return;
    if (strstr(format, "Starting ") != NULL) return;
    if (strstr(format, "init") != NULL) return;
    if (strstr(format, "reset") != NULL) return;
    vfprintf(stderr, format, ap);
}

uint32_t get_exit_address(const char *elf_path) {
    char cmd[512];
    snprintf(cmd, sizeof(cmd), "avr-nm \"%s\" 2>/dev/null | grep ' T _exit' | awk '{print $1}'", elf_path);
    
    FILE *fp = popen(cmd, "r");
    if (!fp) return 0;
    
    uint32_t addr = 0;
    char buf[32];
    if (fgets(buf, sizeof(buf), fp)) {
        addr = strtoul(buf, NULL, 16);
    }
    pclose(fp);
    
    return addr;
}

typedef struct {
    avr_t *avr;
    uint32_t exit_addr;
    uint8_t last_pin_state;
    uint32_t total_samples;
    int done;
} capture_data_t;

static avr_cycle_count_t sample_timer(
    struct avr_t * avr,
    avr_cycle_count_t when,
    void * param)
{
    capture_data_t *data = (capture_data_t *)param;
    
    uint8_t portb = avr->data[PORTB_ADDR];
    uint8_t pin_state = (portb >> OUTPUT_PIN) & 1;
    uint8_t sample = pin_state ? 255 : 0;
    fwrite(&sample, 1, 1, stdout);
    data->last_pin_state = pin_state;
    data->total_samples++;
    
    static int debug_count = 0;
    if (debug_count++ % 1000 == 0) {
        fprintf(stderr, "SAMPLE: pin=%d samples=%u cycles=%u\n", 
                pin_state, data->total_samples, (unsigned)when);
    }
    
    if (avr->pc >= data->exit_addr && avr->pc <= data->exit_addr + 10) {
        fprintf(stderr, "EXIT detected at PC=%u\n", avr->pc);
        data->done = 1;
        return 0;
    }
    
    return when + avr_usec_to_cycles(avr, SAMPLE_INTERVAL_USEC);
}

int main(int argc, char *argv[])
{
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <firmware.elf>\n", argv[0]);
        return 1;
    }

    const char *firmware_path = argv[1];

    avr_global_logger_set(quiet_logger);

    uint32_t exit_addr = get_exit_address(firmware_path);
    if (!exit_addr) {
        fprintf(stderr, "Error: Could not find _exit address in ELF\n");
        return 1;
    }
    fprintf(stderr, "Exit address: %u\n", exit_addr);

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

    capture_data_t data = {
        .avr = avr,
        .exit_addr = exit_addr,
        .last_pin_state = 0,
        .total_samples = 0,
        .done = 0
    };

    avr_cycle_count_t first_timer = avr->cycle + avr_usec_to_cycles(avr, SAMPLE_INTERVAL_USEC);
    avr_cycle_timer_register(avr, first_timer, sample_timer, &data);

    while (!data.done) {
        avr_run(avr);
    }

    fprintf(stderr, "Done: %u samples captured\n", data.total_samples);
    return 0;
}