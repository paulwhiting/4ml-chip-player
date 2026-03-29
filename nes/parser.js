const GM_PERCUSSION_CHANNEL = 9;
const PERCUSSION_NOTE_MIN = 35;
const PERCUSSION_NOTE_MAX = 81;
const SUSTAIN_PEDAL_CC = 64;

class MIDIReader {
  constructor(buffer) {
    this.buffer = new Uint8Array(buffer);
    this.offset = 0;
  }
  
  readString(length) {
    let s = '';
    for (let i = 0; i < length; i++) s += String.fromCharCode(this.buffer[this.offset++]);
    return s;
  }
  
  readUint32() {
    const val = (this.buffer[this.offset] << 24) | 
                (this.buffer[this.offset + 1] << 16) | 
                (this.buffer[this.offset + 2] << 8) | 
                this.buffer[this.offset + 3];
    this.offset += 4;
    return val;
  }
  
  readUint16() {
    const val = (this.buffer[this.offset] << 8) | this.buffer[this.offset + 1];
    this.offset += 2;
    return val;
  }
  
  readByte() {
    return this.buffer[this.offset++];
  }
  
  readVariableLength() {
    let value = 0;
    while (this.offset < this.buffer.length) {
      const byte = this.readByte();
      value = (value << 7) | (byte & 0x7F);
      if ((byte & 0x80) === 0) break;
    }
    return value;
  }
}

function parseMIDIToEvents(buffer, ignoreSustainPedal = false) {
  const reader = new MIDIReader(buffer);
  
  const header = reader.readString(4);
  if (header !== 'MThd') return null;
  
  const headerLen = reader.readUint32();
  if (headerLen !== 6) return null;
  
  const format = reader.readUint16();
  const numTracks = reader.readUint16();
  const ticksPerBeat = reader.readUint16();
  
  if (ticksPerBeat === 0) return null;
  
  const events = [];
  let sustainUsed = false;
  let activeNotes = {};
  const pendingNoteOffs = [];
  let globalTempo = 500000;
  let currentTempo = globalTempo;
  
  function ticksToMs(ticks) {
    const msPerBeat = currentTempo / 1000;
    const msPerTick = msPerBeat / ticksPerBeat;
    return Math.round(ticks * msPerTick);
  }
  
  function processPendingNoteOffs(timeMs) {
    for (const off of pendingNoteOffs) {
      events.push({
        t: timeMs,
        noteIdx: off.noteIdx,
        on: false,
        percussion: off.isPercussion,
        channel: off.channel,
        volume: off.volume
      });
    }
    pendingNoteOffs.length = 0;
  }
  
  for (let track = 0; track < numTracks; track++) {
    const trackHeader = reader.readString(4);
    if (trackHeader !== 'MTrk') return null;
    
    const trackLen = reader.readUint32();
    const trackEnd = reader.offset + trackLen;
    let trackTime = 0;
    let lastEventType = 0;
    let sustainActive = false;
    
    while (reader.offset < trackEnd) {
      const deltaTime = reader.readVariableLength();
      trackTime += deltaTime;
      const timeMs = ticksToMs(trackTime);
      
      let status = reader.readByte();
      
      if (status < 0x80) {
        reader.offset--;
        status = lastEventType;
      } else {
        lastEventType = status;
      }
      
      const eventType = status >> 4;
      const channel = status & 0x0F;
      
      switch (eventType) {
        case 0x8:
        case 0x9:
        case 0xA:
        case 0xB:
        case 0xE: {
          const note = reader.readByte();
          const velocity = reader.readByte();
          
          if (eventType === 0x8 || (eventType === 0x9 && velocity === 0)) {
            const channelName = 'CH' + (channel + 1);
            const isPercussion = channel === GM_PERCUSSION_CHANNEL && 
                                 note >= PERCUSSION_NOTE_MIN && note <= PERCUSSION_NOTE_MAX;
            const noteIdx = note - 47;
            
            if (sustainActive && !ignoreSustainPedal) {
              pendingNoteOffs.push({ channel: channelName, noteIdx, isPercussion, volume: 8 });
            } else {
              if (activeNotes[channelName] && activeNotes[channelName].note === note) {
                delete activeNotes[channelName];
              }
              for (const key in activeNotes) {
                if (key.startsWith(channelName + '-') && activeNotes[key].note === note) {
                  delete activeNotes[key];
                }
              }
              events.push({
                t: timeMs,
                noteIdx,
                on: false,
                percussion: isPercussion,
                channel: channelName,
                volume: 8
              });
            }
          } else if (eventType === 0x9 && velocity > 0) {
            const isPercussion = channel === GM_PERCUSSION_CHANNEL && 
                                 note >= PERCUSSION_NOTE_MIN && note <= PERCUSSION_NOTE_MAX;
            const noteIdx = note - 47;
            const volume = Math.round(velocity / 8) + 1;
            
            let channelName = 'CH' + (channel + 1);
            if (activeNotes[channelName] && activeNotes[channelName].note === note) {
              let idx = 1;
              while (activeNotes[channelName + '-' + idx]) idx++;
              channelName = channelName + '-' + idx;
            }
            
            activeNotes[channelName] = { note, timeMs };
            
            events.push({
              t: timeMs,
              noteIdx,
              on: true,
              percussion: isPercussion,
              channel: channelName,
              volume
            });
          }
          break;
        }
        
        case 0xB: {
          const cc = reader.readByte();
          const value = reader.readByte();
          if (cc === SUSTAIN_PEDAL_CC) {
            const wasActive = sustainActive;
            sustainActive = value >= 64;
            if (sustainActive) {
              sustainUsed = true;
            } else if (wasActive && !ignoreSustainPedal) {
              const timeMs = ticksToMs(trackTime);
              processPendingNoteOffs(timeMs);
            }
          }
          break;
        }
        
        case 0xC:
        case 0xD:
          reader.readByte();
          break;
        
        case 0xF:
          if (eventType === 0xF && channel === 0xF) {
            const metaType = reader.readByte();
            const length = reader.readVariableLength();
            if (metaType === 0x51 && length === 3) {
              const tempo = (reader.readByte() << 16) | (reader.readByte() << 8) | reader.readByte();
              currentTempo = tempo;
            } else {
              reader.offset += length;
            }
          }
          break;
        
        default:
          break;
      }
    }
  }
  
  return events;
}

function parse4MLToEvents(text) {
  const events = [];
  const lines = text.split('\n');
  const channels = [];
  let currentChannel = -1;
  let globalTempo = 60;
  let globalTimeMs = 0;
  const channelTimes = {};
  
  for (const line of lines) {
    const stripped = line.trim();
    if (!stripped) continue;
    const channelMatch = stripped.match(/^C(\d+)\s*(.*)$/);
    if (channelMatch) {
      currentChannel = parseInt(channelMatch[1], 10);
      if (!channels[currentChannel]) channels[currentChannel] = '';
      channelTimes[currentChannel] = globalTimeMs;
      channels[currentChannel] += channelMatch[2] || '';
    } else if (currentChannel >= 0 && !stripped.startsWith(';')) {
      channels[currentChannel] += stripped;
    }
  }
  
  const noteLetterToSemitone = { c:0, 'c+':1, d:2, 'd+':3, e:4, f:5, 'f+':6, g:7, 'g+':8, a:9, 'a+':10, b:11 };
  
  const beatMs = () => 60000 / globalTempo;
  
  for (let chIdx = 0; chIdx < channels.length; chIdx++) {
    const channelContent = channels[chIdx];
    if (!channelContent) continue;
    const isPercussion = /x[1+]?/i.test(channelContent);
    const channelName = 'CH' + chIdx;
    let currentOctave = 3;
    let currentDuration = 8;
    let currentVolume = 8;
    let timeMs = channelTimes[chIdx] || 0;
    let i = 0;
    const content = channelContent;
    
    while (i < content.length) {
      const ch = content[i];
      if (ch === 't' || ch === 'T') {
        i++;
        let num = '';
        while (i < content.length && /\d/.test(content[i])) { num += content[i]; i++; }
        if (num) globalTempo = Math.min(255, parseInt(num, 10));
        continue;
      }
      if (ch === 'o' || ch === 'O') {
        i++;
        let num = '';
        while (i < content.length && /\d/.test(content[i])) { num += content[i]; i++; }
        if (num) currentOctave = Math.max(0, Math.min(8, parseInt(num, 10)));
        continue;
      }
      if (ch === 'v' || ch === 'V') {
        i++;
        let num = '';
        while (i < content.length && /\d/.test(content[i])) { num += content[i]; i++; }
        if (num) currentVolume = Math.max(1, Math.min(16, parseInt(num, 10)));
        continue;
      }
      if (ch === 'i' || ch === 'I' || ch === '@') {
        i++;
        while (i < content.length && /\d/.test(content[i])) i++;
        continue;
      }
      if (ch === 'r' || ch === 'R') {
        i++;
        let num = '';
        while (i < content.length && /\d/.test(content[i])) { num += content[i]; i++; }
        const dotted = content[i] === '.';
        if (dotted) i++;
        const div = num ? parseInt(num, 10) : currentDuration;
        if ([1,2,4,8,16,32,64,128].indexOf(div) !== -1) {
          let ms = beatMs() * 4 / div;
          if (dotted) ms *= 1.5;
          timeMs += ms;
          if (num) currentDuration = div;
        }
        continue;
      }
      if (ch === '&' || ch === '^' || ch === '<' || ch === '>' || ch === '+' || ch === '#') {
        i++;
        continue;
      }
      const noteMatch = content.slice(i).match(/^([cdefgab])([\+#])?(\d*)(\.)?/i);
      if (noteMatch) {
        let letter = noteMatch[1].toLowerCase();
        if (noteMatch[2]) letter += '+';
        const div = noteMatch[3] ? parseInt(noteMatch[3], 10) : currentDuration;
        if ([1,2,4,8,16,32,64,128].indexOf(div) !== -1) {
          const semitone = noteLetterToSemitone[letter];
          if (semitone !== undefined) {
            const noteIdx = (currentOctave + 1) * 12 + semitone - 47;
            let ms = beatMs() * 4 / div;
            if (noteMatch[4]) ms *= 1.5;
            events.push({ t: Math.round(timeMs), noteIdx, on: true, percussion: isPercussion, channel: channelName, volume: currentVolume });
            events.push({ t: Math.round(timeMs + ms), noteIdx, on: false, percussion: isPercussion, channel: channelName, volume: currentVolume });
            timeMs += ms;
          }
        }
        i += noteMatch[0].length;
        continue;
      }
      i++;
    }
  }
  
  return events;
}

function getRecordingDurationMs(events) {
  if (!events.length) return 0;
  const maxT = Math.max(...events.map(e => e.t));
  return maxT + 300;
}

function sortEvents(events) {
  return events.slice().sort((a, b) => a.t - b.t);
}

module.exports = {
  parseMIDIToEvents,
  parse4MLToEvents,
  getRecordingDurationMs,
  sortEvents,
  MIDIReader
};
