import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk
from tkinter import font as tkfont
import os
import struct
import subprocess
import platform
import zipfile
import concurrent.futures
import multiprocessing
import shutil
import tempfile
import threading
from pathlib import Path

from dsp_codec import (
    encode_dsp_adpcm, create_dsp_file, calculate_coefficients, encode_ps2_adpcm,
    apply_ps2_frame_flag_template
)
from file_operations import (
    extract_sdir_from_uber, load_sound_data, read_wav_file,
    write_wav, resample_audio, find_pattern_in_file, replace_bytes_in_file,
    append_wii_sound_to_uber_samp, append_gc_sound_to_sdir_samp,
    append_ps2_sound_to_uber_samp, resize_wii_sound_in_uber_samp,
    resize_gc_sound_in_sdir_samp, resize_ps2_sound_in_uber_samp,
    bulk_resize_ps2_sounds_in_uber_samp,
    get_pcm_samples, get_ps2_sdir_entries_from_uber,
    write_ps2_rebuild_debug_dump, build_ps2_replacement_from_file,
    get_ps2_uber_sound_name_map, get_wii_uber_sound_name_map,
    get_ps2_uber_random_config_map,
    append_ps2_uber_cue, append_wii_uber_cue,
    set_wii_loop_flags_for_sounds, set_ps2_loop_flags_for_sounds, set_ps2_uber_sound_name,
    set_ps2_uber_random_cue, set_ps2_uber_ambient_full_cue
)

class AudioExtractor:
    def __init__(self, root):
        self.root = root
        self.root.title("GZ Sound Manager [v3.0]")
        self.root.geometry("900x700")

        self.uber_file = None
        self.samp_file = None
        self.extracted_sounds = []
        self.loaded_sounds = []
        self.sound_checkboxes = []
        self.sound_checkbox_widgets = []
        self.show_names_var = tk.BooleanVar(value=True)
        self.sound_filter_var = tk.StringVar()
        self.sound_row_height = 28
        self.sound_list_font = None
        self.sdir_temp_path = None
        self.pending_sound_option_indices = set()
        self.random_pick_context = None

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
        self.uber_entry.insert(0, "No .UBER/SDIR file selected (drag & drop or browse)")
        self.uber_entry.config(state='readonly')

        uber_btn = tk.Button(uber_frame, text="Browse...", command=self.browse_uber, width=15)
        uber_btn.pack(side=tk.RIGHT)

        samp_frame = tk.Frame(file_input_frame)
        samp_frame.pack(fill=tk.X, pady=5)

        self.samp_entry = tk.Entry(samp_frame)
        self.samp_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.samp_entry.insert(0, "No .SAMP file selected (drag & drop or browse)")
        self.samp_entry.config(state='readonly')

        samp_btn = tk.Button(samp_frame, text="Browse...", command=self.browse_samp, width=15)
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

        self.extract_dsp_btn = tk.Button(button_frame, text="Extract (RAW)", command=self.extract_dsp,
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

        sounds_header_frame = tk.Frame(left_frame)
        sounds_header_frame.pack(fill=tk.X, pady=(0, 5))

        sounds_label = tk.Label(sounds_header_frame, text="[Loaded Sounds]", anchor='w')
        sounds_label.pack(side=tk.LEFT)

        show_names_check = tk.Checkbutton(
            sounds_header_frame,
            variable=self.show_names_var,
            text="- Show Names",
            command=self.update_sound_display_names
        )
        show_names_check.pack(side=tk.LEFT, padx=(10, 0))

        save_options_btn = tk.Button(
            sounds_header_frame,
            text="Save",
            command=self.save_sound_option_edits,
            width=7
        )
        save_options_btn.pack(side=tk.LEFT, padx=(8, 0))

        sounds_frame = tk.Frame(left_frame, relief=tk.SUNKEN, bd=2)
        sounds_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.sounds_canvas = tk.Canvas(sounds_frame, height=200, bg="white", highlightthickness=0)
        sounds_scrollbar = tk.Scrollbar(sounds_frame, orient="vertical", command=self.on_sound_scroll)
        self.sounds_canvas.configure(yscrollcommand=sounds_scrollbar.set)
        self.sound_list_font = tkfont.nametofont("TkDefaultFont")

        self.sounds_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.sounds_canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.sounds_canvas.bind_all("<Button-5>", self._on_mousewheel)
        self.sounds_canvas.bind("<Configure>", self.on_sounds_canvas_configure)
        self.sounds_canvas.bind("<Button-1>", self.on_sounds_canvas_click)

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

        filter_label = tk.Label(selection_btn_frame, text="Filter:")
        filter_label.pack(side=tk.LEFT, padx=(15, 4))

        filter_entry = tk.Entry(selection_btn_frame, textvariable=self.sound_filter_var, width=28)
        filter_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.sound_filter_var.trace_add("write", self.on_sound_filter_changed)

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
            if file_path.upper().endswith('.UBER') or file_path.upper().endswith('.SDIR'):
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
            messagebox.showerror("Invalid Files", "Please drop .UBER/.SDIR and/or .SAMP files")
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
            parent=self.root,
            title="Select UBER/SDIR File",
            filetypes=[("UBER/SDIR Files", "*.UBER *.SDIR"), ("All Files", "*.*")]
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
            parent=self.root,
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
            self.status_text.insert(tk.END, "Please Browse for .UBER/SDIR & .SAMP files.")
        elif self.uber_file and not self.samp_file:
            self.status_text.insert(tk.END, "Please Browse for .SAMP file")
        elif not self.uber_file and self.samp_file:
            self.status_text.insert(tk.END, "Please Browse for .UBER/SDIR file")
        else:
            self.status_text.insert(tk.END, "Files loaded. Auto-loading sound data...")
            self.root.update()
            self.auto_load()

    def _on_mousewheel(self, event):
        if event.num == 5 or event.delta < 0:
            self.sounds_canvas.yview_scroll(1, "units")
        elif event.num == 4 or event.delta > 0:
            self.sounds_canvas.yview_scroll(-1, "units")
        self.draw_visible_sounds()

    def on_sound_scroll(self, *args):
        self.sounds_canvas.yview(*args)
        self.draw_visible_sounds()

    def on_sounds_canvas_configure(self, _event=None):
        self.update_sound_scrollregion()
        self.draw_visible_sounds()

    def update_sound_scrollregion(self):
        total_height = max(1, len(self.get_filtered_sound_indices()) * self.sound_row_height)
        self.sounds_canvas.configure(scrollregion=(0, 0, 1, total_height))

    def on_sound_filter_changed(self, *_args):
        self.sounds_canvas.yview_moveto(0)
        self.update_sound_scrollregion()
        self.draw_visible_sounds()

    def get_filtered_sound_indices(self):
        filter_text = self.sound_filter_var.get().strip().lower()
        if not filter_text:
            return list(range(len(self.loaded_sounds)))

        filtered_indices = []
        for index, sound_info in enumerate(self.loaded_sounds):
            searchable_parts = [
                str(sound_info.get('index', '')),
                self.get_original_sound_stem(sound_info),
                self.get_sound_display_name(sound_info, use_names=True),
                self.get_sound_display_name(sound_info, use_names=False),
                str(sound_info.get('sample_rate', '')),
                f"{sound_info.get('duration', 0):.2f}",
            ]
            searchable_parts.extend(sound_info.get('uber_names') or [])
            if sound_info.get('custom_name'):
                searchable_parts.append(sound_info['custom_name'])

            searchable_text = " ".join(searchable_parts).lower()
            if filter_text in searchable_text:
                filtered_indices.append(index)

        return filtered_indices

    def truncate_canvas_text(self, text, max_width):
        if max_width <= 0 or not text:
            return ""
        if self.sound_list_font.measure(text) <= max_width:
            return text

        ellipsis = "..."
        available = max_width - self.sound_list_font.measure(ellipsis)
        if available <= 0:
            return ellipsis

        low = 0
        high = len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if self.sound_list_font.measure(text[:mid]) <= available:
                low = mid
            else:
                high = mid - 1
        return text[:low].rstrip() + ellipsis

    def get_sound_list_layout(self, canvas_width):
        preview_width = 68
        preview_left = max(canvas_width - preview_width - 8, 260)
        preview_right = min(preview_left + preview_width, canvas_width - 8)
        info_left = max(preview_left - 115, 150)
        name_left = 34
        name_width = max(40, info_left - name_left - 10)
        return {
            'preview_left': preview_left,
            'preview_right': preview_right,
            'info_left': info_left,
            'name_left': name_left,
            'name_right': name_left + name_width,
            'name_width': name_width,
        }

    def draw_visible_sounds(self):
        canvas = self.sounds_canvas
        canvas.delete("sound_row")

        filtered_indices = self.get_filtered_sound_indices()
        if not filtered_indices:
            return

        canvas_width = max(canvas.winfo_width(), 1)
        canvas_height = max(canvas.winfo_height(), 1)
        top = canvas.canvasy(0)
        first_row = max(0, int(top // self.sound_row_height) - 1)
        last_row = min(
            len(filtered_indices),
            int((top + canvas_height) // self.sound_row_height) + 2
        )

        layout = self.get_sound_list_layout(canvas_width)
        preview_left = layout['preview_left']
        preview_right = layout['preview_right']
        info_left = layout['info_left']
        name_left = layout['name_left']
        name_width = layout['name_width']

        for visible_row in range(first_row, last_row):
            row_index = filtered_indices[visible_row]
            sound_info = self.loaded_sounds[row_index]
            y = visible_row * self.sound_row_height
            row_top = y + 1
            row_mid = y + self.sound_row_height // 2

            if visible_row % 2:
                canvas.create_rectangle(
                    0, y, canvas_width, y + self.sound_row_height,
                    fill="#f7f7f7", outline="", tags="sound_row"
                )

            checked = self.sound_checkboxes[row_index].get()
            canvas.create_rectangle(8, row_mid - 7, 22, row_mid + 7,
                                    fill="white", outline="#666", tags="sound_row")
            if checked:
                canvas.create_text(15, row_mid, text="X", fill="black",
                                   font=self.sound_list_font, tags="sound_row")

            display_name = self.get_sound_display_name(sound_info)
            if row_index in self.pending_sound_option_indices:
                display_name = f"* {display_name}"
            name = self.truncate_canvas_text(display_name, name_width)
            canvas.create_text(name_left, row_mid, text=name, anchor="w",
                               font=self.sound_list_font, fill="black", tags="sound_row")

            info = f"- {sound_info['sample_rate']} Hz, {sound_info['duration']:.2f}s"
            canvas.create_text(info_left, row_mid, text=info, anchor="w",
                               font=self.sound_list_font, fill="black", tags="sound_row")

            canvas.create_rectangle(preview_left, row_top + 3, preview_right,
                                    row_top + self.sound_row_height - 4,
                                    fill="#eeeeee", outline="#777", tags="sound_row")
            canvas.create_text((preview_left + preview_right) // 2, row_mid,
                               text="Preview", font=self.sound_list_font,
                               fill="black", tags="sound_row")

    def on_sounds_canvas_click(self, event):
        if not self.loaded_sounds:
            return

        filtered_indices = self.get_filtered_sound_indices()
        visible_row = int(self.sounds_canvas.canvasy(event.y) // self.sound_row_height)
        if visible_row < 0 or visible_row >= len(filtered_indices):
            return
        row_index = filtered_indices[visible_row]

        canvas_width = max(self.sounds_canvas.winfo_width(), 1)
        layout = self.get_sound_list_layout(canvas_width)
        preview_left = layout['preview_left']
        preview_right = layout['preview_right']

        if preview_left <= event.x <= preview_right:
            self.preview_loaded_sound(self.loaded_sounds[row_index])
            return

        if self.random_pick_context:
            self.add_sound_to_random_pick_context(row_index)
            return

        if 8 <= event.x <= 22:
            current = self.sound_checkboxes[row_index].get()
            self.sound_checkboxes[row_index].set(not current)
            self.draw_visible_sounds()
            return

        if layout['name_left'] <= event.x <= layout['name_right']:
            self.rename_loaded_sound(row_index)
            return

        if event.x <= preview_left - 8:
            current = self.sound_checkboxes[row_index].get()
            self.sound_checkboxes[row_index].set(not current)
            self.draw_visible_sounds()

    def select_all_sounds(self):
        for var in self.sound_checkboxes:
            var.set(True)
        self.draw_visible_sounds()

    def select_none_sounds(self):
        for var in self.sound_checkboxes:
            var.set(False)
        self.draw_visible_sounds()

    def auto_load(self):
        try:
            is_sdir_file = self.uber_file.lower().endswith('.sdir')

            if is_sdir_file:
                sdir_path = self.uber_file
                should_cleanup = False
            else:
                sdir_path = extract_sdir_from_uber(self.uber_file, silent=True)
                should_cleanup = True

                if not sdir_path or not os.path.exists(sdir_path):
                    self.status_text.insert(tk.END, "\nERROR: Could not extract SDIR file")
                    return

            self.loaded_sounds = load_sound_data(sdir_path, self.samp_file)
            self.attach_uber_sound_names()
            self.populate_sound_list()

            if should_cleanup and sdir_path and os.path.exists(sdir_path):
                os.remove(sdir_path)

            self.status_text.insert(tk.END, f"\nLoaded {len(self.loaded_sounds)} sound(s).\n")
            self.status_text.insert(tk.END, "Select sounds and click Extract (WAV) or Extract (RAW).")

        except Exception as e:
            self.status_text.insert(tk.END, f"\nERROR during auto-load: {str(e)}")
            if self.sdir_temp_path and os.path.exists(self.sdir_temp_path):
                os.remove(self.sdir_temp_path)
                self.sdir_temp_path = None

    def attach_uber_sound_names(self):
        self.pending_sound_option_indices.clear()
        for sound_info in self.loaded_sounds:
            sound_info['uber_names'] = []
            sound_info.pop('custom_name', None)
            sound_info['saved_custom_name'] = ""
            loop_enabled = self.sound_has_loop_flags(sound_info)
            sound_info['loop_flags_enabled'] = loop_enabled
            sound_info['saved_loop_flags_enabled'] = loop_enabled
            sound_info['random_mode'] = sound_info.get('random_mode', 'simple')
            sound_info['random_sound_indices'] = list(sound_info.get('random_sound_indices') or [])
            sound_info['saved_random_signature'] = (
                sound_info['random_mode'],
                tuple(sound_info['random_sound_indices'])
            )

        if not self.uber_file or self.uber_file.lower().endswith('.sdir'):
            return

        try:
            entry_count = max((sound_info['index'] for sound_info in self.loaded_sounds), default=-1) + 1
            if any(sound_info.get('format') == 'wii_dsp' for sound_info in self.loaded_sounds):
                name_map = get_wii_uber_sound_name_map(self.uber_file, entry_count)
            else:
                name_map = get_ps2_uber_sound_name_map(self.uber_file, entry_count)
        except Exception:
            name_map = {}

        try:
            random_config_map = get_ps2_uber_random_config_map(self.uber_file, entry_count)
        except Exception:
            random_config_map = {}

        for sound_info in self.loaded_sounds:
            sound_info['uber_names'] = name_map.get(sound_info['index'], [])
            random_config = random_config_map.get(sound_info['index'])
            if random_config:
                sound_info['random_mode'] = random_config['mode']
                sound_info['random_sound_indices'] = list(random_config['indices'])
                sound_info['saved_random_signature'] = (
                    sound_info['random_mode'],
                    tuple(sound_info['random_sound_indices'])
                )
                sound_info['random_cue_name'] = random_config.get('cue_name', "")
                sound_info['random_cue_index'] = random_config.get('cue_index')
                sound_info['attached_random_cue_name'] = random_config.get('attached_cue_name', "")
                sound_info['attached_random_cue_index'] = random_config.get('attached_cue_index')

    def mark_sound_options_saved(self):
        for sound_info in self.loaded_sounds:
            sound_info['saved_custom_name'] = sound_info.get('custom_name', "")
            sound_info['saved_loop_flags_enabled'] = bool(sound_info.get('loop_flags_enabled'))
            sound_info['saved_random_signature'] = (
                sound_info.get('random_mode', 'simple'),
                tuple(sound_info.get('random_sound_indices') or [])
            )
        self.pending_sound_option_indices.clear()

    def populate_sound_list(self):
        self.sound_checkboxes = []
        self.sound_checkbox_widgets = []

        for sound_info in self.loaded_sounds:
            var = tk.BooleanVar(value=True)
            self.sound_checkboxes.append(var)

        self.sounds_canvas.yview_moveto(0)
        self.update_sound_scrollregion()
        self.draw_visible_sounds()

    def update_sound_display_names(self):
        self.draw_visible_sounds()

    def sound_has_loop_flags(self, sound_info):
        if sound_info.get('format') == 'wii_dsp':
            return bool(sound_info.get('loop_flag'))

        if sound_info.get('format') != 'ps2_adpcm':
            return False

        adpcm_data = sound_info.get('dsp_data') or b""
        if not adpcm_data:
            return False

        frame_flags = [
            adpcm_data[frame_start + 1]
            for frame_start in range(0, len(adpcm_data) - 15, 16)
        ]
        return any(flag & 0x02 for flag in frame_flags)

    def get_sound_custom_or_uber_name(self, sound_info):
        custom_name = sound_info.get('custom_name')
        if custom_name:
            return custom_name

        names = sound_info.get('uber_names') or []
        if names:
            return names[0]

        return None

    def get_rebuild_filename_stem(self):
        return Path(self.samp_file or self.uber_file).stem

    def sanitize_filename_stem(self, text):
        invalid_chars = '<>:"/\\|?*'
        sanitized = ''.join('_' if char in invalid_chars or ord(char) < 32 else char for char in text)
        sanitized = ' '.join(sanitized.split())
        sanitized = sanitized.rstrip(' .')
        return sanitized or "sound"

    def get_cue_display_label(self, sound_info):
        cue_name = self.get_sound_custom_or_uber_name(sound_info)
        if not cue_name:
            return self.get_original_sound_stem(sound_info)
        return str(cue_name).strip()

    def get_original_sound_stem(self, sound_info):
        return f"{self.get_rebuild_filename_stem()}_{sound_info['index']:02d}"

    def get_sound_display_name(self, sound_info, use_names=None):
        original_name = self.get_original_sound_stem(sound_info)
        if use_names is None:
            use_names = self.show_names_var.get()
        if not use_names:
            return original_name

        if not self.get_sound_custom_or_uber_name(sound_info):
            return original_name

        return f"{sound_info['index']}_{self.get_cue_display_label(sound_info)}"

    def get_sound_file_stem(self, sound_info, use_names=None):
        if use_names is None:
            use_names = self.show_names_var.get()

        if use_names and self.get_sound_custom_or_uber_name(sound_info):
            return self.sanitize_filename_stem(
                f"{sound_info['index']}_{self.get_cue_display_label(sound_info)}"
            )

        return self.sanitize_filename_stem(self.get_original_sound_stem(sound_info))

    def is_ps2_sound_library(self):
        if not self.uber_file or self.uber_file.lower().endswith('.sdir'):
            return False
        try:
            get_ps2_sdir_entries_from_uber(self.uber_file)
            return True
        except Exception:
            return False

    def refresh_pending_sound_option_marker(self, row_index):
        sound_info = self.loaded_sounds[row_index]
        name_changed = (
            sound_info.get('custom_name', "") != sound_info.get('saved_custom_name', "")
        )
        loop_changed = (
            bool(sound_info.get('loop_flags_enabled')) !=
            bool(sound_info.get('saved_loop_flags_enabled'))
        )
        random_changed = (
            (
                sound_info.get('random_mode', 'simple'),
                tuple(sound_info.get('random_sound_indices') or [])
            ) != sound_info.get('saved_random_signature', ('simple', ()))
        )
        if name_changed or loop_changed or random_changed:
            self.pending_sound_option_indices.add(row_index)
        else:
            self.pending_sound_option_indices.discard(row_index)

    def add_sound_to_random_pick_context(self, row_index):
        context = self.random_pick_context
        if not context:
            return

        target_index = context['target_row_index']
        target_sound_index = self.loaded_sounds[target_index]['index']
        picked_sound_index = self.loaded_sounds[row_index]['index']

        if picked_sound_index == target_sound_index:
            self.status_text.insert(tk.END, "\nRandom cue base sound is already included automatically.")
            self.status_text.see(tk.END)
            return

        random_indices = context['random_indices']
        if picked_sound_index not in random_indices:
            random_indices.append(picked_sound_index)
            context['render_list']()
            self.loaded_sounds[target_index]['random_sound_indices'] = list(random_indices)
            self.refresh_pending_sound_option_marker(target_index)
            self.draw_visible_sounds()
            self.status_text.insert(
                tk.END,
                f"\nAdded Sound {picked_sound_index} to Entry {target_sound_index}_ random sounds."
            )
            self.status_text.see(tk.END)

    def clear_random_pick_context(self, dialog=None):
        if not self.random_pick_context:
            return
        if dialog is not None and self.random_pick_context.get('dialog') is not dialog:
            return
        self.random_pick_context['add_button'].config(relief=tk.RAISED, text="Add")
        self.random_pick_context = None

    def rename_loaded_sound(self, row_index):
        sound_info = self.loaded_sounds[row_index]
        current_name = self.get_cue_display_label(sound_info)
        original_prefix = self.get_original_sound_stem(sound_info)
        if current_name == original_prefix:
            current_name = ""

        dialog = tk.Toplevel(self.root)
        dialog.title("Sound Options")
        dialog.transient(self.root)
        dialog.resizable(False, False)

        tk.Label(dialog, text=f"Entry {sound_info['index']}_", anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 0)
        )
        tk.Label(dialog, text="Name after the entry number:", anchor="w").grid(
            row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 0)
        )

        name_var = tk.StringVar(value=current_name)
        name_entry = tk.Entry(dialog, textvariable=name_var, width=38)
        name_entry.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))

        loop_var = tk.BooleanVar(value=bool(sound_info.get('loop_flags_enabled')))
        loop_format_label = "Wii" if sound_info.get('format') == 'wii_dsp' else "PS2"
        loop_check = tk.Checkbutton(
            dialog,
            text=f"Entry {sound_info['index']}_ uses {loop_format_label} loop flags",
            variable=loop_var
        )
        loop_check.grid(row=3, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))
        if sound_info.get('format') not in ('ps2_adpcm', 'wii_dsp'):
            loop_check.config(state=tk.DISABLED)

        original_random_mode = sound_info.get('random_mode', 'simple')
        original_random_indices = list(sound_info.get('random_sound_indices') or [])
        random_mode_var = tk.StringVar(value=original_random_mode)
        random_indices = list(original_random_indices)
        random_frame = tk.LabelFrame(dialog, text="Random Sounds", padx=6, pady=6)
        random_frame.grid(row=4, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))

        random_header = tk.Frame(random_frame)
        random_header.pack(fill=tk.X)
        mode_button = tk.Button(random_header, width=14)
        add_button = tk.Button(random_header, text="Add", width=8)
        mode_button.pack(side=tk.LEFT)
        add_button.pack(side=tk.LEFT, padx=(6, 0))

        cue_source_text = ""
        if sound_info.get('random_cue_name'):
            cue_source_text = f"Cue: {sound_info['random_cue_name']}"
            if sound_info.get('attached_random_cue_name'):
                cue_source_text += f" -> {sound_info['attached_random_cue_name']}"
        if cue_source_text:
            tk.Label(random_frame, text=cue_source_text, anchor="w").pack(fill=tk.X, pady=(4, 0))

        random_list_frame = tk.Frame(random_frame)
        random_list_frame.pack(fill=tk.X, pady=(6, 0))

        def get_sound_label_by_index(sound_index):
            match = next(
                (item for item in self.loaded_sounds if item['index'] == sound_index),
                None
            )
            if not match:
                return str(sound_index)
            return self.get_sound_display_name(match, use_names=True)

        def render_random_list():
            for child in random_list_frame.winfo_children():
                child.destroy()

            if not random_indices:
                tk.Label(
                    random_list_frame,
                    text="No extra random sounds selected.",
                    anchor="w"
                ).pack(fill=tk.X)
                return

            for random_index in list(random_indices):
                item_frame = tk.Frame(random_list_frame)
                item_frame.pack(fill=tk.X, pady=1)

                def remove_random(index=random_index):
                    if index in random_indices:
                        random_indices.remove(index)
                    render_random_list()
                    sound_info['random_sound_indices'] = list(random_indices)
                    sound_info['random_mode'] = random_mode_var.get()
                    self.refresh_pending_sound_option_marker(row_index)
                    self.draw_visible_sounds()

                tk.Button(item_frame, text="X", width=2, command=remove_random).pack(side=tk.LEFT)
                tk.Label(
                    item_frame,
                    text=get_sound_label_by_index(random_index),
                    anchor="w"
                ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))

        def update_mode_button():
            if random_mode_var.get() == "ambient":
                mode_button.config(text="Amb. Random")
            elif random_mode_var.get() == "amb_full":
                mode_button.config(text="Amb. Full")
            else:
                mode_button.config(text="Simple Random")

        def toggle_random_mode():
            if random_mode_var.get() == "simple":
                random_mode_var.set("ambient")
            elif random_mode_var.get() == "ambient":
                random_mode_var.set("amb_full")
            else:
                random_mode_var.set("simple")
            update_mode_button()
            sound_info['random_mode'] = random_mode_var.get()
            sound_info['random_sound_indices'] = list(random_indices)
            self.refresh_pending_sound_option_marker(row_index)
            self.draw_visible_sounds()

        def start_random_pick():
            if self.random_pick_context and self.random_pick_context.get('dialog') is dialog:
                self.clear_random_pick_context(dialog)
                return

            self.clear_random_pick_context()
            add_button.config(relief=tk.SUNKEN, text="Adding...")
            self.random_pick_context = {
                'dialog': dialog,
                'target_row_index': row_index,
                'random_indices': random_indices,
                'render_list': render_random_list,
                'add_button': add_button,
            }
            self.status_text.insert(
                tk.END,
                f"\nClick a loaded sound to add it to Entry {sound_info['index']}_ random sounds."
            )
            self.status_text.see(tk.END)

        mode_button.config(command=toggle_random_mode)
        add_button.config(command=start_random_pick)
        update_mode_button()
        render_random_list()
        if not self.is_ps2_sound_library():
            mode_button.config(state=tk.DISABLED)
            add_button.config(state=tk.DISABLED)

        result = {"accepted": False}

        def accept():
            result["accepted"] = True
            self.clear_random_pick_context(dialog)
            dialog.destroy()

        def cancel():
            self.clear_random_pick_context(dialog)
            sound_info['random_mode'] = original_random_mode
            sound_info['random_sound_indices'] = list(original_random_indices)
            self.refresh_pending_sound_option_marker(row_index)
            self.draw_visible_sounds()
            dialog.destroy()

        tk.Button(dialog, text="OK", command=accept, width=10).grid(
            row=5, column=0, padx=(8, 4), pady=(0, 8)
        )
        tk.Button(dialog, text="Cancel", command=cancel, width=10).grid(
            row=5, column=1, padx=(4, 8), pady=(0, 8)
        )
        dialog.columnconfigure(0, weight=1)
        dialog.columnconfigure(1, weight=1)
        name_entry.focus_set()
        name_entry.selection_range(0, tk.END)
        dialog.bind("<Return>", lambda _event: accept())
        dialog.bind("<Escape>", lambda _event: cancel())
        dialog.protocol("WM_DELETE_WINDOW", cancel)

        self.root.wait_window(dialog)

        if not result["accepted"]:
            return

        new_name = name_var.get()
        new_name = self.sanitize_filename_stem(new_name)
        if new_name:
            sound_info['custom_name'] = new_name
        else:
            sound_info.pop('custom_name', None)
        if sound_info.get('format') in ('ps2_adpcm', 'wii_dsp'):
            sound_info['loop_flags_enabled'] = bool(loop_var.get())
        if self.is_ps2_sound_library():
            sound_info['random_mode'] = random_mode_var.get()
            sound_info['random_sound_indices'] = list(random_indices)

        self.refresh_pending_sound_option_marker(row_index)
        self.show_names_var.set(True)
        self.draw_visible_sounds()
        self.status_text.insert(
            tk.END,
            f"\nStaged Sound {sound_info['index']} option edit. Click Save to apply."
        )
        self.status_text.see(tk.END)

    def save_sound_option_edits(self):
        if not self.loaded_sounds:
            return

        pending_name_states = {}
        pending_ps2_loop_states = {}
        pending_wii_loop_states = {}
        pending_random_states = {}
        for row_index in sorted(self.pending_sound_option_indices):
            sound_info = self.loaded_sounds[row_index]
            if (
                sound_info.get('custom_name', "") != sound_info.get('saved_custom_name', "")
            ):
                pending_name_states[sound_info['index']] = sound_info.get('custom_name', "")
            if sound_info.get('format') in ('ps2_adpcm', 'wii_dsp') and (
                bool(sound_info.get('loop_flags_enabled')) !=
                bool(sound_info.get('saved_loop_flags_enabled'))
            ):
                loop_state = bool(sound_info.get('loop_flags_enabled'))
                if sound_info.get('format') == 'ps2_adpcm':
                    pending_ps2_loop_states[sound_info['index']] = loop_state
                else:
                    pending_wii_loop_states[sound_info['index']] = loop_state
            current_random_signature = (
                sound_info.get('random_mode', 'simple'),
                tuple(sound_info.get('random_sound_indices') or [])
            )
            if current_random_signature != sound_info.get('saved_random_signature', ('simple', ())):
                if current_random_signature[1]:
                    pending_random_states[sound_info['index']] = {
                        'mode': current_random_signature[0],
                        'indices': list(current_random_signature[1]),
                    }
                elif sound_info.get('saved_random_signature', ('simple', ()))[1]:
                    messagebox.showerror(
                        "Save Sound Options Failed",
                        "Removing an existing random cue is not supported yet"
                    )
                    return

        try:
            backup_paths = []
            ps2_patched_count = 0
            wii_patched_count = 0
            renamed_cues = []
            random_cues = []
            real_name_states = {}
            sidecar_name_states = {}

            for sound_index, new_name in pending_name_states.items():
                sound_info = next(
                    (item for item in self.loaded_sounds if item['index'] == sound_index),
                    None
                )
                if sound_info and sound_info.get('format') == 'ps2_adpcm':
                    real_name_states[sound_index] = new_name
                else:
                    sidecar_name_states[sound_index] = new_name

            if real_name_states or pending_ps2_loop_states or pending_random_states:
                if not self.is_ps2_sound_library():
                    raise ValueError("Real PS2 sound option edits require a PS2 UBER/SAMP library")
                backup_paths = self.create_rebuild_backups()
            elif pending_wii_loop_states:
                backup_paths = self.create_rebuild_backups()

            for sound_index, new_name in real_name_states.items():
                if not new_name:
                    raise ValueError("Real UBER cue names cannot be blank")
                cue_index = set_ps2_uber_sound_name(
                    self.uber_file,
                    sound_index,
                    new_name
                )
                renamed_cues.append((sound_index, cue_index, new_name))

                for sound_info in self.loaded_sounds:
                    if sound_info['index'] == sound_index:
                        sound_info.pop('custom_name', None)
                        sound_info['saved_custom_name'] = ""
                        if sound_info.get('uber_names'):
                            sound_info['uber_names'][0] = new_name
                        else:
                            sound_info['uber_names'] = [new_name]
                        break

            for sound_index, new_name in sidecar_name_states.items():
                for sound_info in self.loaded_sounds:
                    if sound_info['index'] == sound_index:
                        if new_name:
                            sound_info['custom_name'] = new_name
                        else:
                            sound_info.pop('custom_name', None)
                        break

            if pending_ps2_loop_states:
                ps2_patched_count = set_ps2_loop_flags_for_sounds(
                    self.uber_file,
                    self.samp_file,
                    pending_ps2_loop_states
                )

            if pending_wii_loop_states:
                wii_patched_count = set_wii_loop_flags_for_sounds(
                    self.uber_file,
                    pending_wii_loop_states
                )

            for sound_index, random_state in pending_random_states.items():
                if random_state['mode'] == 'amb_full':
                    sound_info = next(
                        (item for item in self.loaded_sounds if item['index'] == sound_index),
                        None
                    )
                    cue_name = None
                    if sound_info:
                        cue_name = (
                            sound_info.get('custom_name') or
                            sound_info.get('random_cue_name') or
                            self.get_cue_display_label(sound_info)
                        )
                    result = set_ps2_uber_ambient_full_cue(
                        self.uber_file,
                        sound_index,
                        random_state['indices'],
                        cue_name
                    )
                else:
                    result = set_ps2_uber_random_cue(
                        self.uber_file,
                        sound_index,
                        random_state['indices'],
                        random_state['mode']
                    )
                random_cues.append(result)

            self.mark_sound_options_saved()
            self.draw_visible_sounds()

            self.status_text.insert(tk.END, "\nSaved sound options.")
            if backup_paths:
                self.status_text.insert(tk.END, "\n  Created backup file(s):")
                for backup_path in backup_paths:
                    self.status_text.insert(tk.END, f"\n    {backup_path.name}")
            if renamed_cues:
                self.status_text.insert(tk.END, f"\n  Renamed {len(renamed_cues)} real PS2 UBER cue(s):")
                for sound_index, cue_index, new_name in renamed_cues[:10]:
                    self.status_text.insert(
                        tk.END,
                        f"\n    Sound {sound_index}: cue {cue_index} -> {new_name}"
                    )
                if len(renamed_cues) > 10:
                    self.status_text.insert(tk.END, f"\n    ...and {len(renamed_cues) - 10} more")
            if pending_ps2_loop_states:
                enabled_count = sum(1 for enabled in pending_ps2_loop_states.values() if enabled)
                disabled_count = len(pending_ps2_loop_states) - enabled_count
                self.status_text.insert(
                    tk.END,
                    f"\n  Applied PS2 loop flag options to {len(pending_ps2_loop_states)} sound(s) "
                    f"({enabled_count} loop, {disabled_count} one-shot); "
                    f"{ps2_patched_count} had new frame flag changes."
                )
            if pending_wii_loop_states:
                enabled_count = sum(1 for enabled in pending_wii_loop_states.values() if enabled)
                disabled_count = len(pending_wii_loop_states) - enabled_count
                self.status_text.insert(
                    tk.END,
                    f"\n  Applied Wii loop flag options to {len(pending_wii_loop_states)} sound(s) "
                    f"({enabled_count} loop, {disabled_count} one-shot); "
                    f"{wii_patched_count} SDIR flag(s) changed."
                )
            if random_cues:
                self.status_text.insert(tk.END, f"\n  Updated {len(random_cues)} PS2 random cue(s):")
                for result in random_cues[:10]:
                    mode_label = result['mode']
                    target_indices = ", ".join(str(index) for index in result['target_indices'])
                    random_suffix = ""
                    if mode_label == "amb_full":
                        random_suffix = f"; random cue {result['random_cue_index']}"
                    self.status_text.insert(
                        tk.END,
                        f"\n    Cue {result['cue_index']} ({mode_label}) <- [{target_indices}] "
                        f"using {result['template_name']}{random_suffix}"
                    )
                if len(random_cues) > 10:
                    self.status_text.insert(tk.END, f"\n    ...and {len(random_cues) - 10} more")
            self.status_text.see(tk.END)
        except Exception as exc:
            messagebox.showerror("Save Sound Options Failed", str(exc))
            self.status_text.insert(tk.END, f"\nERROR saving sound options: {exc}")
            self.status_text.see(tk.END)

    def get_rebuild_candidate_paths(self, folder_path, sound_info, extension):
        candidates = []
        folder_path = Path(folder_path)
        index_prefix = f"{sound_info['index']}_"

        for path in sorted(folder_path.glob(f"{index_prefix}*{extension}")):
            if path.is_file() and path not in candidates:
                candidates.append(path)

        for use_names in (False, True):
            stem = self.get_sound_file_stem(sound_info, use_names=use_names)
            path = folder_path / f"{stem}{extension}"
            if path not in candidates:
                candidates.append(path)
        return candidates

    def ask_sound_folder(self, title):
        start_dir_source = self.samp_file or self.uber_file
        start_dir = os.path.dirname(start_dir_source) or "."
        return filedialog.askdirectory(
            title=title,
            initialdir=start_dir
        )

    def ask_extract_output_folder(self, title):
        start_dir_source = self.samp_file or self.uber_file
        start_dir = os.path.dirname(start_dir_source) or "."
        initial_name = Path(start_dir_source).stem if start_dir_source else "extracted_sounds"
        folder_path = filedialog.asksaveasfilename(
            title=title,
            initialdir=start_dir,
            initialfile=initial_name,
            filetypes=[("Folder Name", "*")]
        )
        if not folder_path:
            return None

        output_dir = Path(folder_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def get_available_backup_path(self, source_path):
        backup_path = Path(str(source_path) + ".bak")
        if not backup_path.exists():
            return backup_path

        counter = 1
        while True:
            numbered_backup_path = Path(str(source_path) + f".bak{counter}")
            if not numbered_backup_path.exists():
                return numbered_backup_path
            counter += 1

    def create_rebuild_backups(self):
        source_paths = []
        for path in (self.uber_file, self.samp_file):
            if not path:
                continue
            source_path = Path(path)
            if source_path.exists() and source_path not in source_paths:
                source_paths.append(source_path)

        backup_paths = []
        for source_path in source_paths:
            backup_path = self.get_available_backup_path(source_path)
            shutil.copy2(source_path, backup_path)
            backup_paths.append(backup_path)

        return backup_paths

    def preview_loaded_sound(self, sound_info):
        sound_index = sound_info.get('index', '?')
        self.status_text.insert(tk.END, f"\nPreparing preview for Sound {sound_index}...")
        self.root.update_idletasks()

        def worker():
            temp_wav = None
            try:
                temp_wav = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
                temp_wav.close()
                write_wav(temp_wav.name, get_pcm_samples(sound_info), sound_info['sample_rate'])
                self.root.after(0, lambda: self.preview_sound(temp_wav.name))
            except Exception as exc:
                error_message = str(exc)
                if temp_wav:
                    try:
                        os.unlink(temp_wav.name)
                    except OSError:
                        pass
                self.root.after(0, lambda: messagebox.showerror("Preview Error", error_message))

        threading.Thread(target=worker, daemon=True).start()

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

        output_dir = self.ask_extract_output_folder("Create/select folder for extracted WAV files")
        if not output_dir:
            return

        self.status_text.insert(tk.END, f"\nExtracting {len(selected_indices)} selected sound(s)...\n")
        self.progress_bar['value'] = 0
        self.progress_bar['maximum'] = len(selected_indices)
        self.root.update()

        self.extract_wav_btn.configure(state=tk.DISABLED)
        self.extract_dsp_btn.configure(state=tk.DISABLED)

        def ui(callback, *args):
            self.root.after(0, lambda: callback(*args))

        def set_progress(value, label):
            self.progress_bar['value'] = value
            self.progress_label['text'] = label

        def append_status(text):
            self.status_text.insert(tk.END, text)
            self.status_text.see(tk.END)

        def finish_extract(created_count, skipped_count):
            append_status(
                f"\n{'='*54}\nExtraction complete! Created {created_count} WAV file(s), skipped {skipped_count}."
                f"\nOutput folder: {output_dir}"
            )
            self.progress_bar['value'] = 0
            self.progress_label['text'] = ""
            self.extract_wav_btn.configure(state=tk.NORMAL)
            self.extract_dsp_btn.configure(state=tk.NORMAL)

        def fail_extract(error_message):
            append_status(f"\n\nERROR: {error_message}")
            self.progress_bar['value'] = 0
            self.progress_label['text'] = ""
            self.extract_wav_btn.configure(state=tk.NORMAL)
            self.extract_dsp_btn.configure(state=tk.NORMAL)
            messagebox.showerror("Extraction Error", error_message)

        def worker():
            try:
                extracted_sounds = []
                skipped_count = 0

                for progress_idx, idx in enumerate(selected_indices):
                    sound_info = self.loaded_sounds[idx]
                    file_stem = self.get_sound_file_stem(sound_info)
                    wav_path = str(output_dir / f"{file_stem}.wav")
                    dsp_path = str(output_dir / f"{file_stem}.dsp")

                    if os.path.exists(wav_path):
                        skipped_count += 1
                        ui(append_status,
                           f"\nSkipped Sound {sound_info['index']:02d}: {os.path.basename(wav_path)} already exists")
                        ui(set_progress, progress_idx + 1, f"Processed {progress_idx + 1}/{len(selected_indices)}")
                        continue

                    ui(set_progress, progress_idx, f"Decoding {progress_idx + 1}/{len(selected_indices)}")
                    write_wav(wav_path, get_pcm_samples(sound_info), sound_info['sample_rate'])

                    extracted_info = {
                        'index': sound_info['index'],
                        'path': wav_path,
                        'dsp_path': dsp_path,
                        'dsp_data': sound_info['dsp_data'],
                        'sample_rate': sound_info['sample_rate'],
                        'num_samples': sound_info['num_samples'],
                        'duration': sound_info['duration']
                    }
                    extracted_sounds.append(extracted_info)

                    ui(append_status,
                       f"\nExtracted Sound {sound_info['index']:02d}: {os.path.basename(wav_path)}"
                       f"\n  Sample Rate: {sound_info['sample_rate']} Hz"
                       f"\n  Duration: {sound_info['duration']:.2f}s\n")
                    ui(set_progress, progress_idx + 1, f"Extracted {progress_idx + 1}/{len(selected_indices)}")

                def apply_results():
                    self.extracted_sounds = extracted_sounds
                    finish_extract(len(selected_indices) - skipped_count, skipped_count)

                self.root.after(0, apply_results)

            except Exception as exc:
                error_message = str(exc)
                self.root.after(0, lambda: fail_extract(error_message))

        threading.Thread(target=worker, daemon=True).start()

    def extract_dsp(self):
        if not self.loaded_sounds:
            messagebox.showwarning("No Sounds Loaded", "Please load UBER and SAMP files first")
            return

        selected_indices = [i for i, var in enumerate(self.sound_checkboxes) if var.get()]

        if not selected_indices:
            messagebox.showwarning("No Sounds Selected", "Please select at least one sound to extract")
            return

        output_dir = self.ask_extract_output_folder("Create/select folder for extracted raw audio files")
        if not output_dir:
            return

        self.status_text.insert(tk.END, f"\nExtracting {len(selected_indices)} selected sound(s) as DSP...\n")
        self.progress_bar['value'] = 0
        self.progress_bar['maximum'] = len(selected_indices)
        self.root.update()

        try:
            skipped_count = 0

            for progress_idx, idx in enumerate(selected_indices):
                sound_info = self.loaded_sounds[idx]
                raw_ext = sound_info.get('raw_ext', '.dsp')
                file_stem = self.get_sound_file_stem(sound_info)
                dsp_path = str(output_dir / f"{file_stem}{raw_ext}")

                if os.path.exists(dsp_path):
                    skipped_count += 1
                    self.status_text.insert(tk.END,
                        f"\nSkipped Sound {sound_info['index']:02d}: {os.path.basename(dsp_path)} already exists")
                    self.progress_bar['value'] = progress_idx + 1
                    self.progress_label['text'] = f"Processed {progress_idx + 1}/{len(selected_indices)}"
                    self.root.update()
                    continue

                with open(dsp_path, 'wb') as dsp:
                    dsp.write(sound_info.get('raw_data', sound_info['dsp_data']))

                self.status_text.insert(tk.END, f"\nExtracted Sound {sound_info['index']:02d}: {os.path.basename(dsp_path)}")
                self.status_text.insert(tk.END, f"\n  Sample Rate: {sound_info['sample_rate']} Hz")
                self.status_text.insert(tk.END, f"\n  Duration: {sound_info['duration']:.2f}s\n")

                self.progress_bar['value'] = progress_idx + 1
                self.progress_label['text'] = f"Extracted {progress_idx + 1}/{len(selected_indices)}"
                self.root.update()

            self.root.update()

            created_count = len(selected_indices) - skipped_count
            self.status_text.insert(tk.END,
                f"\n{'='*54}\nExtraction complete! Created {created_count} raw audio file(s), skipped {skipped_count}."
                f"\nOutput folder: {output_dir}")
            self.root.update()

            self.progress_bar['value'] = 0
            self.progress_label['text'] = ""

        except Exception as e:
            self.status_text.insert(tk.END, f"\n\nERROR: {str(e)}")
            self.progress_bar['value'] = 0
            self.progress_label['text'] = ""
            messagebox.showerror("Extraction Error", str(e))

    def get_sound_output_base_path(self, create_dir=False):
        source_path = Path(self.samp_file or self.uber_file)
        output_dir = source_path.parent / source_path.stem
        if create_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir / source_path.stem

    def parse_sound_file_index(self, file_path, base_path):
        stem = file_path.stem
        base_prefix = base_path.name + "_"

        if stem.startswith(base_prefix):
            index_text = stem[len(base_prefix):].split("_", 1)[0]
        else:
            index_text = stem.split("_", 1)[0]

        if not index_text.isdigit():
            return None

        return int(index_text)

    def parse_append_cue_name(self, file_path, base_path):
        stem = file_path.stem
        base_prefix = base_path.name + "_"

        if stem.startswith(base_prefix):
            remainder = stem[len(base_prefix):]
        else:
            remainder = stem

        parts = remainder.split("_", 1)
        if len(parts) > 1 and parts[1].strip():
            return parts[1].strip()

        return stem

    def find_append_candidates(self, base_name):
        loaded_indices = {sound_info['index'] for sound_info in self.loaded_sounds}
        highest_loaded_index = max(loaded_indices) if loaded_indices else -1
        append_candidates = {}
        base_path = Path(base_name)
        search_dir = base_path.parent if str(base_path.parent) else Path(".")

        for file_path in search_dir.iterdir():
            if not file_path.is_file() or file_path.suffix.lower() not in (".wav", ".dsp", ".ps2adpcm"):
                continue

            index = self.parse_sound_file_index(file_path, base_path)
            if index is None or index <= highest_loaded_index or index in loaded_indices:
                continue

            append_info = append_candidates.setdefault(index, {
                'index': index,
                'cue_name': self.parse_append_cue_name(file_path, base_path),
                'wav_path': str(file_path.with_suffix(".wav")),
                'dsp_path': str(file_path.with_suffix(".dsp")),
                'ps2_path': str(file_path.with_suffix(".ps2adpcm"))
            })

            if file_path.suffix.lower() == ".wav":
                append_info['wav_path'] = str(file_path)
            elif file_path.suffix.lower() == ".ps2adpcm":
                append_info['ps2_path'] = str(file_path)
            else:
                append_info['dsp_path'] = str(file_path)

        return [append_candidates[index] for index in sorted(append_candidates)]

    def build_dsp_for_append(self, append_info):
        wav_path = append_info['wav_path']
        dsp_path = append_info['dsp_path']

        wav_exists = os.path.exists(wav_path)
        dsp_exists = os.path.exists(dsp_path)

        if dsp_exists and not wav_exists:
            with open(dsp_path, 'rb') as dsp:
                return dsp.read(), False

        if wav_exists:
            samples, wav_sample_rate = read_wav_file(wav_path)
            coefficients = calculate_coefficients(samples)
            adpcm_data = encode_dsp_adpcm(samples, coefficients)
            num_nibbles = len(adpcm_data) * 2
            ps = adpcm_data[0] if len(adpcm_data) > 0 else 0
            dsp_data = create_dsp_file(len(samples), num_nibbles, wav_sample_rate,
                                       coefficients, ps, adpcm_data)

            with open(dsp_path, 'wb') as dsp:
                dsp.write(dsp_data)

            return dsp_data, True

        raise FileNotFoundError(f"No WAV or DSP file found for Sound {append_info['index']:02d}")

    def build_ps2_for_append(self, append_info):
        wav_path = append_info['wav_path']
        ps2_path = append_info['ps2_path']

        wav_exists = os.path.exists(wav_path)
        ps2_exists = os.path.exists(ps2_path)

        if ps2_exists and not wav_exists:
            with open(ps2_path, 'rb') as raw:
                adpcm_data = raw.read()
            if "LOOP" in (append_info.get('cue_name') or "").upper():
                adpcm_data = self.set_ps2_adpcm_loop_flags(adpcm_data)
            return adpcm_data, None, False

        if wav_exists:
            samples, wav_sample_rate = read_wav_file(wav_path)
            adpcm_data = encode_ps2_adpcm(samples)
            if "LOOP" in (append_info.get('cue_name') or "").upper():
                adpcm_data = self.set_ps2_adpcm_loop_flags(adpcm_data)

            with open(ps2_path, 'wb') as raw:
                raw.write(adpcm_data)

            return adpcm_data, wav_sample_rate, True

        raise FileNotFoundError(f"No WAV or PS2 ADPCM file found for Sound {append_info['index']:02d}")

    def set_ps2_adpcm_loop_flags(self, adpcm_data):
        looped_data = bytearray(adpcm_data)
        for frame_start in range(0, len(looped_data) - 15, 16):
            looped_data[frame_start + 1] |= 0x02
        return bytes(looped_data)

    def encode_ps2_replacements_bulk(self, sounds_to_rebuild):
        jobs = []
        for sound_info in sounds_to_rebuild:
            wav_path = sound_info['wav_path']
            raw_path = sound_info['dsp_path']

            wav_exists = os.path.exists(wav_path)
            raw_exists = os.path.exists(raw_path)
            if not wav_exists and not raw_exists:
                self.status_text.insert(tk.END,
                    f"\nSkipped Sound {sound_info['index']:02d}: Neither WAV nor raw audio file found")
                continue

            jobs.append({
                'index': sound_info['index'],
                'wav_path': wav_path,
                'raw_path': raw_path,
                'sample_rate': sound_info['sample_rate'],
                'template': sound_info.get('dsp_data', b''),
                'old_length': sound_info['data_size']
            })

        if not jobs:
            return {}, 0

        self.status_text.insert(tk.END,
            f"\nEncoding {len(jobs)} PS2 replacement(s) before one bulk SAMP rebuild...\n")
        self.root.update()

        replacements = {}
        completed = 0
        max_workers = max(1, min((os.cpu_count() or 1), 8))

        def handle_result(result):
            replacements[result['index']] = {
                'adpcm_data': result['adpcm_data'],
                'sample_rate': result['sample_rate']
            }

        try:
            with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
                future_map = {
                    executor.submit(
                        build_ps2_replacement_from_file,
                        job['index'], job['wav_path'], job['raw_path'],
                        job['sample_rate'], job['template']
                    ): job
                    for job in jobs
                }

                for future in concurrent.futures.as_completed(future_map):
                    job = future_map[future]
                    result = future.result()
                    completed += 1
                    handle_result(result)

                    self.progress_bar['value'] = completed
                    self.progress_label['text'] = f"Encoding PS2 {completed}/{len(jobs)}"
                    if completed == len(jobs) or completed % 10 == 0:
                        self.root.update()
        except Exception as e:
            self.status_text.insert(tk.END,
                f"\nParallel PS2 encoding failed ({e}); falling back to single-process encoding...\n")
            self.root.update()
            replacements = {}
            completed = 0

            for job in jobs:
                result = build_ps2_replacement_from_file(
                    job['index'], job['wav_path'], job['raw_path'],
                    job['sample_rate'], job['template']
                )
                completed += 1
                handle_result(result)

                self.progress_bar['value'] = completed
                self.progress_label['text'] = f"Encoding PS2 {completed}/{len(jobs)}"
                if completed == len(jobs) or completed % 10 == 0:
                    self.root.update()

        self.status_text.insert(tk.END,
            f"\nEncoded {len(replacements)} PS2 replacement(s).")
        self.root.update()

        return replacements, len(jobs)

    def rebuild(self):
        if not self.loaded_sounds:
            messagebox.showwarning("No Sounds Loaded", "Please load UBER/SDIR and SAMP files first")
            return

        is_sdir = self.uber_file.upper().endswith('.SDIR') if self.uber_file else False

        # Check if SDIR is Wii format (has header) or GameCube format (no header)
        is_wii_sdir = False
        if is_sdir:
            with open(self.uber_file, 'rb') as f:
                header = f.read(4)
                is_wii_sdir = header[::-1] == b"SDIR"

        if not self.uber_file:
            messagebox.showwarning("Missing Files", "UBER/SDIR file is required for rebuild")
            return

        if not is_sdir and not self.samp_file:
            messagebox.showwarning("Missing Files", "SAMP file is required for rebuild with UBER files")
            return

        # GameCube SDIR needs SAMP file for audio data
        if is_sdir and not is_wii_sdir and not self.samp_file:
            messagebox.showwarning("Missing Files", "SAMP file is required for GameCube SDIR format")
            return

        confirm = messagebox.askyesno(
            "Rebuild Confirmation",
            "Rebuild will resize the SAMP data and update later sound offsets.\n\n"
            "Longer and shorter sounds are supported for Wii, GameCube, and PS2 banks.\n"
            "External game cues may still control when a sound stops playing.",
            icon='warning'
        )

        if not confirm:
            return

        selected_sound_dir = self.ask_sound_folder("Select folder containing replacement sounds")

        if not selected_sound_dir:
            return

        bank_format = self.loaded_sounds[0].get('format', 'dsp') if self.loaded_sounds else 'dsp'

        sounds_to_rebuild = []
        for sound_info in self.loaded_sounds:
            raw_ext = sound_info.get('raw_ext', '.dsp')
            wav_candidates = self.get_rebuild_candidate_paths(selected_sound_dir, sound_info, ".wav")
            raw_candidates = self.get_rebuild_candidate_paths(selected_sound_dir, sound_info, raw_ext)
            found_wav_path = next((path for path in wav_candidates if path.exists()), None)
            found_raw_path = next((path for path in raw_candidates if path.exists()), None)

            if found_wav_path:
                wav_path = str(found_wav_path)
                dsp_path = str(found_raw_path or found_wav_path.with_suffix(raw_ext))
            else:
                wav_path = str(wav_candidates[0])
                dsp_path = str(found_raw_path or raw_candidates[0])

            if os.path.exists(wav_path) or os.path.exists(dsp_path):
                rebuild_info = {
                    'index': sound_info['index'],
                    'wav_path': wav_path,
                    'dsp_path': dsp_path,
                    'dsp_data': sound_info['dsp_data'],
                    'sample_rate': sound_info['sample_rate'],
                    'format': sound_info.get('format', 'dsp'),
                    'data_offset': sound_info.get('data_offset'),
                    'data_size': sound_info.get('data_size')
                }
                sounds_to_rebuild.append(rebuild_info)

        rebuild_base_path = Path(selected_sound_dir) / self.get_rebuild_filename_stem()
        append_candidates = self.find_append_candidates(rebuild_base_path)

        if not sounds_to_rebuild and not append_candidates:
            messagebox.showwarning("No Files to Rebuild",
                "No WAV or DSP files found for rebuilding.\n"
                "Please choose the folder that contains the edited sound files.\n"
                "To append, use the next higher number, like 34_NewSound.wav or BaseName_34.wav.")
            return

        if append_candidates and not self.samp_file:
            messagebox.showwarning("Append Not Supported",
                "Appending new sounds requires a matching SAMP file.")
            return

        if append_candidates and bank_format not in ('wii_dsp', 'gc_dsp', 'ps2_adpcm'):
            messagebox.showwarning("Append Not Supported",
                "Appending new sounds is not supported for this bank format yet.")
            return

        if append_candidates and bank_format == 'gc_dsp' and not is_sdir:
            messagebox.showwarning("Append Not Supported",
                "GameCube appending requires loading the extracted SDIR file with its matching SAMP.")
            return

        if append_candidates and bank_format in ('wii_dsp', 'ps2_adpcm') and is_sdir:
            messagebox.showwarning("Append Not Supported",
                "This append mode requires loading the UBER file with its matching SAMP.")
            return

        if append_candidates:
            next_index = max(sound_info['index'] for sound_info in self.loaded_sounds) + 1
            for append_info in append_candidates:
                if append_info['index'] != next_index:
                    messagebox.showwarning("Append Number Gap",
                        f"Expected the next appended sound to be {next_index:02d}, "
                        f"but found {append_info['index']:02d}.\n\n"
                        "Please append sounds with contiguous numbers, like 34_NewSound.wav, "
                        "then 35_AnotherSound.wav.")
                    return
                next_index += 1

        if is_sdir:
            if is_wii_sdir:
                self.status_text.insert(tk.END, "\nStarting rebuild with Wii SDIR patching...\n")
            else:
                self.status_text.insert(tk.END, "\nStarting rebuild with GameCube SDIR patching...\n")
        else:
            self.status_text.insert(tk.END, "\nStarting rebuild with UBER and SAMP patching...\n")
        self.status_text.insert(tk.END, f"Found {len(sounds_to_rebuild)} sound(s) to rebuild\n")
        if append_candidates:
            display_names = []
            for info in append_candidates:
                if os.path.exists(info['wav_path']):
                    display_names.append(Path(info['wav_path']).stem)
                elif os.path.exists(info.get('ps2_path', '')):
                    display_names.append(Path(info['ps2_path']).stem)
                else:
                    display_names.append(Path(info['dsp_path']).stem)
            appended_names = ', '.join(display_names)
            self.status_text.insert(tk.END, f"Found {len(append_candidates)} new sound(s) to append: {appended_names}\n")
        self.progress_bar['value'] = 0
        self.progress_bar['maximum'] = len(sounds_to_rebuild) + len(append_candidates)
        self.root.update()

        try:
            backup_paths = self.create_rebuild_backups()
            if backup_paths:
                self.status_text.insert(tk.END, "\nCreated backup file(s):")
                for backup_path in backup_paths:
                    self.status_text.insert(tk.END, f"\n  {backup_path.name}")
                self.status_text.insert(tk.END, "\n")
                self.root.update()

            converted_count = 0
            ps2_debug_before = None
            if bank_format == 'ps2_adpcm':
                ps2_debug_before = get_ps2_sdir_entries_from_uber(self.uber_file)
            ps2_replacements = {}

            if bank_format == 'ps2_adpcm' and sounds_to_rebuild:
                self.progress_bar['value'] = 0
                self.progress_bar['maximum'] = len(sounds_to_rebuild)
                ps2_replacements, converted_count = self.encode_ps2_replacements_bulk(sounds_to_rebuild)
                sounds_to_rebuild = []

            for progress_idx, sound_info in enumerate(sounds_to_rebuild):
                wav_path = sound_info['wav_path']
                dsp_path = sound_info['dsp_path']
                original_dsp_data = sound_info['dsp_data']

                wav_exists = os.path.exists(wav_path)
                dsp_exists = os.path.exists(dsp_path)

                if not wav_exists and not dsp_exists:
                    self.status_text.insert(tk.END,
                        f"\nSkipped Sound {sound_info['index']:02d}: Neither WAV nor raw audio file found")
                    continue

                self.status_text.insert(tk.END,
                    f"\n\nProcessing Sound {sound_info['index']:02d}")

                if sound_info.get('format') == 'ps2_adpcm':
                    if dsp_exists and not wav_exists:
                        self.status_text.insert(tk.END, f": Using existing PS2 ADPCM file")
                        with open(dsp_path, 'rb') as raw:
                            new_audio_data = raw.read()

                        self.status_text.insert(tk.END,
                            f"\n  Step 1: Loaded existing PS2 ADPCM ({len(new_audio_data)} bytes)")
                    else:
                        self.status_text.insert(tk.END, f": {os.path.basename(wav_path)}")

                        samples, wav_sample_rate = read_wav_file(wav_path)
                        original_sample_rate = sound_info['sample_rate']

                        if wav_sample_rate != original_sample_rate:
                            self.status_text.insert(tk.END,
                                f"\n  Resampling from {wav_sample_rate} Hz to {original_sample_rate} Hz...")
                            samples = resample_audio(samples, wav_sample_rate, original_sample_rate)

                        new_audio_data = encode_ps2_adpcm(samples)
                        new_audio_data = apply_ps2_frame_flag_template(
                            new_audio_data, sound_info.get('dsp_data', b'')
                        )

                        with open(dsp_path, 'wb') as raw:
                            raw.write(new_audio_data)

                        self.status_text.insert(tk.END,
                            f"\n  Step 1: Converted to PS2 ADPCM ({len(new_audio_data)} bytes)")

                    ps2_replacements[sound_info['index']] = {
                        'adpcm_data': new_audio_data,
                        'sample_rate': sound_info['sample_rate']
                    }
                    old_length = sound_info['data_size']
                    self.status_text.insert(tk.END,
                        f"\n  Step 2: Queued PS2 resize from {old_length} to {len(new_audio_data)} byte(s)")

                    converted_count += 1
                    self.progress_bar['value'] = progress_idx + 1
                    self.progress_label['text'] = f"Processing {progress_idx + 1}/{len(sounds_to_rebuild)}"
                    self.root.update()
                    continue

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

                    # Calculate new coefficients from the new audio samples
                    coefficients = calculate_coefficients(samples)
                    adpcm_data = encode_dsp_adpcm(samples, coefficients)
                    num_nibbles = len(adpcm_data) * 2
                    ps = adpcm_data[0] if len(adpcm_data) > 0 else 0

                    new_dsp_data = create_dsp_file(num_samples, num_nibbles, original_sample_rate,
                                                    coefficients, ps, adpcm_data)

                    with open(dsp_path, 'wb') as dsp:
                        dsp.write(new_dsp_data)

                    self.status_text.insert(tk.END,
                        f"\n  Step 1: Converted to DSP ({len(new_dsp_data)} bytes)")

                if is_sdir:
                    old_length = sound_info['data_size']
                    if is_wii_sdir:
                        delta = resize_wii_sound_in_uber_samp(
                            self.uber_file, self.samp_file, sound_info['index'], new_dsp_data
                        )
                    elif self.samp_file:
                        delta = resize_gc_sound_in_sdir_samp(
                            self.uber_file, self.samp_file, sound_info['index'], new_dsp_data
                        )
                    else:
                        self.status_text.insert(tk.END,
                            f"\n  Step 2: SAMP file not loaded - cannot resize GameCube audio")
                        delta = 0

                    self.status_text.insert(tk.END,
                        f"\n  Step 2: Resized audio from {old_length} to {len(new_dsp_data[0x60:])} byte(s)")
                    self.status_text.insert(tk.END,
                        f"\n  Step 3: Shifted later SAMP data by {delta} byte(s)")
                else:
                    old_length = sound_info['data_size']
                    delta = resize_wii_sound_in_uber_samp(
                        self.uber_file, self.samp_file, sound_info['index'], new_dsp_data
                    )
                    self.status_text.insert(tk.END,
                        f"\n  Step 2: Resized audio from {old_length} to {len(new_dsp_data[0x60:])} byte(s)")
                    self.status_text.insert(tk.END,
                        f"\n  Step 3: Shifted later SAMP data by {delta} byte(s)")

                converted_count += 1

                self.progress_bar['value'] = progress_idx + 1
                self.progress_label['text'] = f"Processing {progress_idx + 1}/{len(sounds_to_rebuild)}"
                self.root.update()

            if ps2_replacements:
                self.status_text.insert(tk.END,
                    f"\n\nApplying {len(ps2_replacements)} PS2 replacement(s) in one SAMP rebuild...")
                self.root.update()
                delta = bulk_resize_ps2_sounds_in_uber_samp(
                    self.uber_file, self.samp_file, ps2_replacements
                )
                self.status_text.insert(tk.END,
                    f"\nShifted final SAMP size by {delta} byte(s).")
                self.root.update()

            appended_count = 0
            for append_idx, append_info in enumerate(append_candidates):
                sound_index = append_info['index']
                self.status_text.insert(tk.END,
                    f"\n\nAppending Sound {sound_index:02d}")

                if bank_format == 'ps2_adpcm':
                    new_audio_data, sample_rate, generated_raw = self.build_ps2_for_append(append_info)
                    if sample_rate is None:
                        sample_rate = self.loaded_sounds[-1]['sample_rate']

                    if generated_raw:
                        self.status_text.insert(tk.END,
                            f": Converted {os.path.basename(append_info['wav_path'])} to PS2 ADPCM")
                    else:
                        self.status_text.insert(tk.END,
                            f": Using existing PS2 ADPCM file")

                    actual_index = append_ps2_sound_to_uber_samp(
                        self.uber_file, self.samp_file, new_audio_data, sample_rate
                    )
                    cue_index = append_ps2_uber_cue(
                        self.uber_file, actual_index, append_info.get('cue_name')
                    )
                    appended_bytes = len(new_audio_data)
                else:
                    new_dsp_data, generated_dsp = self.build_dsp_for_append(append_info)
                    if generated_dsp:
                        self.status_text.insert(tk.END,
                            f": Converted {os.path.basename(append_info['wav_path'])} to DSP")
                    else:
                        self.status_text.insert(tk.END,
                            f": Using existing DSP file")

                    if bank_format == 'gc_dsp':
                        actual_index = append_gc_sound_to_sdir_samp(
                            self.uber_file, self.samp_file, new_dsp_data
                        )
                        cue_index = None
                    else:
                        actual_index = append_wii_sound_to_uber_samp(
                            self.uber_file, self.samp_file, new_dsp_data
                        )
                        cue_index = append_wii_uber_cue(
                            self.uber_file, actual_index, append_info.get('cue_name')
                        )
                    appended_bytes = len(new_dsp_data[0x60:])

                self.status_text.insert(tk.END,
                    f"\n  Added SDIR entry {actual_index:02d}")
                if bank_format in ('ps2_adpcm', 'wii_dsp') and cue_index is not None:
                    self.status_text.insert(tk.END,
                        f"\n  Added UBER cue {cue_index:02d}: {append_info.get('cue_name', '')}")
                self.status_text.insert(tk.END,
                    f"\n  Appended {appended_bytes} byte(s) to SAMP")

                appended_count += 1
                progress_value = len(sounds_to_rebuild) + append_idx + 1
                self.progress_bar['value'] = progress_value
                self.progress_label['text'] = f"Processing {progress_value}/{len(sounds_to_rebuild) + len(append_candidates)}"
                self.root.update()

            self.status_text.insert(tk.END,
                f"\n\n{'='*53}\nRebuild complete! Processed {converted_count} sound(s).")
            if append_candidates:
                self.status_text.insert(tk.END,
                    f"\nAppended {appended_count} new sound(s).")
            if is_sdir:
                self.status_text.insert(tk.END,
                    f"\nSDIR file has been patched with new audio data.")
            else:
                self.status_text.insert(tk.END,
                    f"\nUBER and SAMP files have been patched with new audio data.")

            # Clean up generated DSP files (keep DSPs without WAVs - those are edited raw DSPs)
            deleted_dsp_count = 0
            cleanup_dirs = {rebuild_base_path.parent}
            for cleanup_dir in cleanup_dirs:
                for dsp_file in cleanup_dir.glob("*.dsp"):
                    wav_file = dsp_file.with_suffix('.wav')
                    if wav_file.exists():
                        dsp_file.unlink()
                        deleted_dsp_count += 1
                for raw_file in cleanup_dir.glob("*.ps2adpcm"):
                    wav_file = raw_file.with_suffix('.wav')
                    if wav_file.exists():
                        raw_file.unlink()
                        deleted_dsp_count += 1

            if deleted_dsp_count > 0:
                self.status_text.insert(tk.END,
                    f"\nCleaned up {deleted_dsp_count} generated DSP file(s).")

            if bank_format == 'ps2_adpcm':
                debug_path = str(rebuild_base_path.with_name(f"{rebuild_base_path.name}_ps2_rebuild_debug.txt"))
                write_ps2_rebuild_debug_dump(
                    self.uber_file, self.samp_file, debug_path, ps2_debug_before
                )
                self.status_text.insert(tk.END,
                    f"\nCreated PS2 rebuild debug dump: {os.path.basename(debug_path)}")

            # Auto-zip SDIR/proj/pool files if rebuilding from SDIR
            if is_sdir:
                sdir_path = Path(self.uber_file)
                sdir_dir = sdir_path.parent
                sdir_base = sdir_path.stem

                proj_path = sdir_dir / f"{sdir_base}.proj"
                pool_path = sdir_dir / f"{sdir_base}.pool"

                files_to_zip = [sdir_path]
                if proj_path.exists():
                    files_to_zip.append(proj_path)
                if pool_path.exists():
                    files_to_zip.append(pool_path)

                if len(files_to_zip) > 1:
                    samp_dir = Path(self.samp_file).parent if self.samp_file else sdir_dir
                    zip_path = samp_dir / f"{sdir_base}.zip"

                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                        for file_path in files_to_zip:
                            zipf.write(file_path, file_path.name)

                    self.status_text.insert(tk.END,
                        f"\n\nCreated archive: {zip_path.name}")
                    file_names = [f.name for f in files_to_zip]
                    self.status_text.insert(tk.END,
                        f"\nContains: {', '.join(file_names)}")

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
    multiprocessing.freeze_support()

    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    except ImportError:
        root = tk.Tk()
        print("Warning: tkinterdnd2 not available. Drag and drop will not work.")

    root.iconbitmap(default=str(Path(__file__).resolve().parent / "gzsm.ico"))

    app = AudioExtractor(root)
    root.mainloop()

if __name__ == "__main__":
    main()
