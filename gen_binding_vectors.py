#!/usr/bin/env python3
"""Checked-in generator for SCRUM-91 bindingHash test vectors.

Spec: DESIGN.md v12, section 3. All integers big-endian. All hex lowercase.
Run: python3 gen_binding_vectors.py

v12 changes vs v11 (Codex review findings):
- P1-1: nextMaintenanceTimeMs is an AUTHORITATIVE chain input read from
  DynamicPropertiesStore.NEXT_MAINTENANCE_TIME at the solidified height H_q
  (cross-checked across >=2 full-node RPC endpoints). The v11 epoch-rounding
  formula ((T_q // interval) + 1) * interval is REMOVED: java-tron advances
  nextMaintenanceTime from the previous boundary, so the phase is anchored
  to history, not to the Unix epoch (and MAINTENANCE_TIME_INTERVAL itself
  can change by governance). The generator asserts the checkable protocol
  invariant T_q < nextMaintenanceTimeMs <= T_q + maintenanceIntervalMs.
- P1-1: the provenance of nextMaintenanceTimeMs is bound into the design
  as field 44 (nextMaintenanceTimeSource, length-prefixed UTF-8) and into
  feeDerivationId (domain bumped to TRONFEEDERIVEv2).
- P2: proposalSnapshotHash uses a strict typed canonical encoding
  (domain TRONFEEPROPOSALSv2): u32be count, then per proposal sorted by id:
  u64be proposalId, u64be paramId, u64be paramValue, u64be effectiveTimeMs,
  u8 stateId (numeric enum pinned to java-tron ProposalCapsule.State).
  Rejects duplicate ids, unknown states, foreign (non-fee) params, and
  effective times that are not future maintenance boundaries.
- feeDerivationId inputs are all length-delimited (incl. sponsorPolicyVersion).
- V3: new vector with a historical MAINTENANCE_TIME_INTERVAL change
  (6h -> 3h) where epoch-rounding gives the WRONG boundary.
- Real mutation tests + negative cases run as part of this script.
"""
import hashlib
import struct
import json

# --- java-tron pins (must match the pinned java-tron commit in CI) ---
# ProposalCapsule.State order: PENDING=0, DISAPPROVED=1, APPROVED=2, CANCELED=3
PROPOSAL_STATE_IDS = {'PENDING': 0, 'DISAPPROVED': 1, 'APPROVED': 2, 'CANCELED': 3}
# Committee parameter ids affecting the fee bound (ProposalService):
# 3 = TRANSACTION_FEE, 11 = ENERGY_FEE
FEE_PARAM_IDS = {3: 'TRANSACTION_FEE', 11: 'ENERGY_FEE'}


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


def proposal_snapshot_hash(proposals, next_maintenance_ms, interval_ms) -> bytes:
    """Strict canonical serialization of the fee-relevant proposal set.

    Every proposal dict: {id, paramId, paramValue, effectiveTimeMs, state}.
    Rejects: duplicate ids, unknown states, non-fee params, effective times
    that are not real future maintenance boundaries.
    """
    seen = set()
    for pr in proposals:
        pid = pr['id']
        if pid in seen:
            raise ValueError(f'duplicate proposal id: {pid}')
        seen.add(pid)
        if pr['state'] not in PROPOSAL_STATE_IDS:
            raise ValueError(f"unknown proposal state: {pr['state']}")
        if pr['paramId'] not in FEE_PARAM_IDS:
            raise ValueError(f"foreign (non-fee) param id: {pr['paramId']}")
        eff = pr['effectiveTimeMs']
        if eff < next_maintenance_ms:
            raise ValueError('proposal effective time before next maintenance')
        if (eff - next_maintenance_ms) % interval_ms != 0:
            raise ValueError('proposal effective time is not a maintenance boundary')
    parts = [struct.pack('>I', len(proposals))]
    for pr in sorted(proposals, key=lambda x: x['id']):
        parts.append(u64be(pr['id']))
        parts.append(u64be(pr['paramId']))
        parts.append(u64be(pr['paramValue']))
        parts.append(u64be(pr['effectiveTimeMs']))
        parts.append(struct.pack('B', PROPOSAL_STATE_IDS[pr['state']]))
    return domain_digest(b'TRONFEEPROPOSALSv2', parts)


def fee_derivation_id(q, proposal_hash: bytes) -> bytes:
    return domain_digest(b'TRONFEEDERIVEv2', [
        u64be(q['quoteBlockHeight']),
        u64be(q['quoteBlockTimestampMs']),
        u64be(q['maintenanceIntervalMs']),
        u64be(q['nextMaintenanceTimeMs']),
        lpref(q['nextMaintenanceTimeSource'].encode('utf-8')),
        u64be(q['marginMs']),
        u64be(q['currentFeeSun']),
        proposal_hash,
        lpref(q['sponsorPolicyVersion'].encode('utf-8')),
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
    p += opt_u64(q['txTimestampMs'])                           # 24
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
    # --- v12: authoritative maintenance boundary (P1-1). The value is a
    # quoted chain input (DynamicPropertiesStore.NEXT_MAINTENANCE_TIME at
    # solidified H_q, cross-checked); the generator asserts the checkable
    # protocol invariant instead of deriving it by epoch rounding. ---
    assert q['maintenanceIntervalMs'] > 0
    assert q['marginMs'] > 0
    assert q['nextMaintenanceTimeMs'] > q['quoteBlockTimestampMs'], \
        'next maintenance must be strictly after the quote timestamp'
    assert q['nextMaintenanceTimeMs'] <= \
        q['quoteBlockTimestampMs'] + q['maintenanceIntervalMs'], \
        'next maintenance must be within one interval after the quote'
    assert q['pricingHorizonMs'] == q['nextMaintenanceTimeMs'] - q['marginMs']
    if q['txExpirationMs'] is not None:
        assert q['txExpirationMs'] < q['pricingHorizonMs'], \
            'expiration must be strictly before the pricing horizon'
    prop_hash = proposal_snapshot_hash(q['proposals'],
                                       q['nextMaintenanceTimeMs'],
                                       q['maintenanceIntervalMs'])
    deriv_id = fee_derivation_id(q, prop_hash)
    assert q['transactionFeeUpperBoundSun'] == q['currentFeeSun'], \
        'no proposal can activate before the horizon: bound == current fee'
    p += lpref(deriv_id)                                       # 36 (v12: TRONFEEDERIVEv2)
    p += u64be(q['quoteBlockHeight'])                          # 37 (v11)
    p += u64be(q['quoteBlockTimestampMs'])                      # 38 (v11)
    p += u64be(q['maintenanceIntervalMs'])                      # 39 (v11)
    p += u64be(q['nextMaintenanceTimeMs'])                      # 40 (v11, authoritative)
    p += u64be(q['marginMs'])                                   # 41 (v11)
    p += u64be(q['currentFeeSun'])                               # 42 (v11)
    p += lpref(prop_hash)                                       # 43 (v11, TRONFEEPROPOSALSv2)
    p += lpref(q['nextMaintenanceTimeSource'].encode('utf-8'))  # 44 (v12: provenance)
    return p


def _quote_base():
    return {
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
    }


# Vector 1: complete quote (all fields present). nextMaintenanceTimeMs is the
# authoritative chain value at H_q (treated as input, not derived).
V1 = _quote_base()
V1.update({
    'transactionFeeUpperBoundSun': 1000, 'pricingHorizonMs': 1759017540000,
    'quoteBlockHeight': 12345678, 'quoteBlockTimestampMs': 1759000000000,
    'maintenanceIntervalMs': 21600000, 'nextMaintenanceTimeMs': 1759017600000,
    'nextMaintenanceTimeSource': 'chain:getchainparameters@H=12345678+crosscheck:2of2',
    'marginMs': 60000, 'currentFeeSun': 1000, 'proposals': [],
})

# Vector 2: display-only quote (blockBound=false -> nulls)
V2 = _quote_base()
V2.update({
    'amountRaw': '0',
    'conservativeEnergyUnits': 14351, 'worstCaseEnergyUnits': 63145,
    'energyFeeLimitSun': 6314500,
    'maxTotalDebitSun': 6664500,
    'policyFeeCents': None,
    'refBlockHash': None, 'refBlockBytes': None,
    'txExpirationMs': None, 'txTimestampMs': None,
    'unsignedRawDataHex': None,
    'simulationBlockHeight': 12345670,
    'simulationBlockHash': '12' * 32,
    'quotedSuccessCostSun': 6664500, 'policyFeeSun': 0,
    'transactionFeeUpperBoundSun': 1000, 'pricingHorizonMs': 1759017540000,
    'quoteBlockHeight': 12345670, 'quoteBlockTimestampMs': 1759000000000,
    'maintenanceIntervalMs': 21600000, 'nextMaintenanceTimeMs': 1759017600000,
    'nextMaintenanceTimeSource': 'chain:getchainparameters@H=12345670+crosscheck:2of2',
    'marginMs': 60000, 'currentFeeSun': 1000, 'proposals': [],
})

# Vector 3: historical MAINTENANCE_TIME_INTERVAL change (6h -> 3h).
# The chain's maintenance phase is anchored to history (java-tron advances
# nextMaintenanceTime from the previous boundary), NOT to the Unix epoch.
# T_q = 1759000000000, current interval = 10800000 (3h).
# v11's epoch formula would compute ((T_q // 10800000) + 1) * 10800000
#   = 1759006800000  <-- WRONG.
# The authoritative chain value is 1759000800000 (last 6h-regime boundary
# 1758990000000 advanced by 3h steps). v12 uses the authoritative value.
V3 = _quote_base()
V3.update({
    'transactionFeeUpperBoundSun': 1000, 'pricingHorizonMs': 1759000740000,
    'quoteBlockHeight': 12345679, 'quoteBlockTimestampMs': 1759000000000,
    'maintenanceIntervalMs': 10800000, 'nextMaintenanceTimeMs': 1759000800000,
    'nextMaintenanceTimeSource': 'chain:getchainparameters@H=12345679+crosscheck:2of2',
    'marginMs': 60000, 'currentFeeSun': 1000,
    'simulationBlockHeight': 12345679,
    'proposals': [
        {'id': 7, 'paramId': 3, 'paramValue': 2000,
         'effectiveTimeMs': 1759000800000, 'state': 'APPROVED'},
    ],
})


def _mut(base, **kw):
    c = dict(base)
    c.update(kw)
    return c


def run_mutation_tests():
    """Real mutation tests: every bound input changes feeDerivationId;
    every invalid input is rejected."""
    base = V1
    base_ph = proposal_snapshot_hash(base['proposals'],
                                     base['nextMaintenanceTimeMs'],
                                     base['maintenanceIntervalMs'])
    base_id = fee_derivation_id(base, base_ph)
    assert len(base_id) == 32
    n_mut = 0

    def expect_change(label, q):
        nonlocal n_mut
        ph = proposal_snapshot_hash(q['proposals'],
                                    q['nextMaintenanceTimeMs'],
                                    q['maintenanceIntervalMs'])
        nid = fee_derivation_id(q, ph)
        assert nid != base_id, f'mutation did not change feeDerivationId: {label}'
        n_mut += 1

    expect_change('quoteBlockHeight', _mut(base, quoteBlockHeight=12345679))
    expect_change('quoteBlockTimestampMs', _mut(base, quoteBlockTimestampMs=1759000000001))
    expect_change('maintenanceIntervalMs', _mut(base, maintenanceIntervalMs=10800000))
    expect_change('nextMaintenanceTimeMs',
                  _mut(base, nextMaintenanceTimeMs=1759017600001,
                       pricingHorizonMs=1759017540001))
    expect_change('nextMaintenanceTimeSource',
                  _mut(base, nextMaintenanceTimeSource='chain:getchainparameters@H=12345679+crosscheck:2of2'))
    expect_change('marginMs', _mut(base, marginMs=60001,
                                   pricingHorizonMs=1759017539999))
    expect_change('currentFeeSun', _mut(base, currentFeeSun=1001))
    expect_change('sponsorPolicyVersion', _mut(base, sponsorPolicyVersion='sp-2'))
    expect_change('proposal added', _mut(base, proposals=[
        {'id': 7, 'paramId': 3, 'paramValue': 2000,
         'effectiveTimeMs': 1759017600000, 'state': 'PENDING'}]))
    expect_change('proposal value', _mut(base, proposals=[
        {'id': 7, 'paramId': 11, 'paramValue': 101,
         'effectiveTimeMs': 1759017600000, 'state': 'PENDING'}]))

    n_neg = 0

    def expect_reject(label, fn):
        nonlocal n_neg
        try:
            fn()
        except (ValueError, AssertionError):
            n_neg += 1
            return
        raise AssertionError(f'negative case NOT rejected: {label}')

    dup = {'id': 7, 'paramId': 3, 'paramValue': 2000,
           'effectiveTimeMs': 1759017600000, 'state': 'PENDING'}
    nm, iv = base['nextMaintenanceTimeMs'], base['maintenanceIntervalMs']
    expect_reject('duplicate proposal id',
                  lambda: proposal_snapshot_hash([dup, dict(dup)], nm, iv))
    bad_state = dict(dup, state='BOGUS')
    expect_reject('unknown proposal state',
                  lambda: proposal_snapshot_hash([bad_state], nm, iv))
    foreign = dict(dup, paramId=99)
    expect_reject('foreign (non-fee) param',
                  lambda: proposal_snapshot_hash([foreign], nm, iv))
    early = dict(dup, effectiveTimeMs=nm - 1)
    expect_reject('effective time before next maintenance',
                  lambda: proposal_snapshot_hash([early], nm, iv))
    offgrid = dict(dup, effectiveTimeMs=nm + 1)
    expect_reject('effective time not on boundary grid',
                  lambda: proposal_snapshot_hash([offgrid], nm, iv))
    expect_reject('expiration == horizon (equality rejected)',
                  lambda: build_preimage(_mut(base, txExpirationMs=base['pricingHorizonMs'])))
    expect_reject('expiration > horizon',
                  lambda: build_preimage(_mut(base, txExpirationMs=base['pricingHorizonMs'] + 1)))
    expect_reject('nextMaintenance <= T_q',
                  lambda: build_preimage(_mut(base,
                                             nextMaintenanceTimeMs=base['quoteBlockTimestampMs'],
                                             pricingHorizonMs=base['quoteBlockTimestampMs'] - base['marginMs'])))
    expect_reject('nextMaintenance > T_q + interval',
                  lambda: build_preimage(_mut(base,
                                             nextMaintenanceTimeMs=base['quoteBlockTimestampMs'] + iv + 1,
                                             pricingHorizonMs=base['quoteBlockTimestampMs'] + iv + 1 - base['marginMs'])))
    expect_reject('bound != current fee',
                  lambda: build_preimage(_mut(base, transactionFeeUpperBoundSun=2000)))
    print(f'mutation tests passed: {n_mut} field-mutations change '
          f'feeDerivationId, {n_neg} negative cases rejected')


if __name__ == '__main__':
    import sys
    # Phase 1: compute vectors (no pinned literals yet on first authoring run)
    computed = {}
    for name, fix in (('V1', V1), ('V2', V2), ('V3', V3)):
        pre = build_preimage(fix)
        digest = hashlib.sha256(pre).hexdigest()
        computed[name] = {'preimage_len': len(pre),
                          'preimage_hex': pre.hex(), 'sha256': digest}
    if '--print-only' in sys.argv:
        for name in ('V1', 'V2', 'V3'):
            c = computed[name]
            print(f'--- {name} ---')
            print('preimage_len:', c['preimage_len'])
            print('preimage_hex:', c['preimage_hex'])
            print('sha256:', c['sha256'])
            print()
        sys.exit(0)
    # Phase 2: self-verification against pinned literals
    EXPECTED = {
        'V1': {
            'preimage_len': 539,
            'sha256': 'b144e411fb336f639c7ea2ae3fccf8a3f3818325a9c6f96231aa509546b619a1',
            'preimage_hex': '000a54524332304645457631001541414141414141414141414141414141414141414100154242424242424242424242424242424242424242420015434343434343434343434343434343434343434343000731303030303030000000000000541700000000000171ff00000000000084d00005636861696e000000000000006400000000000003e8000000000090879c0000000000055730000000000095decc000000000000015e0064001974726332302d7472616e736665722d73696e676c652d73696701000000000000000a000001998c91f600000000000001d4c001abababababababab01cdcd01000001998c93cac001000001998c91f60000046e696c6501000864656164626565660000000000bc614e0020efefefefefefefefefefefefefefefefefefefefefefefefefefefefefefefef000000000097656c00000000000186a0000a746573742d66782d76310000000000002710000473702d3100000000000003e8000001998d9d99a000203843697db0d4fec6299b238bd627c137182257678e92fc017b9dee27945f082c0000000000bc614e000001998c91f6000000000001499700000001998d9e8400000000000000ea6000000000000003e800205d224dc1e8ad65deda08ea1c54ff33efa768d40a62579306cf2fc5cd31aa1ff70033636861696e3a676574636861696e706172616d657465727340483d31323334353637382b63726f7373636865636b3a326f6632',
        },
        'V2': {
            'preimage_len': 489,
            'sha256': 'ac9b84e8afe6538e50e1a54e97fac53748a0f2782f4e1ed213ad74d699483efd',
            'preimage_hex': '000a54524332304645457631001541414141414141414141414141414141414141414100154242424242424242424242424242424242424242420015434343434343434343434343434343434343434343000130000000000000380f000000000000f6a900000000000084d00005636861696e000000000000006400000000000003e80000000000605a040000000000055730000000000065b134000000000000015e0064001974726332302d7472616e736665722d73696e676c652d73696700000001998c91f600000000000001d4c00000000000046e696c65000000000000bc614600201212121212121212121212121212121212121212121212121212121212121212000000000065b1340000000000000000000a746573742d66782d76310000000000002710000473702d3100000000000003e8000001998d9d99a000205c1e3a4c47e7bbd0e66387aaa760f7e6fe40ca3ba4e60f0594a94895669402d90000000000bc6146000001998c91f6000000000001499700000001998d9e8400000000000000ea6000000000000003e800205d224dc1e8ad65deda08ea1c54ff33efa768d40a62579306cf2fc5cd31aa1ff70033636861696e3a676574636861696e706172616d657465727340483d31323334353637302b63726f7373636865636b3a326f6632',
        },
        'V3': {
            'preimage_len': 539,
            'sha256': '2228960959afac973daa051df21997280b5ebaa0f462b92a2aea8674e5979f48',
            'preimage_hex': '000a54524332304645457631001541414141414141414141414141414141414141414100154242424242424242424242424242424242424242420015434343434343434343434343434343434343434343000731303030303030000000000000541700000000000171ff00000000000084d00005636861696e000000000000006400000000000003e8000000000090879c0000000000055730000000000095decc000000000000015e0064001974726332302d7472616e736665722d73696e676c652d73696701000000000000000a000001998c91f600000000000001d4c001abababababababab01cdcd01000001998c93cac001000001998c91f60000046e696c6501000864656164626565660000000000bc614f0020efefefefefefefefefefefefefefefefefefefefefefefefefefefefefefefef000000000097656c00000000000186a0000a746573742d66782d76310000000000002710000473702d3100000000000003e8000001998c9d40a0002039670076ead2df7c1b63162c63bdc4c27329b197779abccd6a6547420b51053b0000000000bc614f000001998c91f6000000000000a4cb80000001998c9e2b00000000000000ea6000000000000003e800207e22a88385f9830edb0489b1a3836cead05359fdf718048b7b995cc9a5e909320033636861696e3a676574636861696e706172616d657465727340483d31323334353637392b63726f7373636865636b3a326f6632',
        },
    }
    out = {}
    for name, fix in (('V1', V1), ('V2', V2), ('V3', V3)):
        pre = build_preimage(fix)
        digest = hashlib.sha256(pre).hexdigest()
        assert len(pre) == EXPECTED[name]['preimage_len'], (name, len(pre))
        assert digest == EXPECTED[name]['sha256'], (name, digest)
        assert pre.hex() == EXPECTED[name]['preimage_hex'], (name, 'hex mismatch')
        out[name] = {'preimage_len': len(pre),
                     'preimage_hex': pre.hex(), 'sha256': digest}
        print(f'--- {name} ---')
        print('preimage_len:', len(pre))
        print('sha256:', digest)
        print()
    with open('binding_vectors.json', 'w') as f:
        json.dump(out, f, indent=2)
    print('wrote binding_vectors.json')
    run_mutation_tests()
    print('assertions passed: lengths, digests and preimage hex match pinned literals')
