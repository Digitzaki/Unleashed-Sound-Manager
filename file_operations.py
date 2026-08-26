import os
import struct
import wave
from dsp_codec import (
    nibbles_to_samples, decode_dsp_adpcm, create_dsp_file, decode_ps2_adpcm,
    encode_ps2_adpcm, apply_ps2_frame_flag_template
)

def get_uber_endian(uber_data):
    if uber_data[0:4] == b"UBER":
        return "<"
    return ">"

def extract_sdir_from_uber(uber_path, silent=False):
    uber_size = os.path.getsize(uber_path)
    sdir_path = None

    with open(uber_path, "rb") as uber:
        header = uber.read(4)
        endian = "<" if header == b"UBER" else ">"
        uber.seek(0x08)
        offsets = []
        offset = struct.unpack(endian + "I", uber.read(4))[0]
        offsets.append(offset)

        while uber.tell() < offsets[0]:
            offset = struct.unpack(endian + "I", uber.read(4))[0]
            offsets.append(offset)
        offsets.append(uber_size)

        i = 0
        while uber.tell() < uber_size and i < len(offsets):
            size = offsets[i+1] - uber.tell()
            outbuf = uber.read(size)

            try:
                if endian == "<":
                    file_type = outbuf[0:4].decode("ascii").lower()
                else:
                    file_type = outbuf[0:4][::-1].decode("ascii").lower()
            except:
                file_type = ""

            if file_type == "sdir":
                sdir_path = os.path.splitext(uber_path)[0] + ".sdir"
                with open(sdir_path, "wb") as out:
                    out.write(outbuf)
                break
            i += 1

    return sdir_path

def get_uber_chunk_offsets(uber_data):
    if len(uber_data) < 12:
        raise ValueError("UBER file is too small")

    endian = get_uber_endian(uber_data)
    first_offset = struct.unpack(endian + "I", uber_data[0x08:0x0C])[0]
    if first_offset < 0x0C or first_offset > len(uber_data):
        raise ValueError("Invalid UBER offset table")

    offsets = []
    pos = 0x08
    while pos < first_offset:
        offsets.append(struct.unpack(endian + "I", uber_data[pos:pos + 4])[0])
        pos += 4

    offsets.append(len(uber_data))
    return offsets

def replace_uber_chunk(uber_path, chunk_index, new_chunk_data, adjust_pointers=True):
    with open(uber_path, "rb") as uber:
        uber_data = uber.read()

    endian = get_uber_endian(uber_data)
    offsets = get_uber_chunk_offsets(uber_data)
    if chunk_index < 0 or chunk_index >= len(offsets) - 1:
        raise ValueError("Invalid UBER chunk index")

    old_start = offsets[chunk_index]
    old_end = offsets[chunk_index + 1]
    size_delta = len(new_chunk_data) - (old_end - old_start)

    rebuilt = bytearray()
    rebuilt += uber_data[:old_start]
    rebuilt += new_chunk_data
    rebuilt += uber_data[old_end:]

    new_offsets = offsets[:-1]
    for i in range(chunk_index + 1, len(new_offsets)):
        new_offsets[i] += size_delta

    for i, offset in enumerate(new_offsets):
        struct.pack_into(endian + "I", rebuilt, 0x08 + (i * 4), offset)

    if adjust_pointers and size_delta != 0:
        old_file_size = len(uber_data)
        # Later UBER chunks can contain absolute offsets to strings/data that move
        # when an earlier chunk grows. Update aligned pointers in chunks
        # after the changed chunk while leaving SDIR sample offsets untouched.
        for i in range(chunk_index + 1, len(new_offsets)):
            old_chunk_start = offsets[i]
            old_chunk_end = offsets[i + 1]
            new_chunk_start = new_offsets[i]
            for old_pos in range(old_chunk_start, old_chunk_end - 3, 4):
                value = struct.unpack(endian + "I", uber_data[old_pos:old_pos + 4])[0]
                if old_end <= value < old_file_size:
                    new_pos = new_chunk_start + (old_pos - old_chunk_start)
                    struct.pack_into(endian + "I", rebuilt, new_pos, value + size_delta)

    with open(uber_path, "wb") as uber:
        uber.write(rebuilt)

def find_uber_chunk(uber_path, chunk_type):
    with open(uber_path, "rb") as uber:
        uber_data = uber.read()

    offsets = get_uber_chunk_offsets(uber_data)
    endian = get_uber_endian(uber_data)
    chunk_type = chunk_type.lower()

    for i in range(len(offsets) - 1):
        chunk = uber_data[offsets[i]:offsets[i + 1]]
        try:
            if endian == "<":
                found_type = chunk[0:4].decode("ascii").lower()
            else:
                found_type = chunk[0:4][::-1].decode("ascii").lower()
        except:
            found_type = ""

        if found_type == chunk_type:
            return i, chunk

    return None, None

def create_wii_sdir_entry(dsp_data, sample_offset, template_entry=None):
    if len(dsp_data) < 0x60:
        raise ValueError("DSP data is too small")

    entry = bytearray(template_entry[:64]) if template_entry and len(template_entry) >= 64 else bytearray(64)
    num_nibbles = struct.unpack(">I", dsp_data[0x04:0x08])[0]
    sample_rate = struct.unpack(">I", dsp_data[0x08:0x0C])[0]
    loop_flag = struct.unpack(">H", dsp_data[0x0C:0x0E])[0]
    dsp_format = struct.unpack(">H", dsp_data[0x0E:0x10])[0]
    if template_entry and len(template_entry) >= 64 and loop_flag == 0:
        loop_flag = struct.unpack(">I", template_entry[0x08:0x0C])[0]
        dsp_format = struct.unpack(">H", template_entry[0x0C:0x0E])[0]

    if sample_rate > 0xFFFF:
        raise ValueError("Sample rate is too large for Wii SDIR")

    entry[0x00:0x04] = struct.pack(">I", sample_offset)
    entry[0x04:0x08] = struct.pack(">I", num_nibbles)
    entry[0x08:0x0C] = struct.pack(">I", loop_flag)
    entry[0x0C:0x0E] = struct.pack(">H", dsp_format)
    entry[0x0E:0x10] = struct.pack(">H", sample_rate)
    entry[0x10:0x30] = dsp_data[0x1C:0x3C]

    # SDIR stores the same DSP predictor/scale and history block after coefficients.
    entry[0x30:0x32] = dsp_data[0x3C:0x3E]
    entry[0x32:0x34] = dsp_data[0x3E:0x40]
    entry[0x34:0x36] = dsp_data[0x40:0x42]
    entry[0x36:0x38] = dsp_data[0x42:0x44]
    entry[0x38:0x3A] = dsp_data[0x44:0x46]
    entry[0x3A:0x3C] = dsp_data[0x46:0x48]
    entry[0x3C:0x3E] = dsp_data[0x48:0x4A]

    return bytes(entry)

def append_wii_sound_to_uber_samp(uber_path, samp_path, dsp_data):
    chunk_index, sdir_data = find_uber_chunk(uber_path, "sdir")
    if sdir_data is None:
        raise ValueError("No SDIR chunk found in UBER")
    if sdir_data[0:4][::-1] != b"SDIR":
        raise ValueError("Embedded SDIR is not Wii format")

    num_entries = struct.unpack(">I", sdir_data[0x0C:0x10])[0]
    expected_size = 0x10 + (num_entries * 64)
    if len(sdir_data) != expected_size:
        raise ValueError("Unsupported SDIR layout: table size does not match entry count")

    old_samp_size = os.path.getsize(samp_path)
    sample_offset = (old_samp_size * 2) + 2
    adpcm_data = dsp_data[0x60:]

    with open(samp_path, "ab") as samp:
        samp.write(adpcm_data)

    new_sdir = bytearray(sdir_data)
    new_sdir[0x08:0x0C] = struct.pack(">I", old_samp_size + len(adpcm_data))
    new_sdir[0x0C:0x10] = struct.pack(">I", num_entries + 1)
    new_sdir += create_wii_sdir_entry(dsp_data, sample_offset)

    replace_uber_chunk(uber_path, chunk_index, bytes(new_sdir))
    return num_entries

def create_gc_sdir_entries(dsp_data, sample_offset, sound_id, tbl2_offset):
    if len(dsp_data) < 0x60:
        raise ValueError("DSP data is too small")

    num_samples = struct.unpack(">I", dsp_data[0x00:0x04])[0]
    sample_rate = struct.unpack(">I", dsp_data[0x08:0x0C])[0]
    if sample_rate > 0xFFFF:
        raise ValueError("Sample rate is too large for GameCube SDIR")

    table1 = bytearray(32)
    table1[0x00:0x02] = struct.pack(">H", sound_id & 0xFFFF)
    table1[0x04:0x08] = struct.pack(">I", sample_offset)
    table1[0x0C:0x0E] = struct.pack(">H", 0x3C00)
    table1[0x0E:0x10] = struct.pack(">H", sample_rate)
    table1[0x10:0x14] = struct.pack(">I", num_samples)
    table1[0x18:0x1C] = struct.pack(">I", num_samples)
    table1[0x1C:0x20] = struct.pack(">I", tbl2_offset)

    table2 = bytearray(0x28)
    ps = dsp_data[0x3F]
    table2[0x00:0x02] = b"\x00\x08"
    table2[0x02] = ps
    table2[0x03] = ps
    table2[0x08:0x28] = dsp_data[0x1C:0x3C]

    return bytes(table1), bytes(table2)

def append_gc_sound_to_sdir_samp(sdir_path, samp_path, dsp_data):
    with open(sdir_path, "rb") as sdir:
        sdir_data = sdir.read()

    table2_offsets = []
    last_sound_id = 0
    insert_offset = None

    for offset in range(0, len(sdir_data) - 31, 32):
        record = sdir_data[offset:offset + 32]
        if record[0:4] == b"\xFF\xFF\xFF\xFF":
            insert_offset = offset
            break

        tbl2_offset = struct.unpack(">I", record[0x1C:0x20])[0]
        if tbl2_offset:
            table2_offsets.append(tbl2_offset)

        sound_id = struct.unpack(">H", record[0x00:0x02])[0]
        if sound_id != 0xFFFF:
            last_sound_id = max(last_sound_id, sound_id)

    if insert_offset is None:
        raise ValueError("Could not find GameCube SDIR table boundary")

    table2_start = min(table2_offsets) if table2_offsets else len(sdir_data)
    new_tbl2_offset = len(sdir_data) + 32
    new_sound_index = insert_offset // 32
    new_sound_id = last_sound_id + 1
    old_samp_size = os.path.getsize(samp_path)
    adpcm_data = dsp_data[0x60:]

    with open(samp_path, "ab") as samp:
        samp.write(adpcm_data)

    new_table1, new_table2 = create_gc_sdir_entries(
        dsp_data, old_samp_size, new_sound_id, new_tbl2_offset
    )

    rebuilt = bytearray()
    rebuilt += sdir_data[:insert_offset]
    rebuilt += new_table1
    rebuilt += sdir_data[insert_offset:]
    rebuilt += new_table2

    for offset in range(0, insert_offset, 32):
        tbl2_offset = struct.unpack(">I", rebuilt[offset + 0x1C:offset + 0x20])[0]
        if tbl2_offset >= table2_start:
            struct.pack_into(">I", rebuilt, offset + 0x1C, tbl2_offset + 32)

    with open(sdir_path, "wb") as sdir:
        sdir.write(rebuilt)

    return new_sound_index

def create_ps2_sdir_entry(data_offset, data_size, sample_rate):
    entry = bytearray(16)
    entry[0x00:0x04] = struct.pack("<I", data_offset)
    entry[0x04:0x08] = struct.pack("<I", data_size)
    entry[0x0C:0x10] = struct.pack("<I", sample_rate)
    return bytes(entry)

def get_sdir_chunk_from_uber(uber_path):
    chunk_index, sdir_data = find_uber_chunk(uber_path, "sdir")
    if sdir_data is None:
        raise ValueError("No SDIR chunk found in UBER")
    return chunk_index, sdir_data

def parse_ps2_sdir_entries(sdir_data):
    if sdir_data[0:4] != b"SDIR":
        raise ValueError("SDIR is not PS2 little-endian format")

    num_entries = struct.unpack("<I", sdir_data[0x0C:0x10])[0]
    entries = []
    for index in range(num_entries):
        offset = 0x10 + (index * 16)
        raw = sdir_data[offset:offset + 16]
        if len(raw) < 16:
            break

        entries.append({
            'index': index,
            'entry_offset': offset,
            'data_offset': struct.unpack("<I", raw[0x00:0x04])[0],
            'data_size': struct.unpack("<I", raw[0x04:0x08])[0],
            'unknown': raw[0x08:0x0C],
            'unknown_value': struct.unpack("<I", raw[0x08:0x0C])[0],
            'sample_rate': struct.unpack("<I", raw[0x0C:0x10])[0],
            'raw': raw
        })

    return entries

def get_ps2_sdir_entries_from_uber(uber_path):
    _chunk_index, sdir_data = get_sdir_chunk_from_uber(uber_path)
    return parse_ps2_sdir_entries(sdir_data)

def read_uber_c_string(uber_data, offset):
    if offset < 0 or offset >= len(uber_data):
        return ""
    end = uber_data.find(b"\x00", offset)
    if end < 0 or end == offset:
        return ""
    raw = uber_data[offset:end]
    if any(byte < 0x20 or byte >= 0x7F for byte in raw):
        return ""
    return raw.decode("ascii", errors="ignore")

def find_ps2_uber_name_table(uber_data, offsets):
    best_names = []

    for chunk_index in range(len(offsets) - 1):
        chunk = uber_data[offsets[chunk_index]:offsets[chunk_index + 1]]
        if len(chunk) < 8:
            continue

        count = struct.unpack("<I", chunk[0:4])[0]
        if count <= 0 or count > 10000 or 4 + count * 4 > len(chunk):
            continue

        names = []
        valid_count = 0
        for index in range(count):
            ptr_offset = 4 + index * 4
            string_offset = struct.unpack("<I", chunk[ptr_offset:ptr_offset + 4])[0]
            name = read_uber_c_string(uber_data, string_offset)
            names.append(name)
            if name:
                valid_count += 1

        if valid_count > len(best_names) // 2 and valid_count > 10:
            best_names = names

    return best_names

def extract_ps2_pool_sound_refs(record, entry_count):
    refs = set()

    for offset in range(0, max(0, len(record) - 3), 8):
        command = record[offset]
        sample_index = None

        if command == 0x10:
            sample_index = (record[offset + 1] << 8) | record[offset + 2]
        elif command in (0x06, 0x13):
            sample_index = (record[offset + 2] << 8) | record[offset + 3]

        if sample_index is not None and 0 <= sample_index < entry_count:
            refs.add(sample_index)

    return refs

def get_ps2_uber_sound_name_map(uber_path, entry_count):
    with open(uber_path, "rb") as uber:
        uber_data = uber.read()

    if get_uber_endian(uber_data) != "<":
        return {}

    offsets = get_uber_chunk_offsets(uber_data)
    cue_names = find_ps2_uber_name_table(uber_data, offsets)
    if not cue_names:
        return {}

    _pool_index, pool_data = find_uber_chunk(uber_path, "pool")
    if not pool_data or len(pool_data) < 0x10 or pool_data[0:4] != b"POOL":
        return {}

    pool_count = struct.unpack("<I", pool_data[0x08:0x0C])[0]
    cue_count = min(len(cue_names), pool_count)
    if cue_count <= 0 or 0x10 + cue_count * 4 > len(pool_data):
        return {}

    record_offsets = [
        struct.unpack("<I", pool_data[0x10 + index * 4:0x14 + index * 4])[0]
        for index in range(cue_count)
    ]
    sorted_record_offsets = sorted({
        offset for offset in record_offsets
        if 0 <= offset < len(pool_data)
    })

    sound_name_matches = {}
    for cue_index, record_offset in enumerate(record_offsets):
        if not (0 <= record_offset < len(pool_data)):
            continue

        next_offsets = [
            offset for offset in sorted_record_offsets
            if offset > record_offset
        ]
        record_end = next_offsets[0] if next_offsets else len(pool_data)
        record = pool_data[record_offset:record_end]

        cue_name = cue_names[cue_index]
        if not cue_name:
            continue

        refs = extract_ps2_pool_sound_refs(record, entry_count)
        if not refs:
            continue

        is_direct_cue = len(refs) == 1
        for sample_index in refs:
            matches = sound_name_matches.setdefault(sample_index, [])
            if not any(match['name'] == cue_name for match in matches):
                matches.append({
                    'name': cue_name,
                    'cue_index': cue_index,
                    'is_direct_cue': is_direct_cue,
                    'ref_count': len(refs),
                })

    sound_names = {}
    for sample_index, matches in sound_name_matches.items():
        matches.sort(key=lambda match: (
            0 if match['is_direct_cue'] else 1,
            match['ref_count'],
            match['cue_index'],
        ))
        sound_names[sample_index] = [match['name'] for match in matches]

    return sound_names

def is_ps2_ambient_random_record(record, refs):
    return (
        len(refs) > 1 and
        len(record) >= 128 and
        len(record) % 8 == 0 and
        record[0:1] == b"\x38" and
        record[8:10] == b"\x0d\x80"
    )

def is_ps2_ambient_full_record(record, refs):
    return (
        len(refs) >= 2 and
        len(record) == 112 and
        record[0:1] == b"\x38" and
        record[8:10] == b"\x0d\x80" and
        record[0x40:0x41] == b"\x30"
    )

def get_ps2_uber_random_config_map(uber_path, entry_count):
    with open(uber_path, "rb") as uber:
        uber_data = uber.read()

    if get_uber_endian(uber_data) != "<":
        return {}

    pool_index, pool_data = find_uber_chunk(uber_path, "pool")
    name_index, name_data, _name_chunk_start = find_ps2_uber_name_table_chunk(uber_path)
    if pool_data is None or name_data is None or pool_data[0:4] != b"POOL":
        return {}

    records = get_ps2_cue_candidate_records(pool_data, name_data, uber_data, entry_count)
    ambient_records = [
        record for record in records
        if is_ps2_ambient_random_record(record['record'], record['refs'])
    ]
    configs = {}

    for record in records:
        refs = record['refs']
        if len(refs) < 2:
            continue

        if is_ps2_ambient_full_record(record['record'], refs):
            random_anchor = refs[0]
            base_sound = refs[0]
            attached = None
            for candidate in ambient_records:
                if (
                    candidate['cue_index'] != record['cue_index'] and
                    random_anchor in candidate['refs']
                ):
                    if attached is None or len(candidate['refs']) > len(attached['refs']):
                        attached = candidate

            random_indices = list(attached['refs'][1:]) if attached else []
            configs[base_sound] = {
                'mode': 'amb_full',
                'indices': random_indices,
                'cue_index': record['cue_index'],
                'cue_name': record['name'],
                'attached_cue_index': attached['cue_index'] if attached else None,
                'attached_cue_name': attached['name'] if attached else "",
            }
            continue

        if is_ps2_ambient_random_record(record['record'], refs):
            mode = 'ambient'
            base_sound = refs[0] + 1 if refs[0] + 1 < entry_count else refs[0]
            random_indices = refs[1:]
        else:
            mode = 'simple'
            base_sound = refs[0]
            random_indices = refs[1:]

        if base_sound in configs and configs[base_sound].get('mode') == 'amb_full':
            continue

        configs[base_sound] = {
            'mode': mode,
            'indices': random_indices,
            'cue_index': record['cue_index'],
            'cue_name': record['name'],
            'attached_cue_index': None,
            'attached_cue_name': "",
        }

    return configs

def set_ps2_uber_sound_name(uber_path, sound_index, cue_name):
    cue_name = (cue_name or "").strip()
    if not cue_name:
        raise ValueError("Cue name cannot be empty")

    with open(uber_path, "rb") as uber:
        uber_data = uber.read()

    if get_uber_endian(uber_data) != "<":
        raise ValueError("Renaming UBER cue names is only supported for PS2 little-endian UBER files")

    _sdir_index, sdir_data = get_sdir_chunk_from_uber(uber_path)
    entry_count = len(parse_ps2_sdir_entries(sdir_data))
    if sound_index < 0 or sound_index >= entry_count:
        raise ValueError("Sound index is outside the PS2 SDIR table")

    pool_index, pool_data = find_uber_chunk(uber_path, "pool")
    name_index, name_data, name_chunk_start = find_ps2_uber_name_table_chunk(uber_path)
    if pool_data is None or name_data is None:
        raise ValueError("Could not find PS2 UBER POOL/name chunks")
    if pool_data[0:4] != b"POOL":
        raise ValueError("PS2 UBER POOL chunk has an unsupported layout")

    pool_count = struct.unpack("<I", pool_data[0x08:0x0C])[0]
    name_count = struct.unpack("<I", name_data[0:4])[0]
    cue_count = min(pool_count, name_count)
    if cue_count <= 0 or 0x10 + cue_count * 4 > len(pool_data) or 4 + cue_count * 4 > len(name_data):
        raise ValueError("PS2 UBER cue/name tables are not valid")

    record_offsets = [
        struct.unpack("<I", pool_data[0x10 + index * 4:0x14 + index * 4])[0]
        for index in range(cue_count)
    ]
    sorted_record_offsets = sorted({
        offset for offset in record_offsets
        if 0 <= offset < len(pool_data)
    })

    candidates = []
    for cue_index, record_offset in enumerate(record_offsets):
        if not (0 <= record_offset < len(pool_data)):
            continue

        next_offsets = [
            offset for offset in sorted_record_offsets
            if offset > record_offset
        ]
        record_end = next_offsets[0] if next_offsets else len(pool_data)
        record = pool_data[record_offset:record_end]
        refs = extract_ps2_pool_sound_refs(record, entry_count)
        if sound_index in refs:
            candidates.append({
                'cue_index': cue_index,
                'is_direct_cue': len(refs) == 1,
                'ref_count': len(refs),
            })

    if not candidates:
        raise ValueError(f"Could not find a UBER cue that references sound {sound_index}")

    candidates.sort(key=lambda candidate: (
        0 if candidate['is_direct_cue'] else 1,
        candidate['ref_count'],
        candidate['cue_index'],
    ))
    target_cue_index = candidates[0]['cue_index']

    new_name_offset = name_chunk_start + len(name_data)
    new_name_data = bytearray(name_data)
    struct.pack_into("<I", new_name_data, 4 + target_cue_index * 4, new_name_offset)
    new_name_data += cue_name.encode("ascii", errors="replace") + b"\x00"
    replace_uber_chunk(uber_path, name_index, bytes(new_name_data))

    return target_cue_index

def select_ps2_cue_index_for_sound(pool_data, sound_index, entry_count):
    pool_count = struct.unpack("<I", pool_data[0x08:0x0C])[0]
    record_offsets = get_ps2_pool_record_offsets(pool_data, pool_count)
    spans = get_ps2_pool_record_spans(pool_data, record_offsets)
    candidates = []

    for cue_index, (record_start, record_end) in enumerate(spans):
        if not (0 <= record_start < record_end <= len(pool_data)):
            continue

        record = pool_data[record_start:record_end]
        refs = extract_ps2_pool_sound_refs(record, entry_count)
        if sound_index in refs:
            candidates.append({
                'cue_index': cue_index,
                'is_direct_cue': len(refs) == 1,
                'ref_count': len(refs),
            })

    if not candidates:
        raise ValueError(f"Could not find a UBER cue that references sound {sound_index}")

    candidates.sort(key=lambda candidate: (
        0 if candidate['is_direct_cue'] else 1,
        candidate['ref_count'],
        candidate['cue_index'],
    ))
    return candidates[0]['cue_index']

def find_ps2_pool_template_by_name(records, wanted_name):
    wanted_norm = normalize_ps2_cue_name(wanted_name)
    for record in records:
        if normalize_ps2_cue_name(record['name']) == wanted_norm:
            return record
    return None

def select_ps2_random_template_record(records, required_ref_count, mode):
    if mode == "ambient":
        template = find_ps2_pool_template_by_name(records, "random_birdcall")
        if not template:
            raise ValueError("Could not find random_birdcall ambient random template")
        return template

    preferred_names = [
        "MECHAZ SERVO RANDOM",
        "GIGAN GROWL",
        "GIGAN GRUNT",
        "GIGAN ROAR",
        "EXPLOSION_LARGE_RANDOM",
    ]
    for preferred_name in preferred_names:
        template = find_ps2_pool_template_by_name(records, preferred_name)
        if template and len(template['refs']) >= required_ref_count:
            return template

    array_templates = [
        record for record in records
        if len(record['refs']) >= required_ref_count and len(record['refs']) > 1
    ]
    if not array_templates:
        raise ValueError(
            f"Could not find a simple random template with at least {required_ref_count} sound slot(s)"
        )

    array_templates.sort(key=lambda record: (len(record['refs']), len(record['record'])))
    return array_templates[0]

def build_ps2_random_pool_record(template_record, target_sound_indices):
    ordered_template_refs = template_record['refs']
    if not ordered_template_refs:
        raise ValueError("Random template has no sound references")
    if len(target_sound_indices) > len(ordered_template_refs):
        raise ValueError(
            f"Random template only has {len(ordered_template_refs)} sound slot(s), "
            f"but {len(target_sound_indices)} were selected"
        )

    ref_mapping = {}
    for template_pos, old_ref in enumerate(ordered_template_refs):
        if template_pos < len(target_sound_indices):
            new_ref = target_sound_indices[template_pos]
        else:
            repeat_pos = (template_pos - 1) % max(1, len(target_sound_indices) - 1)
            new_ref = target_sound_indices[1 + repeat_pos] if len(target_sound_indices) > 1 else target_sound_indices[0]
        ref_mapping[old_ref] = new_ref

    return replace_ps2_pool_ref_mapping(template_record['record'], ref_mapping)

def replace_ps2_pool_cue_record(uber_path, target_cue_index, new_record):
    pool_index, pool_data = find_uber_chunk(uber_path, "pool")
    if pool_data is None or pool_data[0:4] != b"POOL":
        raise ValueError("Could not find PS2 UBER POOL chunk")

    pool_count = struct.unpack("<I", pool_data[0x08:0x0C])[0]
    if target_cue_index < 0 or target_cue_index >= pool_count:
        raise ValueError("Target cue index is outside the PS2 POOL table")

    record_offsets = get_ps2_pool_record_offsets(pool_data, pool_count)
    spans = get_ps2_pool_record_spans(pool_data, record_offsets)
    pointer_start = 0x10
    pointer_end = pointer_start + (pool_count * 4)

    rebuilt_records = bytearray()
    new_offsets = []
    for cue_index, (record_start, record_end) in enumerate(spans):
        new_offsets.append(pointer_end + len(rebuilt_records))
        if cue_index == target_cue_index:
            rebuilt_records += new_record
        else:
            rebuilt_records += pool_data[record_start:record_end]

    new_pool = bytearray()
    new_pool += pool_data[:pointer_start]
    for offset in new_offsets:
        new_pool += struct.pack("<I", offset)
    new_pool += rebuilt_records

    replace_uber_chunk(uber_path, pool_index, bytes(new_pool))

def set_ps2_uber_random_cue(uber_path, sound_index, random_sound_indices, mode):
    mode = (mode or "simple").lower()
    if mode not in ("simple", "ambient"):
        raise ValueError("Random cue mode must be simple or ambient")

    target_indices = []
    for index in [sound_index] + list(random_sound_indices or []):
        index = int(index)
        if index not in target_indices:
            target_indices.append(index)

    if len(target_indices) < 2:
        raise ValueError("Random cues need at least one additional random sound")

    with open(uber_path, "rb") as uber:
        uber_data = uber.read()

    if get_uber_endian(uber_data) != "<":
        raise ValueError("Random cue editing is only supported for PS2 little-endian UBER files")

    _sdir_index, sdir_data = get_sdir_chunk_from_uber(uber_path)
    entry_count = len(parse_ps2_sdir_entries(sdir_data))
    for index in target_indices:
        if index < 0 or index >= entry_count:
            raise ValueError(f"Invalid PS2 sound index for random cue: {index}")

    pool_index, pool_data = find_uber_chunk(uber_path, "pool")
    name_index, name_data, _name_chunk_start = find_ps2_uber_name_table_chunk(uber_path)
    if pool_data is None or name_data is None:
        raise ValueError("Could not find PS2 UBER POOL/name chunks")
    if pool_data[0:4] != b"POOL":
        raise ValueError("PS2 UBER POOL chunk has an unsupported layout")

    pool_count = struct.unpack("<I", pool_data[0x08:0x0C])[0]
    name_count = struct.unpack("<I", name_data[0:4])[0]
    cue_count = min(pool_count, name_count)
    if cue_count <= 0 or 0x10 + cue_count * 4 > len(pool_data):
        raise ValueError("PS2 UBER cue tables are not valid")

    records = get_ps2_cue_candidate_records(pool_data, name_data, uber_data, entry_count)
    template = select_ps2_random_template_record(records, len(target_indices), mode)
    new_record = build_ps2_random_pool_record(template, target_indices)
    target_cue_index = select_ps2_cue_index_for_sound(pool_data, sound_index, entry_count)

    replace_ps2_pool_cue_record(uber_path, target_cue_index, new_record)
    return {
        'cue_index': target_cue_index,
        'mode': mode,
        'template_cue_index': template['cue_index'],
        'template_name': template['name'],
        'target_indices': target_indices,
    }

def build_ps2_ambient_full_base_record(records, sound_index, random_anchor_index):
    island_template = find_ps2_pool_template_by_name(records, "ISLAND LOOP")
    if not island_template:
        raise ValueError("Could not find ISLAND LOOP full ambience template")

    template_refs = island_template['refs']
    if len(template_refs) < 2:
        raise ValueError("ISLAND LOOP template does not contain both ambience and random references")

    ref_mapping = {
        template_refs[0]: random_anchor_index,
        template_refs[-1]: sound_index,
    }
    return replace_ps2_pool_ref_mapping(island_template['record'], ref_mapping), island_template

def set_ps2_uber_ambient_full_cue(uber_path, sound_index, random_sound_indices, cue_name=None):
    random_indices = []
    for index in list(random_sound_indices or []):
        index = int(index)
        if index not in random_indices:
            random_indices.append(index)

    if not random_indices:
        raise ValueError("Amb. Full needs at least one random sound")

    with open(uber_path, "rb") as uber:
        uber_data = uber.read()

    if get_uber_endian(uber_data) != "<":
        raise ValueError("Amb. Full editing is only supported for PS2 little-endian UBER files")

    _sdir_index, sdir_data = get_sdir_chunk_from_uber(uber_path)
    entry_count = len(parse_ps2_sdir_entries(sdir_data))
    for index in [sound_index] + random_indices:
        if index < 0 or index >= entry_count:
            raise ValueError(f"Invalid PS2 sound index for Amb. Full cue: {index}")

    base_name = (cue_name or f"sound_{sound_index}").strip() or f"sound_{sound_index}"
    random_cue_name = f"{base_name} RANDOM"
    random_anchor_index = random_indices[0]

    new_random_cue_index = append_ps2_uber_cue(
        uber_path,
        random_anchor_index,
        random_cue_name
    )

    with open(uber_path, "rb") as uber:
        uber_data = uber.read()
    pool_index, pool_data = find_uber_chunk(uber_path, "pool")
    name_index, name_data, _name_chunk_start = find_ps2_uber_name_table_chunk(uber_path)
    if pool_data is None or name_data is None:
        raise ValueError("Could not find PS2 UBER POOL/name chunks")

    records = get_ps2_cue_candidate_records(pool_data, name_data, uber_data, entry_count)
    random_template = select_ps2_random_template_record(records, len(random_indices), "ambient")
    random_record = build_ps2_random_pool_record(random_template, random_indices)
    replace_ps2_pool_cue_record(uber_path, new_random_cue_index, random_record)

    with open(uber_path, "rb") as uber:
        uber_data = uber.read()
    pool_index, pool_data = find_uber_chunk(uber_path, "pool")
    name_index, name_data, _name_chunk_start = find_ps2_uber_name_table_chunk(uber_path)
    records = get_ps2_cue_candidate_records(pool_data, name_data, uber_data, entry_count)
    base_record, island_template = build_ps2_ambient_full_base_record(
        records,
        sound_index,
        random_anchor_index
    )
    target_cue_index = select_ps2_cue_index_for_sound(pool_data, sound_index, entry_count)
    replace_ps2_pool_cue_record(uber_path, target_cue_index, base_record)

    return {
        'cue_index': target_cue_index,
        'mode': 'amb_full',
        'template_cue_index': island_template['cue_index'],
        'template_name': island_template['name'],
        'random_cue_index': new_random_cue_index,
        'appended_random_cue_index': new_random_cue_index,
        'random_template_name': random_template['name'],
        'target_indices': [sound_index] + random_indices,
    }

def find_ps2_uber_name_table_chunk(uber_path):
    with open(uber_path, "rb") as uber:
        uber_data = uber.read()

    if get_uber_endian(uber_data) != "<":
        return None, None, None

    offsets = get_uber_chunk_offsets(uber_data)
    best = (None, None, None, 0)

    for chunk_index in range(len(offsets) - 1):
        chunk_start = offsets[chunk_index]
        chunk = uber_data[chunk_start:offsets[chunk_index + 1]]
        if len(chunk) < 8:
            continue

        count = struct.unpack("<I", chunk[0:4])[0]
        if count <= 0 or count > 10000 or 4 + count * 4 > len(chunk):
            continue

        valid_count = 0
        for index in range(count):
            ptr_offset = 4 + index * 4
            string_offset = struct.unpack("<I", chunk[ptr_offset:ptr_offset + 4])[0]
            if read_uber_c_string(uber_data, string_offset):
                valid_count += 1

        if valid_count > best[3] and valid_count > 10:
            best = (chunk_index, chunk, chunk_start, valid_count)

    return best[0], best[1], best[2]

def get_ps2_pool_record_offsets(pool_data, cue_count):
    return [
        struct.unpack("<I", pool_data[0x10 + index * 4:0x14 + index * 4])[0]
        for index in range(cue_count)
    ]

def get_ps2_pool_record_spans(pool_data, record_offsets):
    sorted_record_offsets = sorted({
        offset for offset in record_offsets
        if 0 <= offset < len(pool_data)
    })

    spans = []
    for record_offset in record_offsets:
        if not (0 <= record_offset < len(pool_data)):
            spans.append((record_offset, record_offset))
            continue

        next_offsets = [
            offset for offset in sorted_record_offsets
            if offset > record_offset
        ]
        record_end = next_offsets[0] if next_offsets else len(pool_data)
        spans.append((record_offset, record_end))

    return spans

def replace_ps2_pool_sound_refs(record, sound_index):
    updated = bytearray(record)
    changed = False

    for offset in range(0, max(0, len(updated) - 3), 8):
        command = updated[offset]
        if command == 0x10:
            updated[offset + 1] = (sound_index >> 8) & 0xFF
            updated[offset + 2] = sound_index & 0xFF
            changed = True
        elif command in (0x06, 0x13):
            updated[offset + 2] = (sound_index >> 8) & 0xFF
            updated[offset + 3] = sound_index & 0xFF
            changed = True

    return bytes(updated), changed

def get_ps2_pool_ref_order(record, entry_count):
    refs = []
    seen = set()
    for offset in range(0, max(0, len(record) - 3), 8):
        command = record[offset]
        sample_index = None

        if command == 0x10:
            sample_index = (record[offset + 1] << 8) | record[offset + 2]
        elif command in (0x06, 0x13):
            sample_index = (record[offset + 2] << 8) | record[offset + 3]

        if sample_index is not None and 0 <= sample_index < entry_count and sample_index not in seen:
            seen.add(sample_index)
            refs.append(sample_index)

    return refs

def replace_ps2_pool_ref_mapping(record, ref_mapping):
    updated = bytearray(record)
    for offset in range(0, max(0, len(updated) - 3), 8):
        command = updated[offset]
        sample_index = None

        if command == 0x10:
            sample_index = (updated[offset + 1] << 8) | updated[offset + 2]
            if sample_index in ref_mapping:
                new_index = ref_mapping[sample_index]
                updated[offset + 1] = (new_index >> 8) & 0xFF
                updated[offset + 2] = new_index & 0xFF
        elif command in (0x06, 0x13):
            sample_index = (updated[offset + 2] << 8) | updated[offset + 3]
            if sample_index in ref_mapping:
                new_index = ref_mapping[sample_index]
                updated[offset + 2] = (new_index >> 8) & 0xFF
                updated[offset + 3] = new_index & 0xFF

    return bytes(updated)

def normalize_ps2_cue_name(name):
    return "".join(char for char in name.upper() if char.isalnum())

def get_ps2_cue_candidate_records(pool_data, name_data, uber_data, entry_count):
    name_count = struct.unpack("<I", name_data[0:4])[0]
    pool_count = struct.unpack("<I", pool_data[0x08:0x0C])[0]
    cue_count = min(name_count, pool_count)
    record_offsets = get_ps2_pool_record_offsets(pool_data, cue_count)
    spans = get_ps2_pool_record_spans(pool_data, record_offsets)

    records = []
    for cue_index, (record_start, record_end) in enumerate(spans):
        if not (0 <= record_start < record_end <= len(pool_data)):
            continue

        pointer = struct.unpack("<I", name_data[4 + cue_index * 4:8 + cue_index * 4])[0]
        cue_name = read_uber_c_string(uber_data, pointer)
        record = pool_data[record_start:record_end]
        refs = get_ps2_pool_ref_order(record, entry_count)
        records.append({
            'cue_index': cue_index,
            'name': cue_name,
            'record': record,
            'refs': refs,
            'record_start': record_start,
            'record_end': record_end,
        })

    return records

def select_ps2_pool_template_record(pool_data, name_data, uber_data, sound_index, cue_name):
    entry_count = 10000
    records = get_ps2_cue_candidate_records(pool_data, name_data, uber_data, entry_count)

    cue_name_norm = normalize_ps2_cue_name(cue_name)
    wants_loop = "LOOP" in cue_name_norm
    best_score = None
    best_record = None

    for candidate in records:
        template_name = candidate['name']
        template_norm = normalize_ps2_cue_name(template_name)
        if not template_norm:
            continue

        record = candidate['record']
        if sound_index in candidate['refs']:
            continue

        is_loop = "LOOP" in template_norm
        if wants_loop and not is_loop:
            continue

        common_prefix = 0
        for left, right in zip(cue_name_norm, template_norm):
            if left != right:
                break
            common_prefix += 1

        score = common_prefix + (1000 if is_loop else 0) + min(len(record), 96)
        if best_score is None or score > best_score:
            best_score = score
            best_record = record

    return best_record

def create_ps2_pool_cue_record(sound_index, template_record=None):
    if template_record and len(template_record) >= 32:
        record, changed = replace_ps2_pool_sound_refs(template_record, sound_index)
        if changed:
            return record
        record = bytearray(template_record)
    else:
        record = bytearray.fromhex(
            "0d c8 00 00 00 00 00 00 "
            "10 00 00 00 00 00 00 00 "
            "07 00 00 01 00 00 ff ff "
            "00 00 00 00 00 00 00 00"
        )

    record[0x08] = 0x10
    record[0x09] = (sound_index >> 8) & 0xFF
    record[0x0A] = sound_index & 0xFF
    record[0x0B] = 0x00
    return bytes(record)

def append_ps2_uber_cue(uber_path, sound_index, cue_name):
    cue_name = (cue_name or f"sound_{sound_index}").strip()
    if not cue_name:
        cue_name = f"sound_{sound_index}"

    with open(uber_path, "rb") as uber:
        original_uber_data = uber.read()

    proj_index, proj_data = find_uber_chunk(uber_path, "proj")
    pool_index, pool_data = find_uber_chunk(uber_path, "pool")
    name_index, name_data, name_chunk_start = find_ps2_uber_name_table_chunk(uber_path)
    if proj_data is None or pool_data is None:
        raise ValueError("PS2 UBER cue append requires PROJ and POOL chunks")
    if proj_data[0:4] != b"PROJ" or pool_data[0:4] != b"POOL":
        raise ValueError("PS2 UBER cue append only supports little-endian PROJ/POOL chunks")
    if name_data is None:
        raise ValueError("Could not find PS2 UBER name table")

    proj_count = struct.unpack("<I", proj_data[0x08:0x0C])[0]
    pool_count = struct.unpack("<I", pool_data[0x08:0x0C])[0]
    name_count = struct.unpack("<I", name_data[0:4])[0]
    if proj_count != pool_count:
        raise ValueError("PROJ and POOL cue counts do not match")
    if name_count != pool_count:
        raise ValueError("Name table and POOL cue counts do not match before cue append")
    if len(proj_data) != 0x10 + (proj_count * 12):
        raise ValueError("Unsupported PS2 PROJ layout")
    if 0x10 + (pool_count * 4) > len(pool_data):
        raise ValueError("Unsupported PS2 POOL layout")

    new_cue_index = proj_count
    old_name_pointers = [
        struct.unpack("<I", name_data[4 + index * 4:8 + index * 4])[0]
        for index in range(name_count)
    ]
    template_record = select_ps2_pool_template_record(
        pool_data, name_data, original_uber_data, sound_index, cue_name
    )

    new_proj = bytearray(proj_data)
    struct.pack_into("<I", new_proj, 0x08, proj_count + 1)
    proj_record = bytearray(proj_data[0x10 + ((proj_count - 1) * 12):0x10 + (proj_count * 12)])
    if len(proj_record) != 12:
        proj_record = bytearray.fromhex("00 00 80 3f 09 00 00 00 00 00 ff ff")
    struct.pack_into("<H", proj_record, 0x08, new_cue_index & 0xFFFF)
    struct.pack_into("<H", proj_record, 0x0A, 0xFFFF)
    new_proj += proj_record
    proj_delta = len(new_proj) - len(proj_data)
    replace_uber_chunk(uber_path, proj_index, bytes(new_proj), adjust_pointers=False)

    pool_index, pool_data = find_uber_chunk(uber_path, "pool")
    pool_count = struct.unpack("<I", pool_data[0x08:0x0C])[0]
    pointer_start = 0x10
    pointer_end = pointer_start + (pool_count * 4)
    record_offsets = get_ps2_pool_record_offsets(pool_data, pool_count)
    shifted_offsets = [offset + 4 for offset in record_offsets]
    if template_record is None:
        template_offset = record_offsets[-1] if record_offsets else pointer_end
        template_spans = get_ps2_pool_record_spans(pool_data, record_offsets)
        template_end = next((end for start, end in template_spans if start == template_offset), template_offset + 32)
        template_record = pool_data[template_offset:template_end]
    new_record_offset = len(pool_data) + 4

    new_pool = bytearray()
    new_pool += pool_data[:0x08]
    new_pool += struct.pack("<I", pool_count + 1)
    new_pool += pool_data[0x0C:pointer_start]
    for offset in shifted_offsets:
        new_pool += struct.pack("<I", offset)
    new_pool += struct.pack("<I", new_record_offset)
    new_pool += pool_data[pointer_end:]
    new_pool += create_ps2_pool_cue_record(sound_index, template_record)
    pool_delta = len(new_pool) - len(pool_data)
    replace_uber_chunk(uber_path, pool_index, bytes(new_pool), adjust_pointers=False)

    earlier_chunk_delta = proj_delta + pool_delta
    shifted_pointers = [
        pointer + earlier_chunk_delta + 4
        for pointer in old_name_pointers
    ]
    new_string_offset = name_chunk_start + earlier_chunk_delta + len(name_data) + 4

    new_names = bytearray()
    new_names += struct.pack("<I", name_count + 1)
    for pointer in shifted_pointers:
        new_names += struct.pack("<I", pointer)
    new_names += struct.pack("<I", new_string_offset)
    new_names += name_data[4 + (name_count * 4):]
    new_names += cue_name.encode("ascii", errors="replace") + b"\x00"
    replace_uber_chunk(uber_path, name_index, bytes(new_names), adjust_pointers=False)

    return new_cue_index

def format_debug_name_list(names, limit=6):
    if not names:
        return "(no UBER cue name found)"
    shown = names[:limit]
    suffix = f" (+{len(names) - limit} more)" if len(names) > limit else ""
    return " / ".join(shown) + suffix

def write_ps2_rebuild_debug_dump(uber_path, samp_path, dump_path, before_entries=None):
    _chunk_index, sdir_data = get_sdir_chunk_from_uber(uber_path)
    after_entries = parse_ps2_sdir_entries(sdir_data)
    before_by_index = {entry['index']: entry for entry in before_entries or []}
    samp_size = os.path.getsize(samp_path)
    sound_names = get_ps2_uber_sound_name_map(uber_path, len(after_entries))

    active_entries = [
        entry for entry in after_entries
        if entry['data_size'] > 0 and entry['data_offset'] != 0xFFFFFFFF
    ]
    sorted_entries = sorted(active_entries, key=lambda entry: entry['data_offset'])

    lines = []
    lines.append(f"UBER: {uber_path}")
    lines.append(f"SAMP: {samp_path}")
    lines.append(f"SAMP size: {samp_size}")
    lines.append(f"SDIR size field: {struct.unpack('<I', sdir_data[0x08:0x0C])[0]}")
    lines.append(f"SDIR entry count: {struct.unpack('<I', sdir_data[0x0C:0x10])[0]}")
    lines.append(f"UBER cue-name mappings found: {sum(1 for names in sound_names.values() if names)} sound slot(s)")
    lines.append("")
    lines.append("Notes:")
    lines.append("- Offsets and sizes are SAMP-relative.")
    lines.append("- Padding is the gap between this entry's audio end and the next entry start.")
    lines.append("- UBER names are best-effort cue names from POOL records; random/shared cues can name the same sound more than once.")
    lines.append("")
    with open(samp_path, "rb") as samp:
        samp_data = samp.read()

    lines.append("=" * 72)

    for order, entry in enumerate(sorted_entries):
        start = entry['data_offset']
        size = entry['data_size']
        end = start + size
        next_start = sorted_entries[order + 1]['data_offset'] if order + 1 < len(sorted_entries) else samp_size

        status = []
        if start >= samp_size:
            status.append("OUTSIDE_SAMP")
        if end > samp_size:
            status.append("ENDS_OUTSIDE_SAMP")
        if order + 1 < len(sorted_entries) and end > next_start:
            status.append(f"OVERLAPS_NEXT_{sorted_entries[order + 1]['index']}")
        if end < next_start:
            status.append(f"PAD_{next_start - end}")

        before = before_by_index.get(entry['index'])
        flags = []
        if start < len(samp_data) and size >= 16:
            frame_flags = samp_data[start + 1:end:16]
            if frame_flags:
                flags = [frame_flags[0], frame_flags[-1]]
                unique_flags = sorted(set(frame_flags))
                if len(unique_flags) > 2:
                    flags.extend(unique_flags)

        if before:
            changed = []
            for key in ('data_offset', 'data_size', 'unknown_value', 'sample_rate'):
                if before[key] != entry[key]:
                    changed.append(f"{key}:{before[key]}->{entry[key]}")
            if changed:
                status.append("CHANGED[" + ", ".join(changed) + "]")

            raw_changes = [
                f"{i:02X}:{before['raw'][i]:02X}->{entry['raw'][i]:02X}"
                for i in range(16)
                if before['raw'][i] != entry['raw'][i]
            ]
            if raw_changes:
                status.append("BYTES[" + " ".join(raw_changes) + "]")

        lines.append(f"Sound {entry['index']:05d}")
        lines.append(f"  UBER name(s): {format_debug_name_list(sound_names.get(entry['index'], []))}")
        lines.append(f"  Offset: 0x{start:08X} ({start})")
        lines.append(f"  End:    0x{end:08X} ({end})")
        lines.append(f"  Size:   0x{size:08X} ({size})")
        lines.append(f"  Align:  start % 0x10 = 0x{start % 0x10:02X}, start % 0x20 = 0x{start % 0x20:02X}")
        lines.append(f"  Rate:   {entry['sample_rate']} Hz")
        lines.append(f"  Unknown bytes 08-0B: {entry['unknown'].hex(' ')}")
        lines.append(f"  PS2 frame flags: {' '.join(f'{flag:02X}' for flag in flags) if flags else '--'}")
        lines.append(f"  Status: {'; '.join(status) if status else 'OK'}")
        lines.append("")
        lines.append("-" * 72)
        lines.append("")

    with open(dump_path, "w", encoding="utf-8") as dump:
        dump.write("\n".join(lines))

    return dump_path

def append_ps2_sound_to_uber_samp(uber_path, samp_path, adpcm_data, sample_rate):
    chunk_index, sdir_data = get_sdir_chunk_from_uber(uber_path)
    if sdir_data[0:4] != b"SDIR":
        raise ValueError("Embedded SDIR is not PS2 format")

    num_entries = struct.unpack("<I", sdir_data[0x0C:0x10])[0]
    expected_size = 0x10 + (num_entries * 16)
    if len(sdir_data) != expected_size:
        raise ValueError("Unsupported PS2 SDIR layout: table size does not match entry count")

    old_samp_size = os.path.getsize(samp_path)
    with open(samp_path, "ab") as samp:
        samp.write(adpcm_data)

    new_sdir = bytearray(sdir_data)
    new_sdir[0x08:0x0C] = struct.pack("<I", old_samp_size + len(adpcm_data))
    new_sdir[0x0C:0x10] = struct.pack("<I", num_entries + 1)
    new_sdir += create_ps2_sdir_entry(old_samp_size, len(adpcm_data), sample_rate)

    replace_uber_chunk(uber_path, chunk_index, bytes(new_sdir))
    return num_entries

def replace_samp_range(samp_path, offset, old_size, new_data):
    with open(samp_path, "rb") as samp:
        samp_data = samp.read()

    if offset < 0 or old_size < 0 or offset + old_size > len(samp_data):
        raise ValueError("Invalid SAMP replacement range")

    rebuilt = samp_data[:offset] + new_data + samp_data[offset + old_size:]
    with open(samp_path, "wb") as samp:
        samp.write(rebuilt)

    return len(new_data) - old_size, len(rebuilt)

def align_up(value, alignment):
    if alignment <= 1:
        return value
    return ((value + alignment - 1) // alignment) * alignment

def get_next_data_offset(entries, current_offset, samp_size):
    later_offsets = [offset for offset in entries if offset > current_offset]
    return min(later_offsets) if later_offsets else samp_size

def build_aligned_region(samp_path, data_offset, old_data_size, old_region_end,
                         new_audio_data, alignment):
    new_region_end = align_up(data_offset + len(new_audio_data), alignment)
    new_padding_size = new_region_end - data_offset - len(new_audio_data)

    with open(samp_path, "rb") as samp:
        samp.seek(data_offset + old_data_size)
        old_padding = samp.read(max(0, old_region_end - data_offset - old_data_size))

    if len(old_padding) >= new_padding_size:
        padding = old_padding[:new_padding_size]
    else:
        padding = old_padding + (b"\x00" * (new_padding_size - len(old_padding)))

    return new_audio_data + padding

def resize_wii_sound_in_uber_samp(uber_path, samp_path, sound_index, new_dsp_data):
    chunk_index, sdir_data = find_uber_chunk(uber_path, "sdir")
    if sdir_data is None:
        raise ValueError("No SDIR chunk found in UBER")
    if sdir_data[0:4][::-1] != b"SDIR":
        raise ValueError("Embedded SDIR is not Wii format")

    num_entries = struct.unpack(">I", sdir_data[0x0C:0x10])[0]
    entry_offset = 0x10 + (sound_index * 64)
    if sound_index < 0 or sound_index >= num_entries or entry_offset + 64 > len(sdir_data):
        raise ValueError("Invalid Wii SDIR sound index")

    entry = sdir_data[entry_offset:entry_offset + 64]
    sample_offset = struct.unpack(">I", entry[0x00:0x04])[0]
    old_nibbles = struct.unpack(">I", entry[0x04:0x08])[0]
    old_data_offset = (sample_offset - 2) // 2
    old_data_size = (old_nibbles + 1) // 2
    new_audio_data = new_dsp_data[0x60:]
    samp_size = os.path.getsize(samp_path)

    data_offsets = []
    for i in range(num_entries):
        offset = 0x10 + (i * 64)
        entry_nibbles = struct.unpack(">I", sdir_data[offset + 0x04:offset + 0x08])[0]
        if entry_nibbles == 0:
            continue
        entry_sample_offset = struct.unpack(">I", sdir_data[offset:offset + 4])[0]
        data_offsets.append((entry_sample_offset - 2) // 2)

    old_region_end = get_next_data_offset(data_offsets, old_data_offset, samp_size)
    old_region_size = old_region_end - old_data_offset
    new_region = build_aligned_region(
        samp_path, old_data_offset, old_data_size, old_region_end, new_audio_data, 8
    )

    delta, new_samp_size = replace_samp_range(
        samp_path, old_data_offset, old_region_size, new_region
    )

    new_sdir = bytearray(sdir_data)
    new_sdir[0x08:0x0C] = struct.pack(">I", new_samp_size)

    new_entry = create_wii_sdir_entry(new_dsp_data, sample_offset, template_entry=entry)
    new_sdir[entry_offset:entry_offset + 64] = new_entry

    if delta != 0:
        for i in range(num_entries):
            offset = 0x10 + (i * 64)
            entry_nibbles = struct.unpack(">I", new_sdir[offset + 0x04:offset + 0x08])[0]
            if entry_nibbles == 0:
                continue
            entry_sample_offset = struct.unpack(">I", new_sdir[offset:offset + 4])[0]
            entry_data_offset = (entry_sample_offset - 2) // 2
            if entry_data_offset > old_data_offset:
                shifted_sample_offset = ((entry_data_offset + delta) * 2) + 2
                struct.pack_into(">I", new_sdir, offset, shifted_sample_offset)

    replace_uber_chunk(uber_path, chunk_index, bytes(new_sdir))
    return delta

def resize_ps2_sound_in_uber_samp(uber_path, samp_path, sound_index, new_adpcm_data, sample_rate):
    return bulk_resize_ps2_sounds_in_uber_samp(
        uber_path,
        samp_path,
        {sound_index: {'adpcm_data': new_adpcm_data, 'sample_rate': sample_rate}}
    )

def set_wii_loop_flags_for_sounds(uber_or_sdir_path, sound_loop_states):
    with open(uber_or_sdir_path, "rb") as source:
        source_data = source.read()

    is_direct_sdir = source_data[0:4][::-1] == b"SDIR"
    if is_direct_sdir:
        chunk_index = None
        sdir_data = source_data
    else:
        chunk_index, sdir_data = find_uber_chunk(uber_or_sdir_path, "sdir")

    if sdir_data is None or sdir_data[0:4][::-1] != b"SDIR":
        raise ValueError("Wii loop flag edits require a Wii big-endian SDIR/UBER")

    num_entries = struct.unpack(">I", sdir_data[0x0C:0x10])[0]
    new_sdir = bytearray(sdir_data)
    changed = 0

    for sound_index, loop_enabled in sorted(sound_loop_states.items()):
        sound_index = int(sound_index)
        entry_offset = 0x10 + (sound_index * 64)
        if sound_index < 0 or sound_index >= num_entries or entry_offset + 64 > len(new_sdir):
            raise ValueError(f"Invalid Wii sound index for loop flag edit: {sound_index}")

        old_flag = struct.unpack(">I", new_sdir[entry_offset + 0x08:entry_offset + 0x0C])[0]
        new_flag = 1 if loop_enabled else 0
        if old_flag != new_flag:
            struct.pack_into(">I", new_sdir, entry_offset + 0x08, new_flag)
            changed += 1

    if is_direct_sdir:
        with open(uber_or_sdir_path, "wb") as target:
            target.write(new_sdir)
    else:
        replace_uber_chunk(uber_or_sdir_path, chunk_index, bytes(new_sdir))

    return changed

def set_ps2_loop_flags_for_sounds(uber_path, samp_path, sound_loop_states):
    _chunk_index, sdir_data = get_sdir_chunk_from_uber(uber_path)
    if sdir_data[0:4] != b"SDIR":
        raise ValueError("PS2 loop flag edits require a PS2 little-endian UBER")

    requested = {
        int(sound_index): bool(loop_enabled)
        for sound_index, loop_enabled in sound_loop_states.items()
    }
    if not requested:
        return 0

    entries = parse_ps2_sdir_entries(sdir_data)
    with open(samp_path, "rb") as samp:
        samp_data = bytearray(samp.read())

    patched_count = 0
    for sound_index, loop_enabled in sorted(requested.items()):
        if sound_index < 0 or sound_index >= len(entries):
            raise ValueError(f"Invalid PS2 SDIR sound index: {sound_index}")

        entry = entries[sound_index]
        data_offset = entry['data_offset']
        data_size = entry['data_size']
        if data_size <= 0 or data_offset == 0xFFFFFFFF:
            raise ValueError(f"Cannot edit inactive PS2 SDIR entry: {sound_index}")
        if data_offset < 0 or data_offset + data_size > len(samp_data):
            raise ValueError(f"PS2 SDIR entry {sound_index} points outside the SAMP data")

        changed = False
        for frame_start in range(data_offset, data_offset + data_size - 15, 16):
            old_flag = samp_data[frame_start + 1]
            if loop_enabled:
                new_flag = old_flag | 0x02
            else:
                new_flag = old_flag & ~0x02
            if new_flag != old_flag:
                samp_data[frame_start + 1] = new_flag
                changed = True

        if changed:
            patched_count += 1

    with open(samp_path, "wb") as samp:
        samp.write(samp_data)

    return patched_count

def apply_ps2_loop_flags_to_sounds(uber_path, samp_path, sound_indices):
    return set_ps2_loop_flags_for_sounds(
        uber_path,
        samp_path,
        {sound_index: True for sound_index in sound_indices}
    )

def bulk_resize_ps2_sounds_in_uber_samp(uber_path, samp_path, replacements):
    chunk_index, sdir_data = get_sdir_chunk_from_uber(uber_path)
    if sdir_data[0:4] != b"SDIR":
        raise ValueError("Embedded SDIR is not PS2 format")

    entries = parse_ps2_sdir_entries(sdir_data)
    normalized_replacements = {}
    for sound_index, replacement in replacements.items():
        if sound_index < 0 or sound_index >= len(entries):
            raise ValueError(f"Invalid PS2 SDIR sound index: {sound_index}")

        target = entries[sound_index]
        if target['data_size'] <= 0 or target['data_offset'] == 0xFFFFFFFF:
            raise ValueError(f"Cannot replace inactive PS2 SDIR entry: {sound_index}")

        normalized_replacements[sound_index] = replacement

    with open(samp_path, "rb") as samp:
        old_samp_data = samp.read()

    active_entries = [
        entry for entry in entries
        if entry['data_size'] > 0 and entry['data_offset'] != 0xFFFFFFFF
    ]
    active_entries.sort(key=lambda entry: entry['data_offset'])

    first_offset = active_entries[0]['data_offset'] if active_entries else 0
    rebuilt_samp = bytearray(old_samp_data[:first_offset])
    new_offsets = {}
    new_sizes = {}

    for order, entry in enumerate(active_entries):
        old_start = entry['data_offset']
        old_size = entry['data_size']
        old_end = old_start + old_size
        next_old_start = (
            active_entries[order + 1]['data_offset']
            if order + 1 < len(active_entries)
            else len(old_samp_data)
        )
        old_padding = old_samp_data[old_end:next_old_start]

        new_offsets[entry['index']] = len(rebuilt_samp)
        replacement = normalized_replacements.get(entry['index'])
        if replacement:
            audio_data = replacement['adpcm_data']
            new_sizes[entry['index']] = len(audio_data)
        else:
            audio_data = old_samp_data[old_start:old_end]
            new_sizes[entry['index']] = old_size

        rebuilt_samp += audio_data

        padding_size = align_up(len(rebuilt_samp), 16) - len(rebuilt_samp)
        if len(old_padding) >= padding_size:
            rebuilt_samp += old_padding[:padding_size]
        else:
            rebuilt_samp += old_padding
            rebuilt_samp += b"\x00" * (padding_size - len(old_padding))

    with open(samp_path, "wb") as samp:
        samp.write(rebuilt_samp)

    old_samp_size = len(old_samp_data)
    new_samp_size = len(rebuilt_samp)
    new_sdir = bytearray(sdir_data)
    new_sdir[0x08:0x0C] = struct.pack("<I", new_samp_size)

    for entry in active_entries:
        entry_offset = entry['entry_offset']
        struct.pack_into("<I", new_sdir, entry_offset + 0x00, new_offsets[entry['index']])
        struct.pack_into("<I", new_sdir, entry_offset + 0x04, new_sizes[entry['index']])
        replacement = normalized_replacements.get(entry['index'])
        if replacement:
            struct.pack_into("<I", new_sdir, entry_offset + 0x0C, replacement['sample_rate'])

    replace_uber_chunk(uber_path, chunk_index, bytes(new_sdir))
    return new_samp_size - old_samp_size

def resize_gc_sound_in_sdir_samp(sdir_path, samp_path, sound_index, new_dsp_data):
    with open(sdir_path, "rb") as sdir:
        sdir_data = sdir.read()

    entry_offset = sound_index * 32
    if sound_index < 0 or entry_offset + 32 > len(sdir_data):
        raise ValueError("Invalid GameCube SDIR sound index")

    record = sdir_data[entry_offset:entry_offset + 32]
    if record[0:4] == b"\xFF\xFF\xFF\xFF":
        raise ValueError("Cannot replace GameCube SDIR sentinel")

    old_data_offset = struct.unpack(">I", record[0x04:0x08])[0]
    old_num_samples = struct.unpack(">I", record[0x10:0x14])[0]
    old_data_size = ((old_num_samples + 13) // 14) * 8
    tbl2_offset = struct.unpack(">I", record[0x1C:0x20])[0]
    if tbl2_offset + 0x28 > len(sdir_data):
        raise ValueError("Invalid GameCube SDIR Table 2 offset")

    new_audio_data = new_dsp_data[0x60:]
    samp_size = os.path.getsize(samp_path)
    data_offsets = []
    for offset in range(0, len(sdir_data) - 31, 32):
        current = sdir_data[offset:offset + 32]
        if current[0:4] == b"\xFF\xFF\xFF\xFF":
            break
        current_data_offset = struct.unpack(">I", current[0x04:0x08])[0]
        current_num_samples = struct.unpack(">I", current[0x10:0x14])[0]
        if current_num_samples > 0:
            data_offsets.append(current_data_offset)

    old_region_end = get_next_data_offset(data_offsets, old_data_offset, samp_size)
    old_region_size = old_region_end - old_data_offset
    new_region = build_aligned_region(
        samp_path, old_data_offset, old_data_size, old_region_end, new_audio_data, 32
    )

    delta, _new_samp_size = replace_samp_range(
        samp_path, old_data_offset, old_region_size, new_region
    )

    new_sdir = bytearray(sdir_data)
    num_samples = struct.unpack(">I", new_dsp_data[0x00:0x04])[0]
    num_nibbles = struct.unpack(">I", new_dsp_data[0x04:0x08])[0]
    sample_rate = struct.unpack(">I", new_dsp_data[0x08:0x0C])[0]
    ps = new_dsp_data[0x3F]

    struct.pack_into(">H", new_sdir, entry_offset + 0x0E, sample_rate)
    struct.pack_into(">I", new_sdir, entry_offset + 0x10, num_samples)
    struct.pack_into(">I", new_sdir, entry_offset + 0x18, num_samples)

    new_sdir[tbl2_offset + 0x02] = ps
    new_sdir[tbl2_offset + 0x03] = ps
    new_sdir[tbl2_offset + 0x08:tbl2_offset + 0x28] = new_dsp_data[0x1C:0x3C]

    if delta != 0:
        for offset in range(0, len(new_sdir) - 31, 32):
            current = new_sdir[offset:offset + 32]
            if current[0:4] == b"\xFF\xFF\xFF\xFF":
                break
            entry_data_offset = struct.unpack(">I", current[0x04:0x08])[0]
            if entry_data_offset > old_data_offset:
                struct.pack_into(">I", new_sdir, offset + 0x04, entry_data_offset + delta)

    with open(sdir_path, "wb") as sdir:
        sdir.write(new_sdir)

    return delta

def load_sound_data(sdir_path, samp_path):
    sounds = []

    # Standard GameCube DSP ADPCM coefficients
    standard_coefs = bytes([
        0x00, 0x00, 0x00, 0x00,
        0x08, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x04, 0x00,
        0x04, 0x00, 0x00, 0x00,
        0x10, 0x00, 0xF8, 0x00,
        0x0E, 0x00, 0xFA, 0x00,
        0x0C, 0x00, 0xFC, 0x00,
        0x12, 0x00, 0xF6, 0x00
    ])

    with open(sdir_path, "rb") as sdir:
        sdirhead = bytearray(16)
        sdir.readinto(sdirhead)

        is_wii_format = sdirhead[0:4][::-1] == b"SDIR"
        is_ps2_format = sdirhead[0:4] == b"SDIR"

        if is_wii_format:
            num_entries = struct.unpack(">I", sdirhead[0x0C:0x10])[0]
            entry_size = 64
        elif is_ps2_format:
            num_entries = struct.unpack("<I", sdirhead[0x0C:0x10])[0]
            entry_size = 16
        else:
            sdir.seek(0)
            sdir_data = sdir.read()
            num_entries = len(sdir_data) // 32
            entry_size = 32
            sdir.seek(0)

        with open(samp_path, "rb") as samp:
            for i in range(num_entries):
                if is_wii_format:
                    sampinfo = bytearray(64)
                    sdir.readinto(sampinfo)

                    sample_offset = struct.unpack(">I", sampinfo[0x00:0x04])[0]
                    num_nibbles = struct.unpack(">I", sampinfo[0x04:0x08])[0]
                    loop_flag = struct.unpack(">I", sampinfo[0x08:0x0C])[0]
                    dsp_format = struct.unpack(">H", sampinfo[0x0C:0x0E])[0]
                    sample_rate = struct.unpack(">H", sampinfo[0x0E:0x10])[0]
                    coefficients = sampinfo[0x10:0x30]
                    ps = sampinfo[0x33]

                    if num_nibbles > 0:
                        num_samples_calc = nibbles_to_samples(num_nibbles)

                        data_size = (num_nibbles + 1) // 2
                        samp.seek((sample_offset - 2) // 2)
                        adpcm_data = samp.read(data_size)

                        dsp_data = create_dsp_file(num_samples_calc, num_nibbles, sample_rate,
                                                        coefficients, ps, adpcm_data,
                                                        loop_flag=loop_flag,
                                                        loop_start=0,
                                                        loop_end=num_nibbles,
                                                        current_addr=2)
                        dsp_data[0x0E:0x10] = struct.pack(">H", dsp_format)

                        sound_info = {
                            'index': i,
                            'format': 'wii_dsp',
                            'loop_flag': loop_flag,
                            'sample_offset': sample_offset,
                            'data_offset': (sample_offset - 2) // 2,
                            'data_size': data_size,
                            'sample_rate': sample_rate,
                            'num_samples': num_samples_calc,
                            'duration': num_samples_calc / sample_rate if sample_rate > 0 else 0,
                            'dsp_data': dsp_data,
                            'raw_data': adpcm_data,
                            'raw_ext': '.dsp',
                            'coefficients': coefficients,
                            'ps': ps,
                            'adpcm_data': adpcm_data
                        }
                        sounds.append(sound_info)
                elif is_ps2_format:
                    sampinfo = sdir.read(entry_size)
                    if len(sampinfo) < entry_size:
                        break

                    sample_offset = struct.unpack("<I", sampinfo[0x00:0x04])[0]
                    data_size = struct.unpack("<I", sampinfo[0x04:0x08])[0]
                    sample_rate = struct.unpack("<I", sampinfo[0x0C:0x10])[0]

                    if data_size > 0 and sample_offset != 0xFFFFFFFF:
                        samp.seek(sample_offset)
                        adpcm_data = samp.read(data_size)
                        num_samples_calc = (len(adpcm_data) // 16) * 28
                        sound_info = {
                            'index': i,
                            'format': 'ps2_adpcm',
                            'sample_offset': sample_offset,
                            'data_offset': sample_offset,
                            'data_size': data_size,
                            'sample_rate': sample_rate,
                            'num_samples': num_samples_calc,
                            'duration': num_samples_calc / sample_rate if sample_rate > 0 else 0,
                            'dsp_data': adpcm_data,
                            'raw_data': adpcm_data,
                            'raw_ext': '.ps2adpcm',
                            'adpcm_data': adpcm_data
                        }
                        sounds.append(sound_info)
                else:
                    tbl1_offset = i * 32

                    if tbl1_offset + 32 > len(sdir_data):
                        break

                    record1 = sdir_data[tbl1_offset:tbl1_offset + 32]

                    if record1[0:4] == b'\xFF\xFF\xFF\xFF':
                        break

                    sound_id = struct.unpack(">H", record1[0x00:0x02])[0]
                    sample_offset = struct.unpack(">I", record1[0x04:0x08])[0]
                    sample_rate = struct.unpack(">H", record1[0x0E:0x10])[0]
                    num_samples_calc = struct.unpack(">I", record1[0x10:0x14])[0]
                    tbl2_offset = struct.unpack(">I", record1[0x1C:0x20])[0]

                    if num_samples_calc > 0 and sample_offset > 0 and tbl2_offset + 0x28 <= len(sdir_data):
                        record2 = sdir_data[tbl2_offset:tbl2_offset + 0x28]

                        ps = record2[0x02]
                        coefficients = record2[0x08:0x28]

                        frames = (num_samples_calc + 13) // 14
                        num_nibbles = frames * 16
                        data_bytes = num_nibbles // 2

                        samp.seek(sample_offset)
                        adpcm_data = samp.read(data_bytes)

                        dsp_data = create_dsp_file(num_samples_calc, num_nibbles, sample_rate,
                                                        coefficients, ps, adpcm_data)

                        sound_info = {
                            'index': i,
                            'format': 'gc_dsp',
                            'sample_offset': sample_offset,
                            'data_offset': sample_offset,
                            'data_size': data_bytes,
                            'sample_rate': sample_rate,
                            'num_samples': num_samples_calc,
                            'duration': num_samples_calc / sample_rate if sample_rate > 0 else 0,
                            'dsp_data': dsp_data,
                            'raw_data': adpcm_data,
                            'raw_ext': '.dsp',
                            'coefficients': coefficients,
                            'ps': ps,
                            'adpcm_data': adpcm_data
                        }
                        sounds.append(sound_info)

    return sounds

def get_pcm_samples(sound_info):
    if 'pcm_samples' in sound_info:
        return sound_info['pcm_samples']

    sound_format = sound_info.get('format')
    if sound_format == 'ps2_adpcm':
        pcm_samples = decode_ps2_adpcm(
            sound_info['adpcm_data'], sound_info.get('num_samples')
        )
    else:
        pcm_samples = decode_dsp_adpcm(
            sound_info['adpcm_data'],
            sound_info['coefficients'],
            sound_info['ps'],
            sound_info['num_samples']
        )

    sound_info['pcm_samples'] = pcm_samples
    return pcm_samples

def decode_wav_sample(audio_data, offset, bits_per_sample, audio_format):
    if audio_format == 3:
        if bits_per_sample == 32:
            value = struct.unpack_from("<f", audio_data, offset)[0]
        elif bits_per_sample == 64:
            value = struct.unpack_from("<d", audio_data, offset)[0]
        else:
            raise ValueError(f"Unsupported IEEE float WAV bit depth: {bits_per_sample}")

        value = max(-1.0, min(1.0, value))
        return int(value * 32767)

    if audio_format != 1:
        raise ValueError(f"Unsupported WAV format: {audio_format}")

    if bits_per_sample == 8:
        return (audio_data[offset] - 128) << 8
    if bits_per_sample == 16:
        return struct.unpack_from("<h", audio_data, offset)[0]
    if bits_per_sample == 24:
        raw = audio_data[offset:offset + 3]
        value = int.from_bytes(raw + (b"\xFF" if raw[2] & 0x80 else b"\x00"),
                               byteorder="little", signed=True)
        return max(-32768, min(32767, value >> 8))
    if bits_per_sample == 32:
        value = struct.unpack_from("<i", audio_data, offset)[0]
        return max(-32768, min(32767, value >> 16))

    raise ValueError(f"Unsupported PCM WAV bit depth: {bits_per_sample}")

def read_wav_file(wav_path):
    with open(wav_path, "rb") as wav:
        data = wav.read()

    if len(data) < 12 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("Not a valid RIFF/WAVE file")

    fmt_chunk = None
    data_chunk = None
    pos = 12
    while pos + 8 <= len(data):
        chunk_id = data[pos:pos + 4]
        chunk_size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        chunk_start = pos + 8
        chunk_end = chunk_start + chunk_size

        if chunk_id == b"fmt ":
            fmt_chunk = data[chunk_start:chunk_end]
        elif chunk_id == b"data":
            data_chunk = data[chunk_start:chunk_end]

        pos = chunk_end + (chunk_size % 2)

    if fmt_chunk is None or data_chunk is None:
        raise ValueError("WAV file is missing fmt or data chunk")
    if len(fmt_chunk) < 16:
        raise ValueError("WAV fmt chunk is too small")

    audio_format, num_channels, sample_rate, _byte_rate, block_align, bits_per_sample = struct.unpack(
        "<HHIIHH", fmt_chunk[:16]
    )

    if audio_format == 0xFFFE and len(fmt_chunk) >= 40:
        audio_format = struct.unpack("<H", fmt_chunk[24:26])[0]

    if num_channels <= 0 or block_align <= 0:
        raise ValueError("Invalid WAV channel or block alignment")

    bytes_per_sample = (bits_per_sample + 7) // 8
    if bytes_per_sample <= 0:
        raise ValueError("Invalid WAV bit depth")

    frame_count = len(data_chunk) // block_align
    samples = []

    for frame in range(frame_count):
        frame_offset = frame * block_align
        channel_samples = []
        for channel in range(num_channels):
            sample_offset = frame_offset + (channel * bytes_per_sample)
            if sample_offset + bytes_per_sample <= len(data_chunk):
                channel_samples.append(
                    decode_wav_sample(data_chunk, sample_offset, bits_per_sample, audio_format)
                )

        if channel_samples:
            samples.append(sum(channel_samples) // len(channel_samples))

    return samples, sample_rate

def write_wav(filename, samples, sample_rate):
    with wave.open(filename, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)

        chunk_size = 65536
        for start in range(0, len(samples), chunk_size):
            chunk = samples[start:start + chunk_size]
            wav_data = bytearray(len(chunk) * 2)
            for idx, sample in enumerate(chunk):
                struct.pack_into('<h', wav_data, idx * 2, sample)
            wav.writeframesraw(wav_data)

def resample_audio(samples, original_rate, target_rate):
    if original_rate == target_rate:
        return samples

    ratio = target_rate / original_rate
    new_length = int(len(samples) * ratio)

    resampled = []
    for i in range(new_length):
        src_pos = i / ratio
        src_index = int(src_pos)
        frac = src_pos - src_index

        if src_index + 1 < len(samples):
            sample = int(samples[src_index] * (1 - frac) + samples[src_index + 1] * frac)
        else:
            sample = samples[src_index]

        resampled.append(sample)

    return resampled

def build_ps2_replacement_from_file(index, wav_path, raw_path, sample_rate, template_adpcm_data):
    wav_exists = os.path.exists(wav_path)
    raw_exists = os.path.exists(raw_path)

    if raw_exists and not wav_exists:
        with open(raw_path, "rb") as raw:
            adpcm_data = raw.read()
        return {
            'index': index,
            'adpcm_data': adpcm_data,
            'sample_rate': sample_rate,
            'source': 'raw',
            'bytes': len(adpcm_data)
        }

    if not wav_exists:
        raise FileNotFoundError(f"No WAV or PS2 ADPCM file found for Sound {index:02d}")

    samples, wav_sample_rate = read_wav_file(wav_path)
    if wav_sample_rate != sample_rate:
        samples = resample_audio(samples, wav_sample_rate, sample_rate)

    adpcm_data = encode_ps2_adpcm(samples)
    adpcm_data = apply_ps2_frame_flag_template(adpcm_data, template_adpcm_data)

    with open(raw_path, "wb") as raw:
        raw.write(adpcm_data)

    return {
        'index': index,
        'adpcm_data': adpcm_data,
        'sample_rate': sample_rate,
        'source': 'wav',
        'bytes': len(adpcm_data)
    }

def find_pattern_in_file(file_path, pattern):
    with open(file_path, 'rb') as f:
        data = f.read()
        offset = data.find(pattern)
        return offset if offset != -1 else None

def replace_bytes_in_file(file_path, offset, new_data):
    with open(file_path, 'r+b') as f:
        f.seek(offset)
        f.write(new_data)
