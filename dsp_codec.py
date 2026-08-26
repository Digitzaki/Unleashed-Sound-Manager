import struct

PS2_ADPCM_COEFS = [
    (0, 0),
    (60, 0),
    (115, -52),
    (98, -55),
    (122, -60),
]

def calculate_coefficients(samples):
    """Calculate optimal ADPCM coefficients using autocorrelation."""

    # Calculate autocorrelation for lags 0, 1, 2
    r = [0.0, 0.0, 0.0]

    for i in range(len(samples)):
        r[0] += samples[i] * samples[i]
        if i > 0:
            r[1] += samples[i] * samples[i-1]
        if i > 1:
            r[2] += samples[i] * samples[i-2]

    # Avoid division by zero
    if r[0] == 0:
        r[0] = 1.0

    # Normalize
    r[1] /= r[0]
    r[2] /= r[0]
    r[0] = 1.0

    # Solve Yule-Walker equations for order 2
    # [ r0  r1 ] [ a1 ]   [ r1 ]
    # [ r1  r0 ] [ a2 ] = [ r2 ]

    det = r[0] * r[0] - r[1] * r[1]
    if abs(det) < 1e-10:
        det = 1e-10

    a1 = (r[0] * r[1] - r[1] * r[2]) / det
    a2 = (r[0] * r[2] - r[1] * r[1]) / det

    # Clamp to valid range for 16-bit signed coefficients
    a1 = max(-2.0, min(2.0, a1))
    a2 = max(-2.0, min(2.0, a2))

    # Convert to fixed-point (Q11 format: multiply by 2048)
    coef1_int = int(a1 * 2048)
    coef2_int = int(a2 * 2048)

    # Clamp to 16-bit signed range
    coef1_int = max(-32768, min(32767, coef1_int))
    coef2_int = max(-32768, min(32767, coef2_int))

    # Create coefficient table (8 pairs, but we'll use the first pair for all)
    coefs = bytearray(32)
    struct.pack_into(">h", coefs, 0, coef1_int)
    struct.pack_into(">h", coefs, 2, coef2_int)

    # Fill remaining 7 pairs with copies (simple approach)
    for i in range(1, 8):
        coefs[i*4:i*4+4] = coefs[0:4]

    return bytes(coefs)

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

def create_dsp_file(
    num_samples, num_nibbles, sample_rate, coefficients, ps, adpcm_data,
    loop_flag=0, loop_start=0, loop_end=0, current_addr=2
):
    dspbuf = bytearray(96 + len(adpcm_data))

    dspbuf[0x00:0x04] = struct.pack(">I", num_samples)
    dspbuf[0x04:0x08] = struct.pack(">I", num_nibbles)
    dspbuf[0x08:0x0C] = struct.pack(">I", sample_rate)
    dspbuf[0x0C:0x0E] = struct.pack(">H", loop_flag)
    dspbuf[0x0E:0x10] = struct.pack(">H", 0)
    dspbuf[0x10:0x14] = struct.pack(">I", loop_start)
    dspbuf[0x14:0x18] = struct.pack(">I", loop_end)
    dspbuf[0x18:0x1C] = struct.pack(">I", current_addr)
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

def decode_ps2_adpcm(data, num_samples=None):
    hist1 = 0
    hist2 = 0
    samples = []

    for frame_start in range(0, len(data) - 15, 16):
        frame = data[frame_start:frame_start + 16]
        predict_shift = frame[0]
        predictor = (predict_shift >> 4) & 0x0F
        shift = predict_shift & 0x0F

        if predictor >= len(PS2_ADPCM_COEFS):
            predictor = 0

        coef1, coef2 = PS2_ADPCM_COEFS[predictor]

        for byte in frame[2:16]:
            for nibble in (byte & 0x0F, (byte >> 4) & 0x0F):
                if num_samples is not None and len(samples) >= num_samples:
                    return samples

                if nibble >= 8:
                    nibble -= 16

                sample = (nibble << 12) >> shift
                sample += ((hist1 * coef1) + (hist2 * coef2) + 32) >> 6
                sample = max(-32768, min(32767, sample))

                samples.append(sample)
                hist2 = hist1
                hist1 = sample

    return samples

def encode_ps2_adpcm(samples):
    encoded = bytearray()
    hist1 = 0
    hist2 = 0

    for frame_start in range(0, len(samples), 28):
        frame_samples = samples[frame_start:frame_start + 28]
        if not frame_samples:
            break

        best_frame = None
        best_error = None
        best_hist1 = hist1
        best_hist2 = hist2

        for predictor, (coef1, coef2) in enumerate(PS2_ADPCM_COEFS):
            for shift in range(0, 13):
                temp_hist1 = hist1
                temp_hist2 = hist2
                nibbles = []
                error = 0

                for sample in frame_samples:
                    predicted = ((temp_hist1 * coef1) + (temp_hist2 * coef2) + 32) >> 6
                    diff = sample - predicted
                    nibble = int(round(diff / float(1 << (12 - shift))))
                    nibble = max(-8, min(7, nibble))

                    reconstructed = (nibble << 12) >> shift
                    reconstructed += ((temp_hist1 * coef1) + (temp_hist2 * coef2) + 32) >> 6
                    reconstructed = max(-32768, min(32767, reconstructed))

                    error += abs(sample - reconstructed)
                    nibbles.append(nibble & 0x0F)
                    temp_hist2 = temp_hist1
                    temp_hist1 = reconstructed

                if best_error is None or error < best_error:
                    best_error = error
                    best_frame = (predictor << 4) | shift, nibbles
                    best_hist1 = temp_hist1
                    best_hist2 = temp_hist2

        predict_shift, nibbles = best_frame
        while len(nibbles) < 28:
            nibbles.append(0)

        encoded.append(predict_shift)
        encoded.append(0)
        for i in range(0, 28, 2):
            encoded.append(nibbles[i] | (nibbles[i + 1] << 4))

        hist1 = best_hist1
        hist2 = best_hist2

    if encoded:
        frame_count = len(encoded) // 16
        encoded[1] = 0x04
        encoded[((frame_count - 1) * 16) + 1] = 0x01

    return bytes(encoded)

def apply_ps2_frame_flag_template(adpcm_data, template_adpcm_data):
    if not adpcm_data or not template_adpcm_data:
        return adpcm_data

    new_data = bytearray(adpcm_data)
    new_frame_count = len(new_data) // 16
    template_frame_count = len(template_adpcm_data) // 16
    if new_frame_count == 0 or template_frame_count == 0:
        return bytes(new_data)

    template_flags = [
        template_adpcm_data[(frame * 16) + 1]
        for frame in range(template_frame_count)
    ]

    first_flag = template_flags[0]
    middle_flags = template_flags[1:-1]
    if middle_flags:
        body_flag = max(set(middle_flags), key=middle_flags.count)
    else:
        body_flag = template_flags[-1]

    trailing_flags = []
    for flag in reversed(template_flags):
        if flag == body_flag and trailing_flags:
            break
        trailing_flags.append(flag)
    trailing_flags.reverse()
    if not trailing_flags:
        trailing_flags = [template_flags[-1]]

    for frame in range(new_frame_count):
        new_data[(frame * 16) + 1] = body_flag

    new_data[1] = first_flag
    trailing_count = min(len(trailing_flags), new_frame_count)
    for i in range(trailing_count):
        frame = new_frame_count - trailing_count + i
        new_data[(frame * 16) + 1] = trailing_flags[i]

    return bytes(new_data)
