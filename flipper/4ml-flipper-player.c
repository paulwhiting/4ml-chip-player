/*H*****************************************************************************
 *  FILENAME:     4ml-flipper-player.c
 *  DESCRIPTION: 4ML Player for Flipper Zero - Ninja Gaiden with 5-voice polyphony
 *               Uses rapid interleaved voice switching like AVR player
 *****************************************************************************H*/

#include <stdint.h>
#include <stdbool.h>
#include <furi.h>
#include <furi_hal.h>
#include <furi_hal_speaker.h>
#include <gui/gui.h>
#include <gui/view_port.h>
#include <input/input.h>

#include "ninjagaiden_data.h"

// Note frequencies (octave 4, C to B) - scaled for faster lookup
static const uint16_t note_freq_scaled[] = {
    1024,  // rest
    4096, 3868, 3648, 3444, 3252, 3068, 2896, 2732, 2580, 2436, 2300, 2168
};

// Duration lookup (at tempo 45)
static const uint16_t note_ticks[] = {
    480, 240, 120, 60, 30, 15, 7, 3
};

// Voice tracking - 5 voices
#define NUM_VOICES 5
static struct {
    uint16_t ptr;
    uint8_t octave;
    uint8_t volume;
    uint8_t note;
    uint8_t duration;
    uint8_t waiting;
    uint16_t loop_stack[4][2];
    uint8_t loop_depth;
} voice[NUM_VOICES];

// Display state
static ViewPort* g_view_port = NULL;
static char g_status[32] = "Starting...";
static uint32_t g_notes_played = 0;

// Input
static bool g_stop_requested = false;

// Command definitions  
#define CMD_REST    0x00
#define CMD_OCTAVE  0x0D
#define CMD_VOLUME  0x0E
#define CMD_FN      0x0F

// Drawing callback
static void draw_callback(Canvas* canvas, void* context) {
    (void)context;
    canvas_clear(canvas);
    canvas_set_font(canvas, FontPrimary);
    canvas_draw_str(canvas, 10, 20, "Ninja Gaiden");
    canvas_set_font(canvas, FontSecondary);
    canvas_draw_str(canvas, 10, 40, g_status);
    canvas_draw_str(canvas, 10, 60, "VOICES: 5");
    canvas_draw_str(canvas, 10, 80, "Press BACK");
}

// Input callback
static void input_callback(InputEvent* event, void* context) {
    (void)context;
    if(event->key == InputKeyBack) {
        g_stop_requested = true;
    }
}

// Parse voice command at current position
static bool process_voice_command(int v) {
    if(voice[v].waiting > 0) {
        voice[v].waiting--;
        return true;
    }
    
    if(voice[v].ptr >= sizeof(_4ml_data)) {
        voice[v].note = 0;
        return true;
    }
    
    uint8_t byte = _4ml_data[voice[v].ptr++];
    uint8_t high = (byte >> 4) & 0x0F;
    uint8_t low = byte & 0x0F;
    
    // Command FN
    if(high == CMD_FN) {
        if(low == 0x00) { // Loop start
            if(voice[v].ptr < sizeof(_4ml_data) - 1) {
                voice[v].loop_stack[voice[v].loop_depth][0] = voice[v].ptr;
                voice[v].loop_stack[voice[v].loop_depth][1] = _4ml_data[voice[v].ptr];
                voice[v].loop_depth++;
                voice[v].ptr++;
            }
        } else if(low == 0x01) { // Loop end
            if(voice[v].loop_depth > 0 && voice[v].loop_stack[voice[v].loop_depth-1][1] > 0) {
                voice[v].loop_stack[voice[v].loop_depth-1][1]--;
                voice[v].ptr = voice[v].loop_stack[voice[v].loop_depth-1][0];
            } else if(voice[v].loop_depth > 0) {
                voice[v].loop_depth--;
            }
        } else if(low == 0x03) { // Tempo - skip value byte
            voice[v].ptr++;
        } else if(low == 0x0C) { // End - set rest, stop processing
            voice[v].note = 0;
        } else {
            voice[v].ptr++;
        }
        return true;
    }
    
    // Note (not command)
    if(high < CMD_OCTAVE) {
        voice[v].note = high;
        voice[v].duration = low;
        voice[v].waiting = 1;
        g_notes_played++;
        return true;
    }
    
    // Octave
    if(high == CMD_OCTAVE) {
        voice[v].octave = low + 1;
        return true;
    }
    
    // Volume
    if(high == CMD_VOLUME) {
        voice[v].volume = low + 1;
        return true;
    }
    
    return true;
}

// Play all active voices in interleaved fashion
static void play_interleaved(void) {
    // Count active voices this frame
    int active = 0;
    for(int v = 0; v < NUM_VOICES; v++) {
        if(voice[v].note > 0 && voice[v].note <= 12) active++;
    }
    
    if(active == 0) return;
    
    int voice_ms = note_ticks[2] / active; // eighth note divided
    if(voice_ms < 10) voice_ms = 10;
    if(voice_ms > 100) voice_ms = 100;
    
    // Round-robin through voices
    for(int round = 0; round < 2; round++) {
        for(int v = 0; v < NUM_VOICES; v++) {
            if(voice[v].note == 0 || voice[v].note > 12) continue;
            
            // Calculate frequency
            uint16_t freq_scaled = note_freq_scaled[voice[v].note];
            float freq = (float)freq_scaled / 4.0f;
            freq *= (1 << (voice[v].octave - 3));
            if(freq > 20000) freq = 20000;
            
            // Play very short burst
            furi_hal_speaker_start(freq, 0.5f);
            furi_delay_ms(voice_ms / 2);
            furi_hal_speaker_stop();
            
            // Process command for next note
            process_voice_command(v);
        }
        
        if(g_stop_requested) break;
    }
}

// Initialize voices from header
static void init_voices(void) {
    // Reset all
    for(int v = 0; v < NUM_VOICES; v++) {
        voice[v].ptr = 0;
        voice[v].octave = 3;
        voice[v].volume = 8;
        voice[v].note = 0;
        voice[v].duration = 0;
        voice[v].waiting = 0;
        voice[v].loop_depth = 0;
    }
    
    // Parse header for voice offsets (each is uint16_t)
    // Header: voice1_offset, voice2_offset, ..., voice5_offset
    uint16_t offsets[NUM_VOICES];
    for(int v = 0; v < NUM_VOICES; v++) {
        offsets[v] = (_4ml_data[v*2] << 8) | _4ml_data[v*2 + 1];
        voice[v].ptr = offsets[v];
    }
    
    // Skip header (first 10 bytes = 5 * uint16_t)
    for(int v = 0; v < NUM_VOICES; v++) {
        if(voice[v].ptr < 60) voice[v].ptr = 60 + v * 20;
    }
    
    g_notes_played = 0;
}

int32_t flipper_player_app(void* p) {
    (void)p;
    
    g_stop_requested = false;
    
    Gui* gui = furi_record_open(RECORD_GUI);
    if(!gui) return 0;
    
    ViewPort* view_port = view_port_alloc();
    g_view_port = view_port;
    
    view_port_draw_callback_set(view_port, draw_callback, NULL);
    view_port_input_callback_set(view_port, input_callback, NULL);
    gui_add_view_port(gui, view_port, GuiLayerFullscreen);
    
    // Initialize
    init_voices();
    snprintf(g_status, sizeof(g_status), "Playing...");
    view_port_update(view_port);
    
    // Acquire speaker
    if(!furi_hal_speaker_acquire(1000)) {
        snprintf(g_status, sizeof(g_status), "Speaker busy!");
        view_port_update(view_port);
    } else {
        // Main playback loop
        uint32_t idle_count = 0;
        while(!g_stop_requested && idle_count < 100) {
            // Check if any voice has active notes
            int active = 0;
            for(int v = 0; v < NUM_VOICES; v++) {
                if(voice[v].note > 0 && voice[v].note <= 12) active++;
            }
            
            if(active > 0) {
                play_interleaved();
                idle_count = 0;
            } else {
                idle_count++;
                furi_delay_ms(10);
            }
            
            // Update display periodically
            if(g_notes_played % 50 == 0 && g_notes_played > 0) {
                snprintf(g_status, sizeof(g_status), "Notes: %lu", g_notes_played);
                view_port_update(view_port);
            }
        }
        
        furi_hal_speaker_stop();
        furi_hal_speaker_release();
    }
    
    snprintf(g_status, sizeof(g_status), "Done! Notes: %lu", g_notes_played);
    view_port_update(view_port);
    furi_delay_ms(1000);
    
    gui_remove_view_port(gui, view_port);
    view_port_free(view_port);
    furi_record_close(RECORD_GUI);
    
    return 0;
}

int main(int argc, char** argv) {
    (void)argc;
    (void)argv;
    return flipper_player_app(NULL);
}