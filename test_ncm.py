# -*- coding: utf-8 -*-
"""NCM 解密自测：构造反向加密的 NCM，验证 ncm_dump 往返正确。"""
import base64
import json
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from binascii import a2b_hex, b2a_hex

from Crypto.Cipher import AES

from tools.ncm2mp3_tool import (
    CORE_KEY, META_KEY, MAGIC, build_key_box, ncm_dump, _detect_format, _xor_stream,
)


def _pad(data: bytes) -> bytes:
    n = 16 - len(data) % 16
    return data + bytes([n]) * n


def _keystream_ks(key: bytes) -> bytes:
    """与 ncm_dump 相同的密钥流：第 p 字节用 j = (p+1) & 0xFF（参照 C++ j=(i+1)&0xff）。

    注意 0x8000 分块与 256 周期整除，故等效于全局周期 256。
    """
    box = build_key_box(key)
    out = []
    for p in range(256):
        j = (p + 1) & 0xFF
        out.append(box[(box[j] + box[(box[j] + j) & 0xFF]) & 0xFF])
    return bytes(out)


def make_ncm(audio: bytes, meta: dict, cover: bytes) -> bytes:
    """构造一个合法 NCM（反向流程）。"""
    # 1. key：随机 128 字节（实际是 RC4 key，任意内容均可）
    key = os.urandom(107)  # 任意长度
    key_block = b"neteasecloudmusic" + key
    key_enc = AES.new(CORE_KEY, AES.MODE_ECB).encrypt(_pad(key_block))
    key_enc = bytes(b ^ 0x64 for b in key_enc)

    # 2. meta
    meta_json = json.dumps(meta, ensure_ascii=False).encode("utf-8")
    meta_block = b"music:" + meta_json
    m_enc = AES.new(META_KEY, AES.MODE_ECB).encrypt(_pad(meta_block))
    # base64 后加 22 字节头
    meta_enc = b"163 key(Don't modify):" + base64.b64encode(m_enc)
    meta_enc = bytes(b ^ 0x63 for b in meta_enc)

    # 3. cover（frame_len = img_len，无补齐）
    # 4. audio 加密
    ks = _keystream_ks(key)
    audio_enc = _xor_stream(audio, ks)

    out = bytearray()
    out += MAGIC
    out += b"\x02\x00"  # gap
    out += struct.pack("<I", len(key_enc)) + key_enc
    out += struct.pack("<I", len(meta_enc)) + meta_enc
    out += b"\x00" * 4      # crc
    out += b"\x01"          # img version
    out += struct.pack("<I", len(cover))  # frame_len
    out += struct.pack("<I", len(cover))  # img_len
    out += cover
    out += audio_enc
    return bytes(out)


def test_roundtrip():
    # 模拟 MP3（ID3 头）
    audio = b"ID3\x04\x00\x00\x00\x00\x00\x00" + os.urandom(4096)
    meta = {
        "musicName": "测试歌曲",
        "artist": [["测试歌手"]],
        "album": "测试专辑",
        "format": "mp3",
        "bitrate": 320000,
    }
    cover = b"\xff\xd8\xff\xe0" + os.urandom(2048) + b"\xff\xd9"  # 假 JPEG

    ncm = make_ncm(audio, meta, cover)
    print(f"[1] 构造 NCM：{len(ncm)} 字节")

    audio2, meta2, cover2 = ncm_dump(ncm)
    assert audio2 == audio, "音频往返不一致！"
    assert cover2 == cover, "封面往返不一致！"
    assert meta2.get("musicName") == "测试歌曲", f"元数据错误: {meta2}"
    assert meta2.get("artist") == [["测试歌手"]], f"歌手错误: {meta2.get('artist')}"
    fmt = _detect_format(audio2, meta2)
    assert fmt == "mp3", f"格式识别错误: {fmt}"
    print(f"[2] 往返验证 ✓ 音频 {len(audio2)}B 封面 {len(cover2)}B 格式 {fmt}")
    print(f"[3] 元数据 ✓ {meta2.get('musicName')} - {meta2.get('artist')[0][0]}")

    # FLAC 格式识别
    audio_flac = b"fLaC" + os.urandom(1024)
    ncm2 = make_ncm(audio_flac, {"musicName": "f", "format": "flac"}, b"")
    a3, m3, c3 = ncm_dump(ncm2)
    assert a3 == audio_flac
    assert _detect_format(a3, m3) == "flac"
    print("[4] FLAC 识别 ✓")

    # 大文件性能（10MB）
    import time
    big = b"ID3" + os.urandom(10 * 1024 * 1024)
    ncm3 = make_ncm(big, {}, b"")
    t0 = time.time()
    a4, _, _ = ncm_dump(ncm3)
    dt = time.time() - t0
    assert a4 == big
    print(f"[5] 10MB 性能 ✓ {dt:.2f}s")

    # 错误文件
    try:
        ncm_dump(b"garbage!" + b"\x00" * 100)
        assert False, "应该抛异常"
    except ValueError as e:
        print(f"[6] 非法文件拒绝 ✓ ({e})")

    print("\n全部通过！")


if __name__ == "__main__":
    test_roundtrip()
