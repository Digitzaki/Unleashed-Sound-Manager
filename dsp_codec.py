import struct

def nibbles_to_samples(nibbles):
    whole_frames = nibbles // 16
    remainder = nibbles % 16
    if remainder > 0:
        return (whole_frames * 14) + (remainder - 2)
    else:
        return whole_frames * 14

def decode_dsp_adpcm(data, coefs, ps_initial, num_samples):
    hist1 = 0
    hist2 = 0
    samples = []

    coef_table = []
    for i in range(8):
        c1 = struct.unpack(">h", coefs[i*4:i*4+2])[0]
        c2 = struct.unpack(">h", coefs[i*4+2:i*4+4])[0]
        coef_table.append((c1, c2))

    ps = ps_initial

    byte_pos = 0
    sample_count = 0

    while sample_count < num_samples and byte_pos < len(data):
        if sample_count % 14 == 0:
            if byte_pos < len(data):
                ps = data[byte_pos]
                byte_pos += 1
            else:
                break

            predictor = (ps >> 4) & 0x0F
            scale = ps & 0x0F

            if predictor >= len(coef_table):
                predictor = 0

            coef1, coef2 = coef_table[predictor]

        if byte_pos >= len(data):
            break

        byte = data[byte_pos]
        nibble1 = (byte >> 4) & 0x0F
        nibble2 = byte & 0x0F

        for nibble in [nibble1, nibble2]:
            if sample_count >= num_samples:
                break

            if nibble >= 8:
                nibble = nibble - 16

            sample = (nibble << scale) << 11
            sample = (sample + coef1 * hist1 + coef2 * hist2 + 1024) >> 11

            sample = max(-32768, min(32767, sample))

            samples.append(sample)

            hist2 = hist1
            hist1 = sample

            sample_count += 1

        byte_pos += 1

    return samples

def encode_dsp_adpcm(samples, coefs):
    encoded = bytearray()
    hist1 = 0
    hist2 = 0

    coef_table = []
    for i in range(8):
        c1 = struct.unpack(">h", coefs[i*4:i*4+2])[0]
        c2 = struct.unpack(">h", coefs[i*4+2:i*4+4])[0]
        coef_table.append((c1, c2))

    i = 0
    while i < len(samples):
        frame_samples = samples[i:i+14]
        if len(frame_samples) == 0:
            break

        best_predictor = 0
        best_error = float('inf')

        for predictor in range(8):
            error = 0
            temp_h1 = hist1
            temp_h2 = hist2
            for sample in frame_samples:
                predicted = (coef_table[predictor][0] * temp_h1 + coef_table[predictor][1] * temp_h2) >> 11
                error += abs(sample - predicted)
                temp_h2 = temp_h1
                temp_h1 = sample
            if error < best_error:
                best_error = error
                best_predictor = predictor

        scale = 0
        best_scale_error = float('inf')

        for test_scale in range(0, 13):
            temp_hist1 = hist1
            temp_hist2 = hist2
            max_quantized = 0

            for sample in frame_samples:
                predicted = (coef_table[best_predictor][0] * temp_hist1 + coef_table[best_predictor][1] * temp_hist2) >> 11
                diff = sample - predicted

                nibble = diff >> test_scale
                nibble = max(-8, min(7, nibble))

                reconstructed = (nibble << test_scale) << 11
                reconstructed = (reconstructed + coef_table[best_predictor][0] * temp_hist1 + coef_table[best_predictor][1] * temp_hist2 + 1024) >> 11
                reconstructed = max(-32768, min(32767, reconstructed))

                error = abs(sample - reconstructed)
                if error > max_quantized:
                    max_quantized = error

                temp_hist2 = temp_hist1
                temp_hist1 = reconstructed

            if max_quantized < best_scale_error:
                best_scale_error = max_quantized
                scale = test_scale

            if max_quantized < 256:
                break

        ps_byte = (best_predictor << 4) | scale
        encoded.append(ps_byte)

        temp_hist1 = hist1
        temp_hist2 = hist2
        nibbles = []

        for sample in frame_samples:
            predicted = (coef_table[best_predictor][0] * temp_hist1 + coef_table[best_predictor][1] * temp_hist2) >> 11
            diff = sample - predicted

            nibble = diff >> scale
            nibble = max(-8, min(7, nibble))
            nibbles.append(nibble & 0x0F)

            reconstructed = (nibble << scale) << 11
            reconstructed = (reconstructed + coef_table[best_predictor][0] * temp_hist1 + coef_table[best_predictor][1] * temp_hist2 + 1024) >> 11
            reconstructed = max(-32768, min(32767, reconstructed))

            temp_hist2 = temp_hist1
            temp_hist1 = reconstructed

        while len(nibbles) < 14:
            nibbles.append(0)

        for j in range(0, 14, 2):
            byte = (nibbles[j] << 4) | nibbles[j+1]
            encoded.append(byte)

        hist1 = temp_hist1
        hist2 = temp_hist2
        i += 14

    return bytes(encoded)

def create_dsp_file(num_samples, num_nibbles, sample_rate, coefficients, ps, adpcm_data):
    dspbuf = bytearray(96 + len(adpcm_data))

    dspbuf[0x00:0x04] = struct.pack(">I", num_samples)
    dspbuf[0x04:0x08] = struct.pack(">I", num_nibbles)
    dspbuf[0x08:0x0C] = struct.pack(">I", sample_rate)
    dspbuf[0x0C:0x0E] = struct.pack(">H", 0)
    dspbuf[0x0E:0x10] = struct.pack(">H", 0)
    dspbuf[0x10:0x14] = struct.pack(">I", 0)
    dspbuf[0x14:0x18] = struct.pack(">I", 0)
    dspbuf[0x18:0x1C] = struct.pack(">I", 2)
    dspbuf[0x1C:0x3C] = coefficients
    dspbuf[0x3C:0x3E] = struct.pack(">H", 0)
    dspbuf[0x3E:0x40] = b"\0" + bytes([ps])
    dspbuf[0x40:0x42] = struct.pack(">H", 0)
    dspbuf[0x42:0x44] = struct.pack(">H", 0)
    dspbuf[0x44:0x46] = struct.pack(">H", 0)
    dspbuf[0x46:0x48] = struct.pack(">H", 0)
    dspbuf[0x48:0x4A] = struct.pack(">H", 0)
    dspbuf[0x4A:0x60] = b"\0" * 22

    dspbuf[0x60:len(dspbuf)] = adpcm_data

    return dspbuf
