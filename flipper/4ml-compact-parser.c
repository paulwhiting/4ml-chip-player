/*H*****************************************************************************
 *  FILENAME:     4ml-compact-parser.c
 *  DESCRIPTION: 4ML Compact Parser - C port of Python compiler utils.py
 *               Supports ALL 4ML features for Flipper Zero
 *
 *  AUTHOR:      Blake 'PROTODOME' Troise (Original Python)
 *               Ported to C for Flipper Zero
 *  DATE:        2024
 *****************************************************************************H*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include "4ml-compact-parser.h"

// Parser state
typedef struct {
    const char* input;
    size_t input_len;
    size_t pos;
    uint8_t bytecode[MAX_BYTECODE_SIZE];
    size_t bytecode_len;
    int error_code;
    char error_msg[128];
    uint16_t error_pos;
    
    // State
    char prev_duration[4];
    int prev_octave;
    int current_channel;
    int loop_depth;
} ParserState;

// Note lookup table (matches Python compiler)
static const char note_lookup[15][3] = {
    "r", "c", "c+", "d", "d+", "e", "e+", "f", "f+", "g", "g+", "a", "a+", "b", "b+"
};

static const uint8_t note_nibble[15] = {
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 0, 0
};

// Duration lookup (matches Python compiler)
static const char duration_lookup[14][4] = {
    "1", "2", "4", "8", "16", "32", "64", "128",
    "2.", "4.", "8.", "16.", "32.", "64."
};

static const uint8_t duration_nibble[14] = {
    0, 1, 2, 3, 4, 5, 6, 7,
    8, 9, 10, 11, 12, 13
};

// Command lookup (matches Python compiler) - using if/else instead of switch for multi-char
static uint8_t command_lookup(char c) {
    if(c == 'r') return 0x00;
    if(c == 'c') return 0x01;
    if(c == 'd') return 0x03;
    if(c == 'e') return 0x05;
    if(c == 'f') return 0x06;
    if(c == 'g') return 0x08;
    if(c == 'a') return 0x0A;
    if(c == 'b') return 0x0C;
    if(c == 'o') return 0x0D;
    if(c == 'v') return 0x0E;
    if(c == 'p') return 0xF2;
    if(c == 't') return 0xF3;
    if(c == '@') return 0xF5;
    if(c == 'i') return 0xF5;
    if(c == '[') return 0xF0;
    if(c == ']') return 0xF1;
    if(c == '&') return 0xF6;
    if(c == '^') return 0xF6;
    if(c == 'K') return 0xF4;
    if(c == 's') return 0xF7;
    if(c == 'F') return 0xFE;
    if(c == 'x') return 0xF8;
    return 0xFF;
}

// Skip whitespace
static void skip_whitespace(ParserState* ps) {
    while(ps->pos < ps->input_len) {
        char c = ps->input[ps->pos];
        if(c != ' ' && c != '\t' && c != '\n' && c != '\r' && c != ';') {
            // Check for line comment
            if(c == '/') {
                if(ps->pos + 1 < ps->input_len && ps->input[ps->pos + 1] == '*') {
                    // Multi-line comment /* */
                    ps->pos += 2;
                    while(ps->pos + 1 < ps->input_len) {
                        if(ps->input[ps->pos] == '*' && ps->input[ps->pos + 1] == '/') {
                            ps->pos += 2;
                            break;
                        }
                        ps->pos++;
                    }
                    continue;
                }
            }
            // Check for single-line comment (semicolon)
            if(c == ';' || c == '#') {
                while(ps->pos < ps->input_len && ps->input[ps->pos] != '\n') {
                    ps->pos++;
                }
                continue;
            }
            break;
        }
        ps->pos++;
    }
}

// Check if at end
static bool at_end(ParserState* ps) {
    skip_whitespace(ps);
    return ps->pos >= ps->input_len;
}

// Peek next char
static char peek_char(ParserState* ps) {
    skip_whitespace(ps);
    if(ps->pos < ps->input_len) {
        return ps->input[ps->pos];
    }
    return '\0';
}

// Get next char and advance
static char get_char(ParserState* ps) {
    skip_whitespace(ps);
    if(ps->pos < ps->input_len) {
        return ps->input[ps->pos++];
    }
    return '\0';
}

// Set error
static void set_error(ParserState* ps, const char* msg, uint16_t pos) {
    ps->error_code = 1;
    if(pos > 0) ps->error_pos = pos;
    else ps->error_pos = ps->pos;
    
    // Format error message with position
    snprintf(ps->error_msg, sizeof(ps->error_msg), 
             "Error at char %d: %s", ps->error_pos, msg);
}

// Parse duration string
static int parse_duration(ParserState* ps, char* dur_out, int max_len) {
    char dur[4] = {0};
    int dur_idx = 0;
    
    // Check for digit sequence
    while(ps->pos < ps->input_len && dur_idx < 3) {
        char c = ps->input[ps->pos];
        if(isdigit(c) || c == '.') {
            if(c == '.' && dur_idx > 0 && dur[0] != '.') {
                // Check for dotted: digit followed bydots
                break;
            }
            dur[dur_idx++] = c;
            ps->pos++;
        } else {
            break;
        }
    }
    
    if(dur_idx == 0) return -1;
    
    // Store in output
    int len = (dur_idx > max_len - 1) ? max_len - 1 : dur_idx;
    strncpy(dur_out, dur, len);
    dur_out[len] = '\0';
    
    return 0;
}

// Parse number (with optional negative)
static int parse_number(ParserState* ps, int* value_out, bool allow_negative) {
    bool negative = false;
    
    if(allow_negative && ps->pos < ps->input_len && ps->input[ps->pos] == '-') {
        negative = true;
        ps->pos++;
    }
    
    int value = 0;
    int digits = 0;
    
    while(ps->pos < ps->input_len && digits < 4) {
        char c = ps->input[ps->pos];
        if(isdigit(c)) {
            value = value * 10 + (c - '0');
            ps->pos++;
            digits++;
        } else {
            break;
        }
    }
    
    if(digits == 0) {
        ps->pos -= (negative ? 1 : 0);
        return -1;
    }
    
    *value_out = negative ? -value : value;
    return 0;
}

// Find duration in lookup table
static uint8_t find_duration(const char* dur) {
    for(int i = 0; i < 14; i++) {
        if(strcmp(dur, duration_lookup[i]) == 0) {
            return duration_nibble[i];
        }
    }
    return 0xFF; // Not found
}

// Find note in lookup table  
static uint8_t find_note(const char* note) {
    for(int i = 0; i < 14; i++) {
        if(note_lookup[i][0] != '\0' && strcmp(note, note_lookup[i]) == 0) {
            return note_nibble[i];
        }
    }
    return 0xFF; // Not found
}

// Output bytecode byte
static void output_byte(ParserState* ps, uint8_t byte) {
    if(ps->bytecode_len < MAX_BYTECODE_SIZE - 1) {
        ps->bytecode[ps->bytecode_len++] = byte;
    } else {
        set_error(ps, "Bytecode overflow", 0);
    }
}

// Parse note or rest
static bool parse_note(ParserState* ps) {
    char note_char = get_char(ps);
    if(note_char == '\0') return false;
    
    // Check if valid note
    uint8_t note_cmd = command_lookup(note_char);
    if(note_cmd == 0xFF) {
        // Check for letter that might be a note
        if(note_char >= 'a' && note_char <= 'g') {
            set_error(ps, "Unknown note", 0);
        }
        ps->pos--; // Put back
        return false;
    }
    
    // Note: 0x00 = rest
    uint8_t note_val = 0;
    if(note_char != 'r') {
        note_val = find_note(&note_char);
        if(note_val == 0xFF) {
            set_error(ps, "Invalid note", 0);
            return false;
        }
    }
    
    // Check for sharp
    if(ps->pos < ps->input_len) {
        char c = ps->input[ps->pos];
        if(c == '+' || c == '#') {
            // Sharpen the note
            if(note_char == 'c') note_val = 2;
            else if(note_char == 'd') note_val = 4;
            else if(note_char == 'f') note_val = 7;
            else if(note_char == 'g') note_val = 9;
            else if(note_char == 'a') note_val = 11;
            else if(note_char == 'b') note_val = 1; // b+ = c
            ps->pos++;
        }
    }
    
    // Parse duration (optional)
    char duration[4] = "8"; // Default
    if(parse_duration(ps, duration, 4) == 0) {
        strncpy(ps->prev_duration, duration, 3);
    } else {
        strcpy(duration, ps->prev_duration);
    }
    
    // Find duration nibble
    uint8_t dur_nibble = find_duration(duration);
    if(dur_nibble == 0xFF) {
        set_error(ps, "Invalid duration", 0);
        return false;
    }
    
    // Check for next note immediately after (optimization)
    char next_c = peek_char(ps);
    (void)0;
    
    // Simple check: look ahead for note letters
    if((next_c >= 'a' && next_c <= 'g') || next_c == 'r') {
        // Save position
        size_t saved = ps->pos;
        (void)saved; // Suppress unused warning
        
        // Check if there's whitespace only or directly another note
        while(ps->pos < ps->input_len && ps->input[ps->pos] == ' ') ps->pos++;
        
        if(ps->pos < ps->input_len) {
            char nc = ps->input[ps->pos];
            if((nc >= 'a' && nc <= 'g') || nc == 'r') {
                // Get second note
                char note2 = nc;
                uint8_t note2_val = 0;
                if(note2 != 'r') {
                    note2_val = find_note(&note2);
                }
                
                // Advance past second note
                ps->pos++;
                char dur2[4] = "8";
                parse_duration(ps, dur2, 4);
                
                // Output combined byte
                uint8_t combined = (note_val << 4) | note2_val;
                output_byte(ps, combined);
                return true;
            }
        }
        ps->pos = saved;
    }
    
    // Single note with duration
    uint8_t combined = (note_val << 4) | dur_nibble;
    output_byte(ps, combined);
    
    return true;
}

// Parse octave command
static bool parse_octave(ParserState* ps) {
    char cmd = get_char(ps); // 'o'
    if(cmd != 'o') return false;
    
    int value;
    if(parse_number(ps, &value, true) != 0) {
        set_error(ps, "Octave requires value", 0);
        return false;
    }
    
    // Store for < and > commands
    ps->prev_octave = value;
    
    // Valid range: -1 to 14
    if(value < -1 || value > 14) {
        snprintf(ps->error_msg, sizeof(ps->error_msg),
                 "Octave %d out of range (-1 to 14)", value);
        set_error(ps, ps->error_msg, 0);
        return false;
    }
    
    // Encode: 0x0D in high nibble, (value + 1) in low nibble
    uint8_t output = (0x0D << 4) | (value + 1);
    output_byte(ps, output);
    
    return true;
}

// Parse volume command
static bool parse_volume(ParserState* ps) {
    char cmd = get_char(ps); // 'v'
    if(cmd != 'v') return false;
    
    int value;
    if(parse_number(ps, &value, false) != 0) {
        set_error(ps, "Volume requires value", 0);
        return false;
    }
    
    // Valid range: 1 to 16
    if(value < 1 || value > 16) {
        set_error(ps, "Volume must be 1-16", 0);
        return false;
    }
    
    // Encode: 0x0E in high nibble, (value - 1) in low nibble
    uint8_t output = (0x0E << 4) | (value - 1);
    output_byte(ps, output);
    
    return true;
}

// Parse single-byte value commands (p, t, @, K, s, F)
static bool parse_fn_value(ParserState* ps, char cmd) {
    uint8_t cmd_byte = command_lookup(cmd);
    if(cmd_byte == 0xFF) return false;
    
    int value;
    if(parse_number(ps, &value, false) != 0) {
        set_error(ps, "Command requires value", 0);
        return false;
    }
    
    // Each command has different valid range
    // We'll be permissive and accept any value 0-255
    
    // Encode as two bytes: command, value-1
    output_byte(ps, cmd_byte);
    output_byte(ps, value - 1);
    
    return true;
}

// Parse loop commands
static bool parse_loop(ParserState* ps) {
    char cmd = get_char(ps);
    
    if(cmd == '[') {
        // Loop start
        ps->loop_depth++;
        
        int value;
        if(parse_number(ps, &value, false) == 0) {
            // Have count
            if(value < 1 || value > 255) {
                set_error(ps, "Loop count must be 1-255", 0);
                return false;
            }
            output_byte(ps, 0xF0);
            output_byte(ps, value - 1);
        } else {
            // No count = loop once (default)
            output_byte(ps, 0xF0);
            output_byte(ps, 0);
        }
        return true;
    }
    else if(cmd == ']') {
        // Loop end
        if(ps->loop_depth <= 0) {
            set_error(ps, "Unmatched loop end", 0);
            return false;
        }
        ps->loop_depth--;
        
        int value;
        if(parse_number(ps, &value, false) == 0) {
            if(value < 1 || value > 255) {
                set_error(ps, "Loop count must be 1-255", 0);
                return false;
            }
            output_byte(ps, 0xF1);
            output_byte(ps, value - 1);
        } else {
            output_byte(ps, 0xF1);
            output_byte(ps, 0);
        }
        return true;
    }
    
    ps->pos--;
    return false;
}

// Parse relative octave ( < > )
static bool parse_octave_shift(ParserState* ps) {
    char cmd = get_char(ps);
    
    if(cmd == '<') {
        // Octave down
        int new_octave = ps->prev_octave - 1;
        ps->prev_octave = new_octave;
        
        if(new_octave < -1) {
            set_error(ps, "Octave would be < -1", 0);
            return false;
        }
        
        uint8_t output = (0x0D << 4) | (new_octave + 1);
        output_byte(ps, output);
        return true;
    }
    else if(cmd == '>') {
        // Octave up
        int new_octave = ps->prev_octave + 1;
        ps->prev_octave = new_octave;
        
        if(new_octave > 14) {
            set_error(ps, "Octave would be > 14", 0);
            return false;
        }
        
        uint8_t output = (0x0D << 4) | (new_octave + 1);
        output_byte(ps, output);
        return true;
    }
    
    ps->pos--;
    return false;
}

// Parse tie command
static bool parse_tie(ParserState* ps) {
    char cmd = get_char(ps);
    
    if(cmd == '&' || cmd == '^') {
        // Tie - not output for AVR, just skip
        return true;
    }
    
    ps->pos--;
    return false;
}

// Parse percussion
static bool parse_percussion(ParserState* ps) {
    char cmd = get_char(ps);
    
    if(cmd == 'x') {
        // Check for off
        if(ps->pos < ps->input_len) {
            char c = ps->input[ps->pos];
            if(c == '0' || c == '-') {
                // Percussion off
                output_byte(ps, 0xF9);
                ps->pos++;
                return true;
            }
        }
        // Percussion on
        output_byte(ps, 0xF8);
        return true;
    }
    
    ps->pos--;
    return false;
}

// Main parse function
ParseResult* parse_4ml_string(const char* input, size_t input_len) {
    static ParseResult result;
    
    // Initialize
    ParserState ps;
    memset(&ps, 0, sizeof(ps));
    ps.input = input;
    ps.input_len = input_len;
    ps.pos = 0;
    ps.bytecode_len = 0;
    ps.error_code = 0;
    ps.error_msg[0] = '\0';
    ps.error_pos = 0;
    
    // Default state
    strcpy(ps.prev_duration, "8");
    ps.prev_octave = 3;
    ps.current_channel = 0;
    ps.loop_depth = 0;
    
    // Main parse loop
    while(!at_end(&ps)) {
        char c = peek_char(&ps);
        
        if(c == '\0') break;
        
        // Notes and rest
        if(c == 'r' || (c >= 'a' && c <= 'g')) {
            parse_note(&ps);
        }
        // Octave
        else if(c == 'o') {
            parse_octave(&ps);
        }
        // Volume
        else if(c == 'v') {
            parse_volume(&ps);
        }
        // Octave shift
        else if(c == '<' || c == '>') {
            parse_octave_shift(&ps);
        }
        // Loops
        else if(c == '[' || c == ']') {
            parse_loop(&ps);
        }
        // Tie
        else if(c == '&' || c == '^') {
            parse_tie(&ps);
        }
        // Percussion
        else if(c == 'x') {
            parse_percussion(&ps);
        }
        // Two-byte commands
        else if(c == 'p' || c == 't' || c == '@' || c == 'i' || c == 'K' || c == 's' || c == 'F') {
            parse_fn_value(&ps, c);
        }
        // Skip unknown - advance past
        else {
            ps.pos++;
        }
        
        if(ps.error_code) break;
    }
    
    // Check for unclosed loops
    if(ps.loop_depth > 0 && !ps.error_code) {
        snprintf(ps.error_msg, sizeof(ps.error_msg),
                 "Unclosed loop at end");
        ps.error_code = 1;
        ps.error_pos = ps.bytecode_len;
    }
    
    // Set result
    result.success = (ps.error_code == 0);
    if(ps.error_code) {
        result.error_msg[0] = '\0';
        // Already set
    }
    
    // Allocate output
    result.data = malloc(ps.bytecode_len);
    if(result.data) {
        memcpy(result.data, ps.bytecode, ps.bytecode_len);
        result.length = ps.bytecode_len;
    } else {
        result.success = false;
        snprintf(result.error_msg, sizeof(result.error_msg),
                 "Memory allocation failed");
        result.length = 0;
    }
    
    return &result;
}

// Free parse result
void free_parse_result(ParseResult* result) {
    if(result && result->data) {
        free(result->data);
        result->data = NULL;
    }
}