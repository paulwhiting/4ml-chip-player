default:
	echo Specify a rule to build

.PRECIOUS: %.4ml

%.4ml: %.mid
	cp "$<" tmp-input.4ml
	. venv/bin/activate && python3 compiler/midi-to-4ml.py tmp-input.4ml > "$@"
	cp "$@" `basename "$@"` || true

%.4ml.h: %.4ml
	python3 compiler/4ml-compiler.py $<
	mv 4ml-data.h $@

%.4ml.avr.h: %.4ml
	python3 compiler/4ml-compiler.py --avr $<
	python3 compiler/combine-dotted-notes.py 4ml-data.h > $@

%.wav: %.4ml.h
	cp $< src/4ml-data.h
	gcc src/super-wavexe.c -O3 -o src/super-wavexe -lm -lasound
	src/super-wavexe
	mv output.wav $@

%.attiny.bin: %.4ml.avr.h | bonus/player-avr/4ml-avr-player.c
	cp $< bonus/player-avr/4ml-data.h
	avr-gcc -Os -std=gnu99 -Wall -funsigned-char -funsigned-bitfields -fpack-struct -fshort-enums  -ffunction-sections -fdata-sections  -DF_CPU=8000000UL -DBAUD=9600UL -I. -I../../AVR-Programming-Library -mmcu=attiny85 -c -o output.o bonus/player-avr/4ml-avr-player.c
	avr-gcc -Wl,-Map,output.map  -Wl,--gc-sections  -Wl,--relax -mmcu=attiny85 output.o  -o $@
	avr-size --mcu=attiny85 $@

%.atmega.bin: %.4ml.avr.h | bonus/player-avr/4ml-avr-player.c
	cp $< bonus/player-avr/4ml-data.h
	avr-gcc -Os -std=gnu99 -Wall -funsigned-char -funsigned-bitfields -fpack-struct -fshort-enums  -ffunction-sections -fdata-sections  -DF_CPU=8000000UL -DBAUD=9600UL -I. -I../../AVR-Programming-Library -mmcu=atmega328p -c -o output.o bonus/player-avr/4ml-avr-player.c
	avr-gcc -Wl,-Map,output.map  -Wl,--gc-sections  -Wl,--relax -mmcu=atmega328p output.o  -o $@
	avr-size --mcu=atmega328p $@

%.hex: %.bin
	avr-objcopy -j .text -j .data -O ihex $< $@

%: %.atmega.hex
	avrdude -p m328p -c arduino -P /dev/ttyUSB0 -b 115200 -D -U flash:w:$<:i
