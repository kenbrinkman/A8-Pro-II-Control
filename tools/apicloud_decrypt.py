#!/usr/bin/env python3
"""Standalone APICloud/uzmap widget decryptor (no external deps).

Key recovery, per newdive/uzmap-resource-extractor:
  .rodata of libsec.so contains
    [0 : 20*4]  -> 20 little-endian uint32 indices, each in [0,0x20)
    ...
    just before the JNI class string "com/uzmap/pkg/uzcore/external/Enslecb"
    sit 4 blocks of 9 bytes: 8 hex chars + NUL  -> concatenated = 32-char keyStr
  rc4key = ''.join(keyStr[i] for i in indices)   (20 chars)
Files are then standard RC4.
"""
import os, sys, struct, zipfile, math, collections

JNI = b'com/uzmap/pkg/uzcore/external/Enslecb'
HEXSET = set(b'0123456789abcdefABCDEF')


def elf_section(data, name):
    """Return the bytes of a named section from an ELF32/ELF64 image."""
    assert data[:4] == b'\x7fELF', 'not an ELF'
    is64 = data[4] == 2
    little = data[5] == 1
    e = '<' if little else '>'
    if is64:
        e_shoff = struct.unpack_from(e + 'Q', data, 0x28)[0]
        e_shentsize = struct.unpack_from(e + 'H', data, 0x3A)[0]
        e_shnum = struct.unpack_from(e + 'H', data, 0x3C)[0]
        e_shstrndx = struct.unpack_from(e + 'H', data, 0x3E)[0]
        fmt, off_o, off_s, off_n = e + 'IIQQQQIIQQ', 3, 4, 0
    else:
        e_shoff = struct.unpack_from(e + 'I', data, 0x20)[0]
        e_shentsize = struct.unpack_from(e + 'H', data, 0x2E)[0]
        e_shnum = struct.unpack_from(e + 'H', data, 0x30)[0]
        e_shstrndx = struct.unpack_from(e + 'H', data, 0x32)[0]
        fmt, off_o, off_s, off_n = e + 'IIIIIIIIII', 4, 5, 0

    def sh(i):
        raw = data[e_shoff + i * e_shentsize: e_shoff + (i + 1) * e_shentsize]
        v = struct.unpack(fmt, raw[:struct.calcsize(fmt)])
        return v[off_n], v[off_o], v[off_s]     # name_off, offset, size

    _, strtab_off, strtab_size = sh(e_shstrndx)
    strtab = data[strtab_off:strtab_off + strtab_size]
    for i in range(e_shnum):
        n_off, off, size = sh(i)
        end = strtab.find(b'\x00', n_off)
        if strtab[n_off:end].decode() == name:
            return data[off:off + size]
    return None


def find_hex_block(rodata, end_idx):
    """Walk backwards from end_idx for 4 consecutive 9-byte (8 hex + NUL) blocks."""
    start = end_idx - 9 * 4
    while start >= 0:
        ok, skip = True, 1
        for i in range(4):
            b = rodata[start + i * 9: start + i * 9 + 9]
            if len(b) < 9 or b[8] != 0 or any(c not in HEXSET for c in b[:8]):
                ok = False
                if i > 0:
                    skip = (4 - i) * 9
                break
        if ok:
            return start, start + 9 * 4
        start -= skip
    return -1, -1


def rc4(data, key):
    if isinstance(key, str):
        key = key.encode()
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) & 0xFF
        S[i], S[j] = S[j], S[i]
    out = bytearray(len(data))
    i = j = 0
    for n, c in enumerate(data):
        i = (i + 1) & 0xFF
        j = (j + S[i]) & 0xFF
        S[i], S[j] = S[j], S[i]
        out[n] = c ^ S[(S[i] + S[j]) & 0xFF]
    return bytes(out)


def entropy(b):
    if not b:
        return 0.0
    c = collections.Counter(b)
    n = len(b)
    return -sum((v / n) * math.log2(v / n) for v in c.values()) / 8.0


def extract_key(so_bytes, sample=None):
    ro = elf_section(so_bytes, '.rodata')
    if not ro:
        return None
    pkg = ro.find(JNI)
    if pkg < 0:
        return None
    bs, be = find_hex_block(ro, pkg)
    if bs < 0:
        return None
    key_str = ro[bs:be].replace(b'\x00', b'').decode()
    little = so_bytes[5] == 1
    f = '<I' if little else '>I'

    def build(idx):
        return ''.join(key_str[i] for i in idx)

    if be == pkg:
        idx = [struct.unpack_from(f, ro, i)[0] for i in range(0, 20 * 4, 4)]
        if all(0 <= v < 0x20 for v in idx):
            return build(idx), key_str, idx
    # fallback: slide a 20-wide window of valid indices, score by decrypted entropy
    best = None
    vals = []
    p = 0
    while p + 4 <= bs:
        v = struct.unpack_from(f, ro, p)[0]
        if v >= 0x20:
            vals = []
        else:
            vals.append(v)
            if len(vals) >= 20:
                cand = build(vals[-20:])
                if sample is not None:
                    if entropy(rc4(sample, cand)) < 0.7:
                        return cand, key_str, vals[-20:]
                else:
                    best = best or (cand, key_str, vals[-20:])
        p += 4
    return best


def main(apk, outdir):
    z = zipfile.ZipFile(apk)
    names = z.namelist()

    conf = z.read('assets/widget/config.xml')
    encrypted = conf.find(b'<?xml') == -1
    print(f'resources encrypted: {encrypted}')
    if not encrypted:
        print('nothing to do')
        return

    targets = [n for n in names
               if n.startswith('assets/widget/')
               and (n.rsplit('.', 1)[-1] in ('js', 'html', 'css')
                    or n.endswith('config.xml') or n.endswith('key.xml'))]
    sample = min((n for n in targets if z.getinfo(n).file_size > 0),
                 key=lambda n: z.getinfo(n).file_size)
    sample_bytes = z.read(sample)

    key = None
    for n in names:
        if n.startswith('lib/') and n.endswith('libsec.so'):
            r = extract_key(z.read(n), sample_bytes)
            if r:
                key, key_str, idx = r
                print(f'libsec: {n}')
                print(f'keyStr (32): {key_str}')
                print(f'indices    : {idx}')
                print(f'RC4 KEY    : {key}')
                break
    if not key:
        print('FAILED to recover key')
        return

    check = rc4(conf, key)
    print(f'config.xml check: {check[:40]!r}')
    if b'<?xml' not in check[:200]:
        print('!! key looks wrong')
        return

    n_ok = 0
    for n in targets:
        raw = z.read(n)
        dec = rc4(raw, key) if entropy(raw) >= 0.9 else raw
        dst = os.path.join(outdir, n)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, 'wb') as f:
            f.write(dec)
        n_ok += 1
    # copy through the non-encrypted assets too (images, fonts, json)
    for n in names:
        if n.startswith('assets/widget/') and n not in targets and not n.endswith('/'):
            dst = os.path.join(outdir, n)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, 'wb') as f:
                f.write(z.read(n))
    print(f'decrypted {n_ok} files -> {outdir}')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
