#!/usr/bin/env python3
"""
Apply moving average filter to raw PCM audio.
Usage: filter_audio.py <window_size> <input.raw > output.raw
"""

import sys
import wave

def apply_moving_average(input_bytes, window_size):
    """Apply moving average filter to convert 1-bit to multi-bit audio."""
    # Input is unsigned 8-bit, output is signed 16-bit
    output = []
    
    # Simple moving average
    for i in range(len(input_bytes)):
        start = max(0, i - window_size + 1)
        window = input_bytes[start:i+1]
        avg = sum(window) / len(window)
        
        # Convert 0-255 to -32768 to 32767
        sample = int((avg / 255.0 * 65535) - 32768)
        
        # Pack as little-endian 16-bit signed
        output.append(sample & 0xFF)
        output.append((sample >> 8) & 0xFF)
    
    return bytes(output)

def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <window_size> [input.raw]", file=sys.stderr)
        print("Reads from stdin, writes to stdout", file=sys.stderr)
        sys.exit(1)
    
    window_size = int(sys.argv[1])
    
    # Read raw 8-bit unsigned PCM from stdin
    input_data = sys.stdin.buffer.read()
    
    # Apply filter
    output_data = apply_moving_average(input_data, window_size)
    
    # Write to stdout
    sys.stdout.buffer.write(output_data)

if __name__ == "__main__":
    main()