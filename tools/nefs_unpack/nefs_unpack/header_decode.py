from __future__ import annotations

import struct
from typing import List, Optional

from .constants import DEFAULT_RSA_EXPONENT, FOUR_CC, INTRO_SIZE

# Public modulus (RSA-1024) for various EGO titles.
# NOTE: NefsLib constructs these via `new BigInteger(bytes, true)` i.e.
# little-endian word order.  We therefore treat the plain bytes as a
# little-endian integer below (see decrypt_header_intro_rsa).
RSA_KEYS: List[bytes] = [
    # DiRT Rally 2 (default)
    bytes.fromhex(
        "CF1963941E0F421635DE51D0B33AB767C71C8D3B2749409E5843DD6DD9AAF51B"
        "9494C43049BAE7723DFADF801755F3ABF89742E6B2DF11E4930E921DC54E0F87"
        "CD4683066B97A7004235B033EAEF6854A0F90341F75CFFC375E11B00735A7A81"
        "68AFB49F863CD6093AC0946F18E2033814F7C513914ED04FAC466C7027ED6999"
    ),
    # DiRT 2, F1 2010, RD:Grid
    bytes.fromhex(
        "E5379EFBAA66E6ACBBEFECB5A7C3C070684D9BD17CF4A14C2C639BA002D8F6DE"
        "3691BA52D5B44189FC1A5F225EC10526A058CAAF0317D86B0104EE58AA1A4769"
        "EED927C6CF0ECB81136D6F51D1A65FA3D9A1C67DBB134F8BB5E6AC1627B4EB7F"
        "9832865A6905B0729C9DEE06F0CD0B45ADACB33791C49F1A468D9F4920F08484"
    ),
    # F1 2011-2014
    bytes.fromhex(
        "35AE6F6783C163661B2E5F0DE2BF4399EAECA47A7F9400FA9E9025ECE2CF51FD"
        "DBAD450098AE29F3017C8A8BCAC64DC26D69FE03797128134D1D0BE81382A62D"
        "DEB796B2DB12A82B86E8CB07EF59FC2B35917C9C22299971E07865AF4236C307"
        "A8AABF0E9B3C857ACBA8086BC6A2867FEC3677F348CC70CE5B8B6FB1457DB9"
    ),
    # DiRT 3
    bytes.fromhex(
        "E1209092B124E2F498C1F48EF9265B18FD24A4B7D6B064B0D7A4568D4695CB0C"
        "D11A63661D9608432BC0CCFA74A5DE1F8B8A683ADEC9724591074B4AC4050EE4"
        "81B05D5279390D09AEB09DF7CC09A1C98EFB24E71EC7AC6D88900B1271341CC4"
        "2B8FDC4D701730385CF2FBC984A1E7C9061435D91EF47E98E94E5635BA23148C"
    ),
    # Grid Autosport
    bytes.fromhex(
        "0F00756D8DB8FBE385B4A115715D57FCA7929534BDAA2C81635B64A5F0D01858"
        "CE0719640C52E060C0E59B314CFBE3CB61EB7C45C40D57B4E391A1F72117C69C"
        "7012DC18F304C21A2BB7C266ED9674A00AF1EEEF61BAD04AD3F868E09D47DF16"
        "4108FC8CD9D153B47A52C171B6DAAF43484236878DCB1E6724009C6A11477F87"
    ),
    # Grid 2
    bytes.fromhex(
        "D9AEBEE86023C6CEF41FC490A8AECCD7A96636B29C02A5EA4B1590FCFF01894D"
        "573D8F603F54DE61E1A268980B803A285669CB7B9FDD086DA3846B82915D60F9"
        "2C86B202199C05A8284FFFCB3C60E75CA184D56FA83470F7F40D847883BBD642"
        "30881F7A3B600F3598ADF01C4690CBA846443FB3E0E68E64C54A447253BBAF"
    ),
    # DiRT Showdown
    bytes.fromhex(
        "B1B1C44319B38A9547C15939755C7E138853B962D9F7F084BAA0397D4CF357"
        "0732956C25C9280BCF2683871E3C6F1F038AA093C72C6762BB55F968938CE355"
        "0BF9750BA299B33A6BB953ECC97B7366CDF190FD0793161B6FCD3F59AF635B"
        "A4C7776D2BCDCA8FD7ED67BA44967A64A49F9FA22A652C8846B1E57F8626173A"
        "91D0BD"
    ),
    # DiRT
    bytes.fromhex(
        "EF84EAE0599170878BC839835CBDF6DBD5C87448CA7951EBC59BBF42EB291C"
        "9A62B58EE4DD9B580CF3D22B84FD8B90CD375B4F9728BD1A26BC722985CE37DE"
        "BD9DC00123F94785FD21FAD3F105F002B76EE626CDF07A7D9DE45125D3A760FF"
        "D1898870A4760FEF9BA6E1429822D1D272591F23A26F9EA61EB38F492A7CE0A5"
    ),
    # Operation Flashpoint: Dragon Rising / Red River
    bytes.fromhex(
        "5DF1C60DC1C0B160802A59D1A4D04DFEE59661338A0F73A0785A99DBF7737CB4"
        "900AEE5A87CE18B29A23940194129B96482B4F80E5DC81D8ED59F9E364E76531"
        "5933DDC487C1B4301ADC1D16CB206116108F07F1CDCDF2DAD6CF35E03D3CE1F0"
        "54FDF0E4EF6A15B90A463DEAF3A4F3C9282C7AC26EF70D9ADDDA3DFD85D2B1D9"
        "D6"
    ),
    # F1 Race Stars
    bytes.fromhex(
        "ADA5F184CDF12B63381B6C9F6DA0A1C4235F706D5954266E8A7C98FD9A8B0C"
        "7785A7BE4EEDA1C5D4A63236D24E58DCC4E88AAE352AB52AFF0A1CA19860BC"
        "BDE8EC0E4DC2FABA2B2A9BA3331FBA23BACF4A6663B7CF28C8FF2B1617D6FFA4"
        "8402C4D73AB47A21302F9A97502408DC0C3C3AEE285910266851F049D509E598"
    ),
    # Toybox Turbos
    bytes.fromhex(
        "65031E110780AF34ACF8A07D20E1E7A6182C54109ACB1D004FF4D88E401D3A"
        "A7C3352A5E55B1EF1D8F2911934141948C4D7C9B4BB589D72523D9A3336E115D"
        "B1C53AFE52A1AF6E56B002F7149A5ED5FB22447169DC59CA9BACA2A81529"
    ),
]

_RSA_EXP = DEFAULT_RSA_EXPONENT


def _swap_endian_blocks16(data: bytes) -> bytes:
    """Swap endianness of each 16-bit block (used in big-endian decode)."""
    out = bytearray(len(data))
    for i in range(0, len(data) - 1, 2):
        out[i] = data[i + 1]
        out[i + 1] = data[i]
    return bytes(out)


def decrypt_header_intro_rsa(encrypted: bytes, modulus: bytes) -> bytes:
    """Unscramble an RSA-encrypted header intro.

    NefsLib reconstructs the public key and the ciphertext as *little-endian*
    big integers (`new BigInteger(bytes, true)`), raises the ciphertext to the
    public exponent (65537), then writes the result as little-endian and pads
    the high end with zero bytes.  Ports that exactly.
    """
    n = int.from_bytes(modulus, "little")
    m = int.from_bytes(encrypted, "little")
    result = pow(m, _RSA_EXP, n)
    # result < n, so it fits in the modulus byte length; pad low positions
    # (little-endian high-order zeros) to INTRO_SIZE.
    length = (n.bit_length() + 7) // 8
    dec = result.to_bytes(max(length, INTRO_SIZE), "little")
    return dec[:INTRO_SIZE]


def _is_plain_or_swapped_magic(dec: bytes) -> bool:
    """True if the first u32 of ``dec`` is FOUR_CC in little or big endian."""
    if len(dec) < 4:
        return False
    le = struct.unpack("<I", dec[:4])[0]
    be = struct.unpack(">I", dec[:4])[0]
    return le == FOUR_CC or be == FOUR_CC


def decode_xor_intro(intro: bytes) -> bytes:
    """Undo the v1.5.1 uint32 XOR obfuscation of the intro."""
    if len(intro) < 124:
        raise ValueError("intro too short for XOR decode")
    # Read as 31 x uint32 little-endian.
    vals = list(struct.unpack("<31I", intro[:124]))
    tail = intro[124:128]

    vals[14] ^= vals[5]
    vals[5] ^= vals[2]
    vals[2] ^= vals[4]
    vals[4] ^= vals[7]
    vals[7] ^= vals[3]
    vals[3] ^= vals[9]
    vals[9] ^= vals[10]
    vals[10] ^= vals[1]
    vals[1] ^= vals[13]
    vals[13] ^= vals[11]
    vals[11] ^= vals[0]
    vals[0] ^= vals[12]
    vals[12] ^= vals[6]
    vals[6] ^= vals[8]
    vals[8] ^= vals[14]

    mod = vals[14]
    for i in range(15, 31):
        vals[i] ^= mod

    out = struct.pack("<31I", *vals)
    if len(out) < INTRO_SIZE:
        out += tail[:(INTRO_SIZE - len(out))]
    return out


def try_rsa_decrypt(encrypted: bytes) -> Optional[bytes]:
    """Try each known RSA modulus until the intro magic is recovered.

    Like NefsLib: try little-endian first for each key, then the 16-bit
    block-swapped (big-endian emulation) variant.
    """
    for key in RSA_KEYS:
        for variant in (encrypted, _swap_endian_blocks16(encrypted)):
            try:
                dec = decrypt_header_intro_rsa(variant, key)
            except Exception:
                continue
            if _is_plain_or_swapped_magic(dec):
                return dec
    return None