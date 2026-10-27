default:
	echo Specify a rule to build

.PRECIOUS: %.4ml %.raw

%.mid: %.MID
	cp "$<" "$@"

%.4ml: %.mid
	cp "$<" tmp-input.4ml
	. venv/bin/activate && python3 compiler/midi-to-4ml.py tmp-input.4ml > "$@"
	#cp "$@" "`basename '$@'`" || true

%.min.4ml: %.4ml
	python3 compiler/4ml-extract-patterns.py "$<" > "$@"

%.min5.4ml: %.4ml
	python3 compiler/4ml-extract-patterns.py --max-rounds 5 "$<" > "$@"

%.reduced.4ml: %.4ml
	python compiler/4ml-reduce-channels.py "$<" > "$@"


#### Transpose Rule

TRANSPOSITIONS := -24 -23 -22 -21 -20 -19 -18 -17 -16 -15 -14 -13 -12 -11 -10 -9 -8 -7 -6 -5 -4 -3 -2 -1 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24

define TRANSPOSITION_RULE
%.transpose$(1).4ml: %.4ml
	python compiler/4ml-update.py "$$<" --transpose "$(1)" > "$$@"
endef

$(foreach n,$(TRANSPOSITIONS),$(eval $(call TRANSPOSITION_RULE,$(n))))


#### Tempo Rule

define TEMPO_RULE
%.tempo$(1).4ml: %.4ml
	python compiler/4ml-update.py "$$<" --tempo $(1) > "$$@"
endef

$(foreach t,$(shell seq 1 255),$(eval $(call TEMPO_RULE,$(t))))


#### Volume Rule

define VOLUME_RULE
%.volume$(1).4ml: %.4ml
	python compiler/4ml-update.py "$$<" --volume $(1) > "$$@"
endef

$(foreach t,$(shell seq 1 16),$(eval $(call VOLUME_RULE,$(t))))


####



%.4ml.h: %.4ml compiler/compiler.py
	python3 compiler/compiler.py "$<"
	mv 4ml-data.h "$@"

%.4ml.avr.h: %.4ml compiler/compiler.py
	python3 compiler/compiler.py --avr "$<" > "$@"

album.4ml.avr.h: Makefile \
	songs/the-moon.min.4ml \
	songs/kraids-hideout.tempo35.min.4ml \
	songs/smb-overworld.min.4ml \
	songs/smb-underground.tempo60.min.4ml \
	songs/smb-water.tempo23.min.4ml \
	songs/ninjagaiden.min.4ml \
	songs/wizards-and-warriors-intro.tempo32.reduced.min.4ml \
	songs/Rad_Racer_02_In-Game_Tune_2_v1.tempo46.min.4ml \
	songs/gauntlet-title-screen.tempo46.min.4ml \
	songs/mega-man-3-proto-man.tempo46.reduced.transpose-6.min.4ml \
	songs/goonies-2-good-enough.min.4ml \
	songs/kid-icarus-stage-1-underworld.min.4ml \
	songs/mike-tysons-punchout-match.tempo33.reduced.transpose-6.min.4ml \
	songs/secret-of-mana-color-of-the-summer-sky.4ml \
	songs/sorcerian-castle.tempo58.reduced.transpose-6.min.4ml \
	songs/Wii_Channels_-_Mii_Channel.tempo28.reduced.transpose6.min.4ml \
	songs/zelda-overworld.min.4ml \
	songs/z2-palace.tempo34.reduced.min.4ml \
	songs/dark-world-overworld.tempo31.reduced.transpose18.min.4ml \
	songs/contra-stage-1-the-jungle-trimmed.tempo33.min.4ml \
	songs/smb-2-ending.tempo43.reduced.transpose-6.min.4ml \
	songs/Tatakai_no_Banka_08_Song_8_v1.tempo45.reduced.min.4ml \
	songs/ninja-gaiden-ending.tempo35.transpose8.min.4ml \
	songs/bluey.reduced.tempo24.volume13.min.4ml \
	songs/harry-potter-hedwig.reduced.tempo34.volume16.transpose-3.4ml \
	songs/byu.4ml \
	songs/never-better.tempo43.volume16.min.4ml
	python3 compiler/compiler.py --avr $(filter-out Makefile, $^) > "$@"

album2.4ml.avr.h: Makefile songs/zelda.reduced.min.4ml songs/gerudo.reduced.min.4ml songs/raiders.reduced12.min.4ml songs/super-mario-world-credits.min.4ml songs/enter-samus.reduced-1.min.4ml songs/brinstar.reduced.min.4ml songs/mario.tempo2.min.4ml 
	python3 compiler/compiler.py --avr $(filter-out Makefile, $^) > "$@"


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

%.atmega.elf: %.4ml.avr.h bonus/player-avr/4ml-avr-player.c
	cp "$<" bonus/player-avr/4ml-data.h
	avr-gcc -Os -std=gnu99 -DF_CPU=16000000UL -mmcu=atmega328p \
		-o "$@" bonus/player-avr/4ml-avr-player.c

%.atmega.hex: %.bin
	avr-objcopy -j .text -j .data -O ihex "$<" "$@"

%.atmega: %.atmega.hex
	cp "$<" tmp.hex
	avrdude -p m328p -c arduino -P /dev/ttyUSB0 -b 115200 -D -U flash:w:tmp.hex:i
	rm tmp.hex




#######################################################
####   STM32 section

CC = clang
OBJCOPY = llvm-objcopy-19
SIZE = llvm-size-19
FLASHER = /opt/st/stm32cubeide_2.2.0/plugins/com.st.stm32cube.ide.mcu.externaltools.cubeprogrammer.linux64_2.2.500.202603051304/tools/bin/STM32_Programmer_CLI
#FLASHER = STM32_Programmer_CLI

CFLAGS = \
	--target=arm-none-eabi \
	-mcpu=cortex-m0plus \
	-mthumb \
	-O2 \
	-ffreestanding \
	-fno-builtin \
	-Wall \
	-Wextra \
	-DSTM32C011 \
	-I cmsis-device-c0/Include \
	-I CMSIS_5/CMSIS/Core/Include

LDFLAGS = \
	--target=arm-none-eabi \
	-mcpu=cortex-m0plus \
	-mthumb \
	-nostdlib \
	-fuse-ld=lld \
	-Wl,-T,stm32c011.ld \
	-Wl,-e,Reset_Handler

main.o: main.c
	$(CC) $(CFLAGS) -c $< -o $@

stm32c011-startup.o: stm32c011-startup.s
	$(CC) \
		--target=arm-none-eabi \
		-mcpu=cortex-m0plus \
		-mthumb \
		-c $< -o $@

cmsis-device-c0:
	git clone --depth 1 --filter=blob:none --sparse https://github.com/STMicroelectronics/cmsis-device-c0.git
	
CMSIS_5:
	git clone --depth 1 --filter=blob:none https://github.com/ARM-software/CMSIS_5.git

%.st.bin: %.4ml.avr.h bonus/player-avr/4ml-avr-player.c stm32c011-startup.o cmsis-device-c0 CMSIS_5
	cp "$<" bonus/player-avr/4ml-data.h
	$(CC) $(CFLAGS) $(LDFLAGS) stm32c011-startup.o -o "$@" bonus/player-avr/4ml-avr-player.c
	#$(CC) $(CFLAGS) $(LDFLAGS) stm32c011-startup.o -o "$@" bonus/player-avr/tim_voice.c
	$(SIZE) "$@"

%.st.hex: %.st.bin
	$(OBJCOPY) -O ihex "$<" "$@"

clean:
	rm -f *.o *.elf *.bin

%.st: %.st.hex
	$(FLASHER) \
		-c port=SWD \
		-ob NRST_MODE=2
		#-ob BOR_EN=0x1 -ob BORF_LEV=0x3 -ob BORR_LEV=0x3
	$(FLASHER) \
		-c port=SWD \
		-d "$<" \
		-v \
		-rst


##### Flash with pyOCD
# pipx install pyocd
# pyocd pack install STM32C011J6Mx

%.pyocd: %.st.hex
	pyocd flash -t STM32C011J6Mx "$<"


##### Flash with openocd
#OPENOCD ?= openocd
#OPENOCD_INTERFACE ?= interface/cmsis-dap.cfg
#OPENOCD_TARGET ?= target/stm32c0x.cfg
#
#%.ocd: %.st.hex
#	$(OPENOCD) \
#	    -f $(OPENOCD_INTERFACE) \
#	    -f $(OPENOCD_TARGET) \
#	    -c "transport select swd" \
#	    -c "adapter speed 100" \
#	    -c "program $< verify reset exit"


.PHONY: all clean flash



# === capture_avr (AVR simulator + audio capture) ===
# Runtime dependency: libsimavr.so.2 (install via apt on Debian/Ubuntu)

DEPS_SIMAVR = deps/

capture_avr: capture_avr.c $(DEPS_SIMAVR)
	gcc -o $@ $< -I$(DEPS_SIMAVR) -L/lib/x86_64-linux-gnu \
		-l:libsimavr.so.2 -Wl,-rpath,/lib/x86_64-linux-gnu

# Generate MP3 from ELF firmware
%.elf.raw: %.elf capture_avr
	./capture_avr "$<" > "$<.raw"

# Generate MP3 from ELF firmware
%.elf.filtered.wav: %.elf.raw
	python3 filter_audio.py 1 < "$<" > "$<.filtered"
	ffmpeg -f s16le -ar 44100 -ac 1 -i "$<.filtered" -y "$@"

# Generate MP3 from ELF firmware
%.mp3: %.elf.filtered.wav
	ffmpeg -i "$<" -b:a 128k -y "$@"

# === Flipper Zero ===
# Using uFBT (micro Flipper Build Tool)
# Build: make flipper/4ml_player.fap
# Flash: make flipper/flash (requires Flipper connected via USB)

flipper/4ml-data.h: album.4ml.avr.h
	sed 's/PROGMEM//' "$<" | sed '1i #include <stdint.h>' > "$@"

flipper/4ml_player.fap: flipper/4ml-flipper-player.c flipper/application.fam
	cd flipper && ufbt build
	cp ~/.ufbt/build/4ml_player.fap "$@"

flipper/flash: flipper/4ml-flipper-player.c flipper/application.fam
	cd flipper && ufbt launch

