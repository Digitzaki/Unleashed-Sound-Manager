import os
import struct
import wave
from dsp_codec import nibbles_to_samples, decode_dsp_adpcm, create_dsp_file

def extract_sdir_from_uber(uber_path, silent=False):
    uber_size = os.path.getsize(uber_path)
    sdir_path = None

    with open(uber_path, "rb") as uber:
        uber.seek(0x08)
        offsets = []
        offset = struct.unpack(">I", uber.read(4))[0]
        offsets.append(offset)

        while uber.tell() < offsets[0]:
            offset = struct.unpack(">I", uber.read(4))[0]
            offsets.append(offset)
        offsets.append(uber_size)

        i = 0
        while uber.tell() < uber_size and i < len(offsets):
            size = offsets[i+1] - uber.tell()
            outbuf = uber.read(size)

            try:
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

def load_sound_data(sdir_path, samp_path):
    sounds = []

    with open(sdir_path, "rb") as sdir:
        sdirhead = bytearray(16)
        sdir.readinto(sdirhead)

        if sdirhead[0:4][::-1] != b"SDIR":
            return sounds

        num_samples = struct.unpack(">I", sdirhead[0x0C:0x10])[0]

        with open(samp_path, "rb") as samp:
            for i in range(num_samples):
                sampinfo = bytearray(64)
                sdir.readinto(sampinfo)

                sample_offset = struct.unpack(">I", sampinfo[0x00:0x04])[0]
                num_nibbles = struct.unpack(">I", sampinfo[0x04:0x08])[0]
                sample_rate = struct.unpack(">H", sampinfo[0x0E:0x10])[0]
                coefficients = sampinfo[0x10:0x30]
                ps = sampinfo[0x33]

                if num_nibbles > 0:
                    num_samples_calc = nibbles_to_samples(num_nibbles)

                    samp.seek((sample_offset - 2) // 2)
                    adpcm_data = samp.read(num_nibbles // 2)

                    dsp_data = create_dsp_file(num_samples_calc, num_nibbles, sample_rate,
                                                    coefficients, ps, adpcm_data)

                    pcm_samples = decode_dsp_adpcm(adpcm_data, coefficients, ps, num_samples_calc)

                    sound_info = {
                        'index': i,
                        'sample_rate': sample_rate,
                        'num_samples': num_samples_calc,
                        'duration': num_samples_calc / sample_rate if sample_rate > 0 else 0,
                        'dsp_data': dsp_data,
                        'pcm_samples': pcm_samples,
                        'coefficients': coefficients,
                        'ps': ps,
                        'adpcm_data': adpcm_data
                    }
                    sounds.append(sound_info)

    return sounds

def read_wav_file(wav_path):
    with wave.open(wav_path, 'rb') as wav:
        sample_rate = wav.getframerate()
        num_channels = wav.getnchannels()
        num_samples = wav.getnframes()
        audio_data = wav.readframes(num_samples)

        samples = []

        if num_channels == 2:
            for i in range(0, len(audio_data), 4):
                left = struct.unpack('<h', audio_data[i:i+2])[0]
                right = struct.unpack('<h', audio_data[i+2:i+4])[0]
                mono_sample = (left + right) // 2
                samples.append(mono_sample)
        else:
            for i in range(0, len(audio_data), 2):
                sample = struct.unpack('<h', audio_data[i:i+2])[0]
                samples.append(sample)

        return samples, sample_rate

def write_wav(filename, samples, sample_rate):
    with wave.open(filename, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)

        wav_data = b''
        for sample in samples:
            wav_data += struct.pack('<h', sample)

        wav.writeframes(wav_data)

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

def find_pattern_in_file(file_path, pattern):
    with open(file_path, 'rb') as f:
        data = f.read()
        offset = data.find(pattern)
        return offset if offset != -1 else None

def replace_bytes_in_file(file_path, offset, new_data):
    with open(file_path, 'r+b') as f:
        f.seek(offset)
        f.write(new_data)
