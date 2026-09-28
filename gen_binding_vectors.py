#!/usr/bin/env python3
"""Checked-in generator for SCRUM-91 bindingHash test vectors.

Spec: DESIGN.md v11, section 3. All integers big-endian. All hex lowercase.
Run: python3 gen_binding_vectors.py
"""
import hashlib
import struct
import json

def u16be(n):
    assert 0 <= n <= 0xFFFF, n
    return struct.pack('>H', n)

def u64be(n):
    assert 0 <= n <= 2**64 - 1, n
    return struct.pack('>Q', n)

def lpref(b: bytes) -> bytes:
    return u16be(len(b)) + b

def valid_hex(s: str) -> bytes:
    assert isinstance(s, str) and len(s) % 2 == 0, s
    assert all(c in '0123456789abcdef' for c in s), s
    return bytes.fromhex(s)

def opt_bytes(b):
    return b'\x00' if b is None else b'\x01' + b

def domain_digest(domain: bytes, parts) -> bytes:
    h = hashlib.sha256()
    h.update(domain)
    for part in parts:
        h.update(part)
    return h.digest()

def proposal_snapshot_hash(proposals) -> bytes:
    # Canonical serialization of the committee-proposal set affecting fees.
    # Empty set -> digest of domain + zero count (still a commitment).
    parts = [struct.pack('>I', len(proposals))]
    for pr in sorted(proposals, key=lambda x: x['id']):
        parts.append(struct.pack('>Q', pr['id']))
        parts.append(u64be(pr['proposedFeeSun']))
        parts.append(u64be(pr['effectiveTimeMs']))
        parts.append(pr['state'].encode('utf-8'))
    return domain_digest(b'TRONFEEPROPOSALSv1', parts)

def fee_derivation_id(q, proposal_hash: bytes) -> bytes:
    return domain_digest(b'TRONFEEDERIVEv1', [
        u64be(q['quoteBlockHeight']),
        u64be(q['quoteBlockTimestampMs']),
        u64be(q['maintenanceIntervalMs']),
        u64be(q['nextMaintenanceTimeMs']),
        u64be(q['marginMs']),
        u64be(q['currentFeeSun']),
        proposal_hash,
        q['sponsorPolicyVersion'].encode('utf-8'),
    ])

def opt_u64(n):
    return b'\x00' if n is None else b'\x01' + u64be(n)

def build_preimage(q: dict) -> bytes:
    p = b''
    p += lpref(b'TRC20FEEv1')                                   # 1 domain
    for k in ('from', 'to', 'contract'):                       # 2-4 addresses
        raw = valid_hex(q[k])
        assert len(raw) == 21, k
        p += lpref(raw)
    p += lpref(q['amountRaw'].encode('utf-8'))                  # 5 amountRaw
    for k in ('conservativeEnergyUnits', 'worstCaseEnergyUnits',
              'maxFactorBps'):                                  # 6-8
        p += u64be(q[k])
    p += lpref(q['boundSource'].encode('utf-8'))                # 9 boundSource
    for k in ('energyFeeSun', 'transactionFeeSun', 'energyFeeLimitSun',
              'bandwidthReservationSun', 'maxTotalDebitSun',
              'byteAllowance'):                                # 10-15
        p += u64be(q[k])
    assert 0 <= q['callerSharePercent'] <= 100
    p += u16be(q['callerSharePercent'])                         # 16
    p += lpref(q['txShape'].encode('utf-8'))                    # 17 txShape
    p += opt_u64(q['policyFeeCents'])                           # 18
    p += u64be(q['quotedAtMs'])                                 # 19
    p += u64be(q['maxAgeMs'])                                   # 20
    p += opt_bytes(valid_hex(q['refBlockHash']) if q['refBlockHash'] else None)  # 21
    assert q['refBlockHash'] is None or len(valid_hex(q['refBlockHash'])) == 8
    p += opt_bytes(valid_hex(q['refBlockBytes']) if q['refBlockBytes'] else None)  # 22
    assert q['refBlockBytes'] is None or len(valid_hex(q['refBlockBytes'])) == 2
    p += opt_u64(q['txExpirationMs'])                           # 23
    p += opt_u64(q['txTimestampMs'])                            # 24
    p += lpref(b'nile')                                         # 25 chainId
    p += opt_bytes(lpref(q['unsignedRawDataHex'].encode('utf-8'))
                   if q['unsignedRawDataHex'] else None)        # 26
    if q['unsignedRawDataHex']:
        valid_hex(q['unsignedRawDataHex'])  # validates lowercase hex
    p += u64be(q['simulationBlockHeight'])                      # 27
    sim_hash = valid_hex(q['simulationBlockHash'])
    assert len(sim_hash) == 32
    p += lpref(sim_hash)                                       # 28
    p += u64be(q['quotedSuccessCostSun'])                       # 29 (v7)
    p += u64be(q['policyFeeSun'])                               # 30 (v7)
    p += lpref(q['fxId'].encode('utf-8'))                       # 31 (v7)
    p += u64be(q['fxSunPerCent'])                               # 32 (v7)
    p += lpref(q['sponsorPolicyVersion'].encode('utf-8'))       # 33 (v7)
    p += u64be(q['transactionFeeUpperBoundSun'])                # 34 (v10/v11)
    p += u64be(q['pricingHorizonMs'])                          # 35 (v11: ms timestamp)
    # --- v11: semantic derivation, recomputed (not a literal) ---
    assert q['maintenanceIntervalMs'] > 0
    assert q['marginMs'] > 0
    assert q['nextMaintenanceTimeMs'] == (
        (q['quoteBlockTimestampMs'] // q['maintenanceIntervalMs']) + 1
    ) * q['maintenanceIntervalMs'], 'not the next maintenance boundary'
    assert q['pricingHorizonMs'] == q['nextMaintenanceTimeMs'] - q['marginMs']
    if q['txExpirationMs'] is not None:
        assert q['txExpirationMs'] < q['pricingHorizonMs'], \
            'expiration must be strictly before the pricing horizon'
    prop_hash = proposal_snapshot_hash(q['proposals'])
    deriv_id = fee_derivation_id(q, prop_hash)
    for pr in q['proposals']:
        assert pr['effectiveTimeMs'] >= q['nextMaintenanceTimeMs'], \
            'protocol rule: proposals activate only at maintenance boundaries'
    assert q['transactionFeeUpperBoundSun'] == q['currentFeeSun'], \
        'no proposal can activate before the horizon: bound == current fee'
    p += lpref(deriv_id)                                       # 36 (v11: digest)
    p += u64be(q['quoteBlockHeight'])                          # 37 (v11)
    p += u64be(q['quoteBlockTimestampMs'])                      # 38 (v11)
    p += u64be(q['maintenanceIntervalMs'])                      # 39 (v11)
    p += u64be(q['nextMaintenanceTimeMs'])                      # 40 (v11)
    p += u64be(q['marginMs'])                                   # 41 (v11)
    p += u64be(q['currentFeeSun'])                               # 42 (v11)
    p += lpref(prop_hash)                                       # 43 (v11)
    return p

# Vector 1: complete quote (all fields present)
V1 = {
    'from': '41' * 21, 'to': '42' * 21, 'contract': '43' * 21,
    'amountRaw': '1000000',
    'conservativeEnergyUnits': 21527, 'worstCaseEnergyUnits': 94719,
    'maxFactorBps': 34000, 'boundSource': 'chain',
    'energyFeeSun': 100, 'transactionFeeSun': 1000,
    'energyFeeLimitSun': 9471900, 'bandwidthReservationSun': 350000,
    'maxTotalDebitSun': 9821900, 'byteAllowance': 350,
    'callerSharePercent': 100, 'txShape': 'trc20-transfer-single-sig',
    'policyFeeCents': 10,
    'quotedAtMs': 1759000000000, 'maxAgeMs': 120000,
    'refBlockHash': 'ab' * 8, 'refBlockBytes': 'cd' * 2,
    'txExpirationMs': 1759000120000, 'txTimestampMs': 1759000000000,
    'unsignedRawDataHex': 'deadbeef',
    'simulationBlockHeight': 12345678,
    'simulationBlockHash': 'ef' * 32,
    'quotedSuccessCostSun': 9921900, 'policyFeeSun': 100000,
    'fxId': 'test-fx-v1', 'fxSunPerCent': 10000,
    'sponsorPolicyVersion': 'sp-1',
    'transactionFeeUpperBoundSun': 1000, 'pricingHorizonMs': 1759017540000,
    'quoteBlockHeight': 12345678, 'quoteBlockTimestampMs': 1759000000000,
    'maintenanceIntervalMs': 21600000, 'nextMaintenanceTimeMs': 1759017600000,
    'marginMs': 60000, 'currentFeeSun': 1000, 'proposals': [],
}

# Vector 2: display-only quote (blockBound=false -> nulls)
V2 = {
    'from': '41' * 21, 'to': '42' * 21, 'contract': '43' * 21,
    'amountRaw': '0',
    'conservativeEnergyUnits': 14351, 'worstCaseEnergyUnits': 63145,
    'maxFactorBps': 34000, 'boundSource': 'chain',
    'energyFeeSun': 100, 'transactionFeeSun': 1000,
    'energyFeeLimitSun': 6314500, 'bandwidthReservationSun': 350000,
    'maxTotalDebitSun': 6664500, 'byteAllowance': 350,
    'callerSharePercent': 100, 'txShape': 'trc20-transfer-single-sig',
    'policyFeeCents': None,
    'quotedAtMs': 1759000000000, 'maxAgeMs': 120000,
    'refBlockHash': None, 'refBlockBytes': None,
    'txExpirationMs': None, 'txTimestampMs': None,
    'unsignedRawDataHex': None,
    'simulationBlockHeight': 12345670,
    'simulationBlockHash': '12' * 32,
    'quotedSuccessCostSun': 6664500, 'policyFeeSun': 0,
    'fxId': 'test-fx-v1', 'fxSunPerCent': 10000,
    'sponsorPolicyVersion': 'sp-1',
    'transactionFeeUpperBoundSun': 1000, 'pricingHorizonMs': 1759017540000,
    'quoteBlockHeight': 12345670, 'quoteBlockTimestampMs': 1759000000000,
    'maintenanceIntervalMs': 21600000, 'nextMaintenanceTimeMs': 1759017600000,
    'marginMs': 60000, 'currentFeeSun': 1000, 'proposals': [],
}

if __name__ == '__main__':
    # Expected values (assertions: the generator is self-verifying; run in CI)
    EXPECTED = {
        'V1': {
            'preimage_len': 486,
            'sha256': '2206c076e53f4458498582ef996cc67b5535698a0efa48351b02b83aeec48734',
            'preimage_hex': '000a54524332304645457631001541414141414141414141414141414141414141414100154242424242424242424242424242424242424242420015434343434343434343434343434343434343434343000731303030303030000000000000541700000000000171ff00000000000084d00005636861696e000000000000006400000000000003e8000000000090879c0000000000055730000000000095decc000000000000015e0064001974726332302d7472616e736665722d73696e676c652d73696701000000000000000a000001998c91f600000000000001d4c001abababababababab01cdcd01000001998c93cac001000001998c91f60000046e696c6501000864656164626565660000000000bc614e0020efefefefefefefefefefefefefefefefefefefefefefefefefefefefefefefef000000000097656c00000000000186a0000a746573742d66782d76310000000000002710000473702d3100000000000003e8000001998d9d99a00020c654baa36aa6fcc299a647eeeeb06886af91888da0ffdf9e9fba071c6e87469d0000000000bc614e000001998c91f6000000000001499700000001998d9e8400000000000000ea6000000000000003e80020ce252b0dddf9a6af84daa326f38185288d5cf0b397a891bb6f40362910f7ae59',
        },
        'V2': {
            'preimage_len': 436,
            'sha256': 'dd59a1a0bc590edb0f6aa831ee9ee26aec53587aef5a84bed803dbba2c008687',
            'preimage_hex': '000a54524332304645457631001541414141414141414141414141414141414141414100154242424242424242424242424242424242424242420015434343434343434343434343434343434343434343000130000000000000380f000000000000f6a900000000000084d00005636861696e000000000000006400000000000003e80000000000605a040000000000055730000000000065b134000000000000015e0064001974726332302d7472616e736665722d73696e676c652d73696700000001998c91f600000000000001d4c00000000000046e696c65000000000000bc614600201212121212121212121212121212121212121212121212121212121212121212000000000065b1340000000000000000000a746573742d66782d76310000000000002710000473702d3100000000000003e8000001998d9d99a000201d5194eac64f13a45a6a885158cfb129bbf9280fc83b9f6faf7c9568a57fb0950000000000bc6146000001998c91f6000000000001499700000001998d9e8400000000000000ea6000000000000003e80020ce252b0dddf9a6af84daa326f38185288d5cf0b397a891bb6f40362910f7ae59',
        },
    }
    out = {}
    for name, fix in (('V1', V1), ('V2', V2)):
        pre = build_preimage(fix)
        digest = hashlib.sha256(pre).hexdigest()
        assert len(pre) == EXPECTED[name]['preimage_len'], (name, len(pre))
        assert digest == EXPECTED[name]['sha256'], (name, digest)
        assert pre.hex() == EXPECTED[name]['preimage_hex'], (name, 'hex mismatch')
        out[name] = {
            'preimage_len': len(pre),
            'preimage_hex': pre.hex(),
            'sha256': digest,
        }
        print(f'--- {name} ---')
        print('preimage_len:', len(pre))
        print('preimage_hex:', pre.hex())
        print('sha256:', digest)
        print()
    with open('binding_vectors.json', 'w') as f:
        json.dump(out, f, indent=2)
    print('wrote binding_vectors.json')
    print('assertions passed: lengths, digests and preimage hex match pinned literals')
