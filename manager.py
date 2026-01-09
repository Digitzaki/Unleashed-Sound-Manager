import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk
import os
import subprocess
import platform
from pathlib import Path

from dsp_codec import decode_dsp_adpcm, encode_dsp_adpcm, create_dsp_file, nibbles_to_samples
from file_operations import (
    extract_sdir_from_uber, load_sound_data, read_wav_file,
    write_wav, resample_audio, find_pattern_in_file, replace_bytes_in_file
)

class AudioExtractor:
    def __init__(self, root):
        self.root = root
        self.root.title("Audio Extractor")
        self.root.geometry("900x700")

        self.uber_file = None
        self.samp_file = None
        self.extracted_sounds = []
        self.loaded_sounds = []
        self.sound_checkboxes = []
        self.sdir_temp_path = None

        self.create_widgets()

    def create_widgets(self):
        frame = tk.Frame(self.root, padx=20, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)

        file_input_frame = tk.Frame(frame, relief=tk.RIDGE, bd=2, padx=10, pady=10)
        file_input_frame.pack(fill=tk.X, pady=10)

        uber_frame = tk.Frame(file_input_frame)
        uber_frame.pack(fill=tk.X, pady=5)

        self.uber_entry = tk.Entry(uber_frame)
        self.uber_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.uber_entry.insert(0, "No .UBER file selected (drag & drop or browse)")
        self.uber_entry.config(state='readonly')

        uber_btn = tk.Button(uber_frame, text="Browse UBER...", command=self.browse_uber, width=15)
        uber_btn.pack(side=tk.RIGHT)

        samp_frame = tk.Frame(file_input_frame)
        samp_frame.pack(fill=tk.X, pady=5)

        self.samp_entry = tk.Entry(samp_frame)
        self.samp_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.samp_entry.insert(0, "No .SAMP file selected (drag & drop or browse)")
        self.samp_entry.config(state='readonly')

        samp_btn = tk.Button(samp_frame, text="Browse SAMP...", command=self.browse_samp, width=15)
        samp_btn.pack(side=tk.RIGHT)

        try:
            file_input_frame.drop_target_register('DND_Files')
            file_input_frame.dnd_bind('<<Drop>>', lambda e: self.on_drop_combined(e))

            uber_frame.drop_target_register('DND_Files')
            uber_frame.dnd_bind('<<Drop>>', lambda e: self.on_drop_combined(e))

            samp_frame.drop_target_register('DND_Files')
            samp_frame.dnd_bind('<<Drop>>', lambda e: self.on_drop_combined(e))

            self.uber_entry.drop_target_register('DND_Files')
            self.uber_entry.dnd_bind('<<Drop>>', lambda e: self.on_drop_combined(e))

            self.samp_entry.drop_target_register('DND_Files')
            self.samp_entry.dnd_bind('<<Drop>>', lambda e: self.on_drop_combined(e))
        except:
            pass

        button_frame = tk.Frame(frame)
        button_frame.pack(pady=15)

        self.extract_wav_btn = tk.Button(button_frame, text="Extract (WAV)", command=self.extract,
                                          width=15, height=2, bg="#28a745", fg="white")
        self.extract_wav_btn.pack(side=tk.LEFT, padx=10)

        self.extract_dsp_btn = tk.Button(button_frame, text="Extract (DSP)", command=self.extract_dsp,
                                          width=15, height=2, bg="#17a2b8", fg="white")
        self.extract_dsp_btn.pack(side=tk.LEFT, padx=10)

        self.rebuild_btn = tk.Button(button_frame, text="Rebuild", command=self.rebuild,
                                      width=15, height=2, bg="#6c757d", fg="white")
        self.rebuild_btn.pack(side=tk.LEFT, padx=10)

        progress_frame = tk.Frame(frame)
        progress_frame.pack(fill=tk.X, pady=(0, 10))

        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate', length=400)
        self.progress_bar.pack()
        self.progress_label = tk.Label(progress_frame, text="", font=("Arial", 9))
        self.progress_label.pack()

        content_frame = tk.Frame(frame)
        content_frame.pack(fill=tk.BOTH, expand=True)

        left_frame = tk.Frame(content_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        sounds_label = tk.Label(left_frame, text="Loaded Sounds:", anchor='w')
        sounds_label.pack(fill=tk.X, pady=(0, 5))

        sounds_frame = tk.Frame(left_frame, relief=tk.SUNKEN, bd=2)
        sounds_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.sounds_canvas = tk.Canvas(sounds_frame, height=200)
        sounds_scrollbar = tk.Scrollbar(sounds_frame, orient="vertical", command=self.sounds_canvas.yview)
        self.sounds_scrollable_frame = tk.Frame(self.sounds_canvas)

        self.sounds_scrollable_frame.bind(
            "<Configure>",
            lambda e: self.sounds_canvas.configure(scrollregion=self.sounds_canvas.bbox("all"))
        )

        self.sounds_canvas.create_window((0, 0), window=self.sounds_scrollable_frame, anchor="nw")
        self.sounds_canvas.configure(yscrollcommand=sounds_scrollbar.set)

        self.sounds_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.sounds_canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.sounds_canvas.bind_all("<Button-5>", self._on_mousewheel)

        self.sounds_canvas.pack(side="left", fill="both", expand=True)
        sounds_scrollbar.pack(side="right", fill="y")

        selection_btn_frame = tk.Frame(left_frame)
        selection_btn_frame.pack(fill=tk.X, pady=(0, 5))

        select_all_btn = tk.Button(selection_btn_frame, text="Select All",
                                   command=self.select_all_sounds, width=12)
        select_all_btn.pack(side=tk.LEFT, padx=5)

        select_none_btn = tk.Button(selection_btn_frame, text="Select None",
                                    command=self.select_none_sounds, width=12)
        select_none_btn.pack(side=tk.LEFT, padx=5)

        right_frame = tk.Frame(content_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        status_label = tk.Label(right_frame, text="Status:", anchor='w')
        status_label.pack(fill=tk.X, pady=(0, 5))

        status_frame = tk.Frame(right_frame, relief=tk.SUNKEN, bd=2)
        status_frame.pack(fill=tk.BOTH, expand=True)

        self.status_text = scrolledtext.ScrolledText(status_frame, wrap=tk.WORD, height=20,
                                                      relief=tk.FLAT, bd=0)
        self.status_text.pack(fill=tk.BOTH, expand=True)

        self.update_status()

    def on_drop_combined(self, event):
        files = self.parse_drop_files(event.data)
        if not files:
            return

        uber_found = False
        samp_found = False

        for file_path in files:
            if file_path.upper().endswith('.UBER'):
                self.uber_file = file_path
                self.uber_entry.config(state='normal')
                self.uber_entry.delete(0, tk.END)
                self.uber_entry.insert(0, file_path)
                self.uber_entry.config(state='readonly')
                uber_found = True
            elif file_path.upper().endswith('.SAMP'):
                self.samp_file = file_path
                self.samp_entry.config(state='normal')
                self.samp_entry.delete(0, tk.END)
                self.samp_entry.insert(0, file_path)
                self.samp_entry.config(state='readonly')
                samp_found = True

        if not uber_found and not samp_found:
            messagebox.showerror("Invalid Files", "Please drop .UBER and/or .SAMP files")
        else:
            self.update_status()

    def parse_drop_files(self, data):
        files = []
        if isinstance(data, str):
            data = data.strip()
            if data.startswith('{'):
                parts = data.split('} {')
                files = [f.strip('{}').strip() for f in parts]
            elif ' ' in data and not os.path.exists(data):
                potential_files = data.split()
                files = [f for f in potential_files if os.path.exists(f)]
                if not files:
                    files = [data]
            else:
                files = [data]
        elif isinstance(data, tuple):
            files = list(data)
        elif isinstance(data, list):
            files = data
        return files

    def browse_uber(self):
        file_path = filedialog.askopenfilename(
            title="Select UBER File",
            filetypes=[("UBER Files", "*.UBER"), ("All Files", "*.*")]
        )
        if file_path:
            self.uber_file = file_path
            self.uber_entry.config(state='normal')
            self.uber_entry.delete(0, tk.END)
            self.uber_entry.insert(0, file_path)
            self.uber_entry.config(state='readonly')
            self.update_status()

    def browse_samp(self):
        file_path = filedialog.askopenfilename(
            title="Select SAMP File",
            filetypes=[("SAMP Files", "*.SAMP"), ("All Files", "*.*")]
        )
        if file_path:
            self.samp_file = file_path
            self.samp_entry.config(state='normal')
            self.samp_entry.delete(0, tk.END)
            self.samp_entry.insert(0, file_path)
            self.samp_entry.config(state='readonly')
            self.update_status()

    def update_status(self):
        self.status_text.delete(1.0, tk.END)
        if not self.uber_file and not self.samp_file:
            self.status_text.insert(tk.END, "Please Browse for .UBER & .SAMP files.")
        elif self.uber_file and not self.samp_file:
            self.status_text.insert(tk.END, "Please Browse for .SAMP file")
        elif not self.uber_file and self.samp_file:
            self.status_text.insert(tk.END, "Please Browse for .UBER file")
        else:
            self.status_text.insert(tk.END, "Files loaded. Auto-loading sound data...")
            self.root.update()
            self.auto_load()

    def _on_mousewheel(self, event):
        if event.num == 5 or event.delta < 0:
            self.sounds_canvas.yview_scroll(1, "units")
        elif event.num == 4 or event.delta > 0:
            self.sounds_canvas.yview_scroll(-1, "units")

    def select_all_sounds(self):
        for var in self.sound_checkboxes:
            var.set(True)

    def select_none_sounds(self):
        for var in self.sound_checkboxes:
            var.set(False)

    def auto_load(self):
        try:
            self.sdir_temp_path = extract_sdir_from_uber(self.uber_file, silent=True)

            if not self.sdir_temp_path or not os.path.exists(self.sdir_temp_path):
                self.status_text.insert(tk.END, "\nERROR: Could not extract SDIR file")
                return

            self.loaded_sounds = load_sound_data(self.sdir_temp_path, self.samp_file)
            self.populate_sound_list()

            if self.sdir_temp_path and os.path.exists(self.sdir_temp_path):
                os.remove(self.sdir_temp_path)
                self.sdir_temp_path = None

            self.status_text.insert(tk.END, f"\nLoaded {len(self.loaded_sounds)} sound(s).\n")
            self.status_text.insert(tk.END, "Select sounds and click Extract (WAV) or Extract (DSP).")

        except Exception as e:
            self.status_text.insert(tk.END, f"\nERROR during auto-load: {str(e)}")
            if self.sdir_temp_path and os.path.exists(self.sdir_temp_path):
                os.remove(self.sdir_temp_path)
                self.sdir_temp_path = None

    def populate_sound_list(self):
        for widget in self.sounds_scrollable_frame.winfo_children():
            widget.destroy()

        self.sound_checkboxes = []

        base_filename = os.path.splitext(os.path.basename(self.uber_file))[0] if self.uber_file else "sound"

        for sound_info in self.loaded_sounds:
            var = tk.BooleanVar(value=True)
            self.sound_checkboxes.append(var)

            sound_frame = tk.Frame(self.sounds_scrollable_frame)
            sound_frame.pack(fill=tk.X, padx=5, pady=2)

            cb = tk.Checkbutton(sound_frame, variable=var, text=f"{base_filename}_{sound_info['index']:02d}")
            cb.pack(side=tk.LEFT)

            info_label = tk.Label(sound_frame,
                                 text=f"- {sound_info['sample_rate']} Hz, {sound_info['duration']:.2f}s")
            info_label.pack(side=tk.LEFT)

            preview_btn = tk.Button(sound_frame, text="Preview",
                                   command=lambda s=sound_info: self.preview_loaded_sound(s))
            preview_btn.pack(side=tk.LEFT, padx=5)

    def preview_loaded_sound(self, sound_info):
        import tempfile
        temp_wav = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        temp_wav.close()

        write_wav(temp_wav.name, sound_info['pcm_samples'], sound_info['sample_rate'])
        self.preview_sound(temp_wav.name)

    def preview_sound(self, wav_path):
        if not os.path.exists(wav_path):
            messagebox.showerror("Error", "WAV file not found")
            return

        system = platform.system()
        try:
            if system == "Windows":
                os.startfile(wav_path)
            elif system == "Darwin":
                subprocess.run(["open", wav_path])
            else:
                subprocess.run(["xdg-open", wav_path])
        except Exception as e:
            messagebox.showerror("Error", f"Could not preview sound: {str(e)}")

    def extract(self):
        if not self.loaded_sounds:
            messagebox.showwarning("No Sounds Loaded", "Please load UBER and SAMP files first")
            return

        selected_indices = [i for i, var in enumerate(self.sound_checkboxes) if var.get()]

        if not selected_indices:
            messagebox.showwarning("No Sounds Selected", "Please select at least one sound to extract")
            return

        self.status_text.insert(tk.END, f"\nExtracting {len(selected_indices)} selected sound(s)...\n")
        self.progress_bar['value'] = 0
        self.progress_bar['maximum'] = len(selected_indices)
        self.root.update()

        try:
            base_name = os.path.splitext(self.uber_file)[0]
            self.extracted_sounds = []

            for progress_idx, idx in enumerate(selected_indices):
                sound_info = self.loaded_sounds[idx]
                wav_path = f"{base_name}_{sound_info['index']:02d}.wav"
                dsp_path = f"{base_name}_{sound_info['index']:02d}.dsp"

                write_wav(wav_path, sound_info['pcm_samples'], sound_info['sample_rate'])

                extracted_info = {
                    'index': sound_info['index'],
                    'path': wav_path,
                    'dsp_path': dsp_path,
                    'dsp_data': sound_info['dsp_data'],
                    'sample_rate': sound_info['sample_rate'],
                    'num_samples': sound_info['num_samples'],
                    'duration': sound_info['duration']
                }
                self.extracted_sounds.append(extracted_info)

                self.status_text.insert(tk.END, f"\nExtracted Sound {sound_info['index']:02d}: {os.path.basename(wav_path)}")
                self.status_text.insert(tk.END, f"\n  Sample Rate: {sound_info['sample_rate']} Hz")
                self.status_text.insert(tk.END, f"\n  Duration: {sound_info['duration']:.2f}s\n")

                self.progress_bar['value'] = progress_idx + 1
                self.progress_label['text'] = f"Extracted {progress_idx + 1}/{len(selected_indices)}"
                self.root.update()

            self.root.update()

            self.status_text.insert(tk.END, f"\n{'='*54}\nExtraction complete! Created {len(selected_indices)} WAV file(s).")
            self.root.update()

            self.progress_bar['value'] = 0
            self.progress_label['text'] = ""

        except Exception as e:
            self.status_text.insert(tk.END, f"\n\nERROR: {str(e)}")
            self.progress_bar['value'] = 0
            self.progress_label['text'] = ""
            messagebox.showerror("Extraction Error", str(e))

    def extract_dsp(self):
        if not self.loaded_sounds:
            messagebox.showwarning("No Sounds Loaded", "Please load UBER and SAMP files first")
            return

        selected_indices = [i for i, var in enumerate(self.sound_checkboxes) if var.get()]

        if not selected_indices:
            messagebox.showwarning("No Sounds Selected", "Please select at least one sound to extract")
            return

        self.status_text.insert(tk.END, f"\nExtracting {len(selected_indices)} selected sound(s) as DSP...\n")
        self.progress_bar['value'] = 0
        self.progress_bar['maximum'] = len(selected_indices)
        self.root.update()

        try:
            base_name = os.path.splitext(self.uber_file)[0]

            for progress_idx, idx in enumerate(selected_indices):
                sound_info = self.loaded_sounds[idx]
                dsp_path = f"{base_name}_{sound_info['index']:02d}.dsp"

                with open(dsp_path, 'wb') as dsp:
                    dsp.write(sound_info['dsp_data'])

                self.status_text.insert(tk.END, f"\nExtracted Sound {sound_info['index']:02d}: {os.path.basename(dsp_path)}")
                self.status_text.insert(tk.END, f"\n  Sample Rate: {sound_info['sample_rate']} Hz")
                self.status_text.insert(tk.END, f"\n  Duration: {sound_info['duration']:.2f}s\n")

                self.progress_bar['value'] = progress_idx + 1
                self.progress_label['text'] = f"Extracted {progress_idx + 1}/{len(selected_indices)}"
                self.root.update()

            self.root.update()

            self.status_text.insert(tk.END, f"\n{'='*54}\nExtraction complete! Created {len(selected_indices)} DSP file(s).")
            self.root.update()

            self.progress_bar['value'] = 0
            self.progress_label['text'] = ""

        except Exception as e:
            self.status_text.insert(tk.END, f"\n\nERROR: {str(e)}")
            self.progress_bar['value'] = 0
            self.progress_label['text'] = ""
            messagebox.showerror("Extraction Error", str(e))

    def rebuild(self):
        if not self.loaded_sounds:
            messagebox.showwarning("No Sounds Loaded", "Please load UBER and SAMP files first")
            return

        if not self.uber_file or not self.samp_file:
            messagebox.showwarning("Missing Files", "UBER and SAMP files are required for rebuild")
            return

        confirm = messagebox.askyesno(
            "Rebuild Confirmation",
            "Are you sure all sounds are as close as possible to the original lengths?\n\n"
            "Longer sounds will be trimmed and may be cut off.\n"
            "Shorter sounds will have padding and be fine.",
            icon='warning'
        )

        if not confirm:
            return

        base_name = os.path.splitext(self.uber_file)[0]

        sounds_to_rebuild = []
        for sound_info in self.loaded_sounds:
            wav_path = f"{base_name}_{sound_info['index']:02d}.wav"
            dsp_path = f"{base_name}_{sound_info['index']:02d}.dsp"

            if os.path.exists(wav_path) or os.path.exists(dsp_path):
                rebuild_info = {
                    'index': sound_info['index'],
                    'wav_path': wav_path,
                    'dsp_path': dsp_path,
                    'dsp_data': sound_info['dsp_data'],
                    'sample_rate': sound_info['sample_rate']
                }
                sounds_to_rebuild.append(rebuild_info)

        if not sounds_to_rebuild:
            messagebox.showwarning("No Files to Rebuild",
                "No WAV or DSP files found for rebuilding.\n"
                "Please extract sounds or place edited files in the same directory as the UBER file.")
            return

        self.status_text.insert(tk.END, "\nStarting rebuild with UBER and SAMP patching...\n")
        self.status_text.insert(tk.END, f"Found {len(sounds_to_rebuild)} sound(s) to rebuild\n")
        self.progress_bar['value'] = 0
        self.progress_bar['maximum'] = len(sounds_to_rebuild)
        self.root.update()

        try:
            converted_count = 0
            for progress_idx, sound_info in enumerate(sounds_to_rebuild):
                wav_path = sound_info['wav_path']
                dsp_path = sound_info['dsp_path']
                original_dsp_data = sound_info['dsp_data']

                wav_exists = os.path.exists(wav_path)
                dsp_exists = os.path.exists(dsp_path)

                if not wav_exists and not dsp_exists:
                    self.status_text.insert(tk.END,
                        f"\nSkipped Sound {sound_info['index']:02d}: Neither WAV nor DSP file found")
                    continue

                self.status_text.insert(tk.END,
                    f"\n\nProcessing Sound {sound_info['index']:02d}")

                if dsp_exists and not wav_exists:
                    self.status_text.insert(tk.END, f": Using existing DSP file")
                    with open(dsp_path, 'rb') as dsp:
                        new_dsp_data = dsp.read()

                    self.status_text.insert(tk.END,
                        f"\n  Step 1: Loaded existing DSP ({len(new_dsp_data)} bytes)")
                else:
                    self.status_text.insert(tk.END, f": {os.path.basename(wav_path)}")

                    samples, wav_sample_rate = read_wav_file(wav_path)
                    original_sample_rate = sound_info['sample_rate']

                    if wav_sample_rate != original_sample_rate:
                        self.status_text.insert(tk.END,
                            f"\n  Resampling from {wav_sample_rate} Hz to {original_sample_rate} Hz...")
                        samples = resample_audio(samples, wav_sample_rate, original_sample_rate)

                    num_samples = len(samples)

                    coefficients = original_dsp_data[0x1C:0x3C]
                    adpcm_data = encode_dsp_adpcm(samples, coefficients)
                    num_nibbles = len(adpcm_data) * 2
                    ps = original_dsp_data[0x3F]

                    new_dsp_data = create_dsp_file(num_samples, num_nibbles, original_sample_rate,
                                                    coefficients, ps, adpcm_data)

                    with open(dsp_path, 'wb') as dsp:
                        dsp.write(new_dsp_data)

                    self.status_text.insert(tk.END,
                        f"\n  Step 1: Converted to DSP ({len(new_dsp_data)} bytes)")

                pattern_for_uber = original_dsp_data[0x1C:0x3C]
                self.status_text.insert(tk.END,
                    f"\n  Step 2: Searching for pattern in UBER (bytes 0x1C-0x3B)...")

                uber_offset = find_pattern_in_file(self.uber_file, pattern_for_uber)
                if uber_offset is not None:
                    replacement_data = new_dsp_data[0x1C:0x3C]
                    replace_bytes_in_file(self.uber_file, uber_offset, replacement_data)
                    self.status_text.insert(tk.END,
                        f"\n  Step 3: Replaced in UBER at offset 0x{uber_offset:X}")
                else:
                    self.status_text.insert(tk.END,
                        f"\n  Step 3: Pattern not found in UBER - skipping UBER patch")

                pattern_for_samp = original_dsp_data[0x60:]
                self.status_text.insert(tk.END,
                    f"\n  Step 4: Searching for audio data in SAMP (from offset 0x60)...")

                samp_offset = find_pattern_in_file(self.samp_file, pattern_for_samp)
                if samp_offset is not None:
                    new_audio_data = new_dsp_data[0x60:]
                    original_length = len(pattern_for_samp)
                    new_length = len(new_audio_data)

                    if new_length < original_length:
                        padding_needed = original_length - new_length
                        new_audio_data = new_audio_data + (b'\x00' * padding_needed)
                        self.status_text.insert(tk.END,
                            f"\n  Step 5: Added {padding_needed} bytes padding to match original length")
                    elif new_length > original_length:
                        new_audio_data = new_audio_data[:original_length]
                        self.status_text.insert(tk.END,
                            f"\n  Step 5: Trimmed {new_length - original_length} bytes to match original length")
                    else:
                        self.status_text.insert(tk.END,
                            f"\n  Step 5: Length matches exactly ({new_length} bytes)")

                    replace_bytes_in_file(self.samp_file, samp_offset, new_audio_data)
                    self.status_text.insert(tk.END,
                        f"\n  Step 6: Replaced in SAMP at offset 0x{samp_offset:X}")
                else:
                    self.status_text.insert(tk.END,
                        f"\n  Step 5: Audio data not found in SAMP - skipping SAMP patch")

                converted_count += 1

                self.progress_bar['value'] = progress_idx + 1
                self.progress_label['text'] = f"Processing {progress_idx + 1}/{len(sounds_to_rebuild)}"
                self.root.update()

            self.status_text.insert(tk.END,
                f"\n\n{'='*53}\nRebuild complete! Processed {converted_count} sound(s).")
            self.status_text.insert(tk.END,
                f"\nUBER and SAMP files have been patched with new audio data.")

            # Clean up generated DSP files (keep DSPs without WAVs - those are edited raw DSPs)
            deleted_dsp_count = 0
            uber_dir = os.path.dirname(self.uber_file) or '.'
            for dsp_file in Path(uber_dir).glob("*.dsp"):
                wav_file = dsp_file.with_suffix('.wav')
                if wav_file.exists():
                    dsp_file.unlink()
                    deleted_dsp_count += 1

            if deleted_dsp_count > 0:
                self.status_text.insert(tk.END,
                    f"\nCleaned up {deleted_dsp_count} generated DSP file(s).")

            self.status_text.insert(tk.END,
                f"\n\nRefreshing loaded sounds...")

            self.progress_bar['value'] = 0
            self.progress_label['text'] = "Refreshing..."
            self.root.update()

            self.auto_load()

            self.progress_bar['value'] = 0
            self.progress_label['text'] = ""

        except Exception as e:
            self.status_text.insert(tk.END, f"\n\nERROR: {str(e)}")
            import traceback
            self.status_text.insert(tk.END, f"\n{traceback.format_exc()}")
            self.progress_bar['value'] = 0
            self.progress_label['text'] = ""
            messagebox.showerror("Rebuild Error", str(e))

def main():
    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    except ImportError:
        root = tk.Tk()
        print("Warning: tkinterdnd2 not available. Drag and drop will not work.")

    app = AudioExtractor(root)
    root.mainloop()

if __name__ == "__main__":
    main()
