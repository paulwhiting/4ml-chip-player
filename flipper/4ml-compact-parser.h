/*H*****************************************************************************
 *  FILENAME:     4ml-compact-parser.h
 *  DESCRIPTION: 4ML Compact Parser - C port of Python compiler
 *               Supports ALL 4ML features for Flipper Zero
 *
 *  AUTHOR:      Blake 'PROTODOME' Troise (Original Python)
 *               Ported to C for Flipper Zero
 *  DATE:        2024
 *****************************************************************************H*/

#ifndef COMPACT_PARSER_H
#define COMPACT_PARSER_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#define MAX_BYTECODE_SIZE 16384
#define MAX_CHANNELS 8
#define MAX_PATTERNS 16

typedef struct {
    uint8_t* data;
    uint16_t length;
    bool success;
    char error_msg[128];
    uint16_t error_pos;
} ParseResult;

// Note values
#define NOTE_REST    0
#define NOTE_C     1
#define NOTE_CS    2
#define NOTE_D     3
#define NOTE_DS    4
#define NOTE_E     5
#define NOTE_F     6
#define NOTE_FS    7
#define NOTE_G     8
#define NOTE_GS    9
#define NOTE_A     10
#define NOTE_AS    11
#define NOTE_B     12

// Duration values
#define DUR_1      0
#define DUR_2      1
#define DUR_4      2
#define DUR_8      3
#define DUR_16     4
#define DUR_32     5
#define DUR_64     6
#define DUR_128    7
#define DUR_2_D    8
#define DUR_4_D    9
#define DUR_8_D    10
#define DUR_16_D   11
#define DUR_32_D   12
#define DUR_64_D   13
#define DUR_EXT    15

// Command FN values
#define CMD_FN_LOOP_START   0
#define CMD_FN_LOOP_END     1
#define CMD_FN_MACRO      2
#define CMD_FN_TEMPO      3
#define CMD_FN_TRANSPOSE  4
#define CMD_FN_INSTRUMENT 5
#define CMD_FN_TIE        6
#define CMD_FN_PAN        7
#define CMD_FN_PERCUSSION 8
#define CMD_FN_PERC_OFF   9

// Parse a 4ML file from storage
// Returns bytecode in result->data, or sets error on failure
ParseResult* parse_4ml_file(const char* filepath);

// Parse 4ML string to bytecode
ParseResult* parse_4ml_string(const char* input, size_t input_len);

// Free parse result
void free_parse_result(ParseResult* result);

#endif