# Unleashed Audio Manager

A tool for extracting and managing Nintendo DSP audio files from UBER container files (commonly found in GameCube/Wii games).

### Working with UBER and SAMP Files

**.UBER & .SAMP** are files that hold multiple DSP audio samples. Think of them like a ZIP file full of audio.

1. Browse or Drag and Drop the .samp and .uber files to the top 2 boxes.
2. The program will scan the file and list all the sounds it finds
3. You'll see each sound listed with its index number, sample rate, and length.

### Browsing Sounds

Once loaded, you'll see a scrollable list of all sounds in the container:
- Each entry shows: `<filename>_# - sample rate: #####, Length (seconds)`
- Simply scroll through to see what's available.
- All sounds are selected by default.

### Previewing Audio

1. Select a sound from the list
2. Click **"Preview"**
3. The audio will be played through the default media player.
4. Use this to test sounds before exporting

**Tip:** Preview is great for finding specific sound effects without having to export everything.

### Exporting Individual Files

#### Export as DSP (Original Format)
1. Select a sound from the list
2. Click **"Save DSP"**, It will appear in the location of the .samp and .uber files.
3. The filename will automatically follow the pattern `filename_##.dsp` (e.g., `Gigan_05.dsp`)

#### Export as WAV (Universal Format)
1. Select sounds from the `Loaded Sounds` list
2. Click **EXPORT**, It will appear in the location of the .samp and .uber files.
3. The DSP is decoded and saved as a standard WAV file you can use anywhere

### Batch Export

Want everything at once?

1. Leave everything checked.
2. Click **"Export"**, It will appear in the location of the .samp and .uber files.

**Example:** If you export all from `Gigan.uber` and `Gigan.samp`, you'll get:
```
Gigan_01.wav
Gigan_02.wav
Gigan_03.wav
Gigan_04.wav
...
```

### Rebuilding Game Audio

Want to put your edited audio back into the game? The Rebuild function takes your modified files and repackages them:

1. Click **"Rebuild"**
2. The program automatically finds all WAV files and any DSP files without corresponding WAVs in the directory
3. WAV files are converted to mono DSP with the correct sample rates and specifications
4. New `.uber` and `.samp` files are created ready to inject back into your game

**What Rebuild Does:**
- Converts stereo WAV files to mono (required for GameCube/Wii audio)
- Re-encodes audio to Nintendo DSP format with proper ADPCM compression
- Preserves original sample rates and specifications from the source files
- Generates matching `.uber` and `.samp` files that the game can read

**Old Method Support:**
Already have edited DSP files from previous tools? No problem! Rebuild also accepts DSP files directly, so you can use your existing workflow if you prefer editing DSPs manually instead of WAVs.

**Tip:** Import troubles? Name your edited files using the same pattern. (`filename_##.wav` or `filename_##.dsp`).

## Tips

- **Preview before exporting** - Save time by listening first
- **Export All for archival** - Grab everything at once, .wav makes it easily accessible!
- **WAV for editing** - Export as WAV to use in audio editing software
- **Keep DSP for authenticity** - DSP files preserve the original game format, or if you like the old editing method.

## Supported Games

This tool works with any game that uses UBER containers and Nintendo DSP audio, including:
- Many GameCube titles
- Various Wii games
- Any game using the WiiMusyx or similar sound engines
---

**Note:** The program automatically handles DSP decoding, sample rates, and loop points. Just load, preview, and export!
