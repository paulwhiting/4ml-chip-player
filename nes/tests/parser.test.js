const { parse4MLToEvents, parseMIDIToEvents, getRecordingDurationMs, sortEvents } = require('../parser');

describe('4ML Parser', () => {
  test('parses simple 4ML with single note', () => {
    const text = 'C0 c4';
    const events = parse4MLToEvents(text);
    
    expect(events).toBeDefined();
    expect(events.length).toBe(2); // note on and note off
    
    // First event should be note on
    expect(events[0].on).toBe(true);
    expect(events[0].noteIdx).toBeDefined();
    expect(events[0].channel).toBe('CH0');
    
    // Second event should be note off
    expect(events[1].on).toBe(false);
    expect(events[1].t).toBeGreaterThan(events[0].t);
  });

  test('parses 4ML with multiple notes', () => {
    const text = 'C0 c4 d4 e4';
    const events = parse4MLToEvents(text);
    
    expect(events).toBeDefined();
    expect(events.length).toBe(6); // 3 notes * 2 events each
    
    // All should be on channel 0
    events.forEach(ev => {
      expect(ev.channel).toBe('CH0');
    });
    
    // Notes should be sequential
    expect(events[0].on).toBe(true);
    expect(events[1].on).toBe(false);
    expect(events[2].on).toBe(true);
  });

  test('parses 4ML with channel specification', () => {
    const text = `C0 c4
C1 d4`;
    const events = parse4MLToEvents(text);
    
    expect(events).toBeDefined();
    expect(events.length).toBe(4); // 2 notes on 2 channels
    
    const ch0Events = events.filter(e => e.channel === 'CH0');
    const ch1Events = events.filter(e => e.channel === 'CH1');
    
    expect(ch0Events.length).toBe(2);
    expect(ch1Events.length).toBe(2);
  });

  test('parses tempo changes', () => {
    const text = 'C0 t120 c4 t60 d4';
    const events = parse4MLToEvents(text);
    
    expect(events).toBeDefined();
    // Tempo should affect note durations differently
    expect(events.length).toBe(4);
  });

  test('parses volume changes', () => {
    const text = 'C0 v8 c4 v4 d4';
    const events = parse4MLToEvents(text);
    
    expect(events).toBeDefined();
    
    const c4Events = events.filter(e => e.t === events[0].t);
    const d4Events = events.filter(e => e.t !== events[0].t && e.on);
    
    expect(c4Events[0].volume).toBe(8);
    expect(d4Events[0].volume).toBe(4);
  });

  test('parses octave changes', () => {
    const text = 'C0 o4 c4 o5 c4';
    const events = parse4MLToEvents(text);
    
    expect(events).toBeDefined();
    
    // First c4 should be lower than second c4
    const c4s = events.filter(e => e.on);
    expect(c4s[0].noteIdx).toBeLessThan(c4s[1].noteIdx);
  });

  test('handles rest commands', () => {
    const text = 'C0 c4 r4 d4';
    const events = parse4MLToEvents(text);
    
    expect(events).toBeDefined();
    expect(events.length).toBe(4); // 2 notes + 2 rests
    
    // Second note should start after first note + rest
    const noteOns = events.filter(e => e.on);
    expect(noteOns[1].t).toBeGreaterThan(noteOns[0].t);
  });

  test('handles comments', () => {
    const text = `; This is a comment
C0 c4 ; another comment
; more comment`;
    const events = parse4MLToEvents(text);
    
    expect(events).toBeDefined();
    // At least the main note should be parsed despite comments
    expect(events.length).toBeGreaterThanOrEqual(2);
  });

  test('returns empty array for empty input', () => {
    const events = parse4MLToEvents('');
    expect(events).toEqual([]);
  });

  test('handles percussion channel', () => {
    const text = 'C0 x c4';
    const events = parse4MLToEvents(text);
    
    expect(events).toBeDefined();
    expect(events[0].percussion).toBe(true);
  });
});

describe('Event Utilities', () => {
  test('getRecordingDurationMs returns 0 for empty events', () => {
    const duration = getRecordingDurationMs([]);
    expect(duration).toBe(0);
  });

  test('getRecordingDurationMs returns max time + 300', () => {
    const events = [
      { t: 1000, noteIdx: 0, on: true },
      { t: 500, noteIdx: 0, on: false },
      { t: 2000, noteIdx: 1, on: true },
      { t: 2500, noteIdx: 1, on: false }
    ];
    const duration = getRecordingDurationMs(events);
    expect(duration).toBe(2800); // max(2500) + 300 = 2800
  });

  test('sortEvents sorts by time', () => {
    const events = [
      { t: 2000, noteIdx: 1, on: true },
      { t: 500, noteIdx: 0, on: true },
      { t: 1000, noteIdx: 0, on: false }
    ];
    const sorted = sortEvents(events);
    
    expect(sorted[0].t).toBe(500);
    expect(sorted[1].t).toBe(1000);
    expect(sorted[2].t).toBe(2000);
  });

  test('sortEvents does not mutate original', () => {
    const events = [
      { t: 2000, noteIdx: 1, on: true },
      { t: 500, noteIdx: 0, on: true }
    ];
    const sorted = sortEvents(events);
    
    expect(events[0].t).toBe(2000); // original unchanged
    expect(sorted[0].t).toBe(500);
  });
});

describe('MIDI Parser', () => {
  test('returns null for invalid MIDI header', () => {
    const invalidMidi = new ArrayBuffer(100);
    const view = new Uint8Array(invalidMidi);
    // Fill with invalid data
    for (let i = 0; i < 100; i++) view[i] = 0;
    
    const events = parseMIDIToEvents(invalidMidi);
    expect(events).toBeNull();
  });

  test('returns null for invalid header length', () => {
    // Create a minimal MIDI file with wrong header length
    const buffer = new ArrayBuffer(16);
    const view = new Uint8Array(buffer);
    
    // MThd
    view[0] = 0x4D; // M
    view[1] = 0x54; // T
    view[2] = 0x68; // h
    view[3] = 0x64; // d
    // headerLen = 5 (should be 6)
    view[4] = 0x00;
    view[5] = 0x00;
    view[6] = 0x00;
    view[7] = 0x05;
    
    const events = parseMIDIToEvents(buffer);
    expect(events).toBeNull();
  });

  test('parses minimal valid MIDI', () => {
    // Create a minimal valid MIDI file
    const buffer = new ArrayBuffer(22);
    const view = new Uint8Array(buffer);
    
    // MThd
    view[0] = 0x4D; view[1] = 0x54; view[2] = 0x68; view[3] = 0x64;
    // headerLen = 6
    view[4] = 0x00; view[5] = 0x00; view[6] = 0x00; view[7] = 0x06;
    // format = 0, tracks = 1, ticks/beat = 120
    view[8] = 0x00; view[9] = 0x00; view[10] = 0x00; view[11] = 0x01;
    view[12] = 0x00; view[13] = 0x78;
    // MTrk
    view[14] = 0x4D; view[15] = 0x54; view[16] = 0x72; view[17] = 0x6B;
    // trackLen = 4
    view[18] = 0x00; view[19] = 0x00; view[20] = 0x00; view[21] = 0x04;
    
    const events = parseMIDIToEvents(buffer);
    // Should return empty or near-empty array (no note events)
    expect(events).toBeDefined();
    expect(Array.isArray(events)).toBe(true);
  });

  test('parses MIDI with note on event', () => {
    // Create a minimal MIDI with one note on channel 0
    // MThd (14 bytes) + MTrk header (8) + delta time + note on + delta time + note off + end of track
    const buffer = new ArrayBuffer(100);
    const view = new Uint8Array(buffer);
    
    // MThd
    let offset = 0;
    [0x4D, 0x54, 0x68, 0x64].forEach(b => view[offset++] = b);
    // headerLen = 6
    [0x00, 0x00, 0x00, 0x06].forEach(b => view[offset++] = b);
    // format = 0, tracks = 1, ticks/beat = 120
    [0x00, 0x00, 0x00, 0x01, 0x00, 0x78].forEach(b => view[offset++] = b);
    // MTrk
    [0x4D, 0x54, 0x72, 0x6B].forEach(b => view[offset++] = b);
    // trackLen (will fill in later, let's put placeholder)
    const trackLenPos = offset;
    [0x00, 0x00, 0x00, 0x00].forEach(b => view[offset++] = b);
    
    // Track content: delta=0, note on ch0 note 60 vel 64
    view[offset++] = 0x00; // delta time
    view[offset++] = 0x90; // note on channel 0
    view[offset++] = 0x3C; // middle C
    view[offset++] = 0x40; // velocity 64
    
    // delta=100, note off ch0 note 60
    view[offset++] = 0x64; // delta time = 100
    view[offset++] = 0x80; // note off channel 0
    view[offset++] = 0x3C; // middle C
    view[offset++] = 0x00; // velocity 0
    
    // End of track
    view[offset++] = 0x00; // delta time
    view[offset++] = 0xFF; // meta
    view[offset++] = 0x2F; // end of track
    view[offset++] = 0x00; // length 0
    
    // Update track length
    const trackLen = offset - trackLenPos - 4;
    view[trackLenPos] = (trackLen >> 24) & 0xFF;
    view[trackLenPos + 1] = (trackLen >> 16) & 0xFF;
    view[trackLenPos + 2] = (trackLen >> 8) & 0xFF;
    view[trackLenPos + 3] = trackLen & 0xFF;
    
    const events = parseMIDIToEvents(buffer);
    
    expect(events).toBeDefined();
    expect(events.length).toBe(2); // note on and note off
    
    // First event is note on
    expect(events[0].on).toBe(true);
    expect(events[0].noteIdx).toBe(13); // middle C (60) - 47 = 13
    expect(events[0].channel).toBe('CH1'); // channel 0 = CH1
    
    // Second event is note off
    expect(events[1].on).toBe(false);
    expect(events[1].t).toBeGreaterThan(events[0].t);
  });
});
