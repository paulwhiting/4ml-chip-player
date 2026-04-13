default:
	echo Specify a rule to build

.PRECIOUS: %.4ml

%.mid: %.MID
	cp "$<" "$@"

%.4ml: %.mid
	cp "$<" tmp-input.4ml
	. venv/bin/activate && python3 compiler/midi-to-4ml.py tmp-input.4ml > "$@"
	cp "$@" `basename "$@"` || true

%.min.4ml: %.4ml
	python3 compiler/4ml-extract-patterns.py "$<" > "$@"

%.4ml.h: %.4ml compiler/compiler.py
	python3 compiler/compiler.py "$<"
	mv 4ml-data.h "$@"

%.4ml.avr.h: %.4ml compiler/compiler.py
	python3 compiler/compiler.py --avr "$<" > "$@"

album.4ml.avr.h: zelda.4ml z2-title.4ml z2-palace.4ml bonus/player-avr/songs/ninjagaiden.4ml bonus/player-avr/songs/wizards-and-warriors-intro.4ml mario.min.4ml
	python3 compiler/compiler.py --avr "$^" > "$@"

album2.4ml.avr.h: n-a-z.4ml bonus/player-avr/songs/ninjagaiden.4ml
	python3 compiler/compiler.py --avr "$^" > "$@"

%.wav: %.4ml.h
	cp "$<" src/4ml-data.h
	gcc src/super-wavexe.c -O3 -o src/super-wavexe -lm -lasound
	src/super-wavexe
	mv output.wav "$@"

# $(1) - chip
# $(2) - dest
# $(3) - src
# $(4) - speed
define BUILD_BINARY
	cp "$(3)" bonus/player-avr/4ml-data.h
	avr-gcc -Os -std=gnu99 -Wall -funsigned-char -funsigned-bitfields -fpack-struct -fshort-enums  -ffunction-sections -fdata-sections  -DF_CPU=$(4) -DBAUD=9600UL -I. -I../../AVR-Programming-Library -mmcu=$(1) -c -o output.o bonus/player-avr/4ml-avr-player.c
	avr-gcc -Wl,-Map,output.map  -Wl,--gc-sections  -Wl,--relax -mmcu=$(1) output.o  -o "$(2)"
	avr-size --mcu=$(1) "$(2)"
endef

%.attiny.bin: %.4ml.avr.h bonus/player-avr/4ml-avr-player.c
	$(call BUILD_BINARY,attiny85,$@,$<,8000000UL)

%.atmega.bin: %.4ml.avr.h bonus/player-avr/4ml-avr-player.c
	$(call BUILD_BINARY,atmega328p,$@,$<,16000000UL)

%.elf: %.4ml.avr.h bonus/player-avr/4ml-avr-player.c
	cp "$<" bonus/player-avr/4ml-data.h
	avr-gcc -Os -std=gnu99 -DF_CPU=16000000UL -mmcu=atmega328p \
		-o "$@" bonus/player-avr/4ml-avr-player.c

%.hex: %.bin
	avr-objcopy -j .text -j .data -O ihex "$<" "$@"

%: %.atmega.hex
	cp "$<" tmp.hex
	avrdude -p m328p -c arduino -P /dev/ttyUSB0 -b 115200 -D -U flash:w:tmp.hex:i
	rm tmp.hex

# === capture_avr (AVR simulator + audio capture) ===
# Runtime dependency: libsimavr.so.2 (install via apt on Debian/Ubuntu)

DEPS_SIMAVR = deps/simavr

capture_avr: capture_avr.c $(DEPS_SIMAVR)
	gcc -o $@ $< -I$(DEPS_SIMAVR) -L/lib/x86_64-linux-gnu \
		-l:libsimavr.so.2 -Wl,-rpath,/lib/x86_64-linux-gnu

$(DEPS_SIMAVR):
	mkdir -p deps/simavr
	cp -r /tmp/simavr/usr/include/simavr deps/simavr/

# Generate MP3 from ELF firmware
%.mp3: %.elf capture_avr
	./capture_avr "$<" > "$<.tmp.raw"
	lame -b 128 -r -s 44.1 "$<.tmp.raw" "$@"
	rm -f "$<.tmp.raw"

