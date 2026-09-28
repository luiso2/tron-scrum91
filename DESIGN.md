# SCRUM-91 — Diseño v11: motor de estimación de energía y fees TRC-20 (solo lectura)

- **Estado:** BORRADOR v11 — pendiente de revisión por Codex. NO escribir código antes del `APPROVE`.
- **Fecha:** 2026-09-28. **Ticket:** [SCRUM-91](https://merktop.atlassian.net/browse/SCRUM-91)
  (padre SCRUM-87).
- **Historial:** v1 → REJECT (3 P0, 7 P1, 3 P2). v2 → REJECT (1 P0, 9 P1, 2 P2).
  v3 → REJECT (1 P0, 7 P1, 3 P2). v4 → REJECT (0 P0, 5 P1, 1 P2).
  v5 → REJECT (0 P0, 5 P1, 2 P2). v6 → REJECT (0 P0, 5 P1, 2 P2).
  v7 → REJECT (0 P0, 7 P1, 1 P2). v8 → REJECT (0 P0, 4 P1, 0 P2).
  v9 → REJECT (0 P0, 1 P1, 0 P2). v10 → REJECT (0 P0, 3 P1, 1 P2).
  Esta v11 corrige los 3 hallazgos de la décima revisión. Trazabilidad: §9
  (v2→v4), §10 (v4→v5), §11 (v5→v6), §12 (v6→v7), §13 (v7→v8), §14 (v8→v9),
  §15 (v9→v10), §16 (v10→v11).
- **Nota de honestidad (v10):** la respuesta no mostró insignia de modelo;
  el selector/composer web no expone el nombre del modelo en la UI actual.
  El revisor cerró el P1 de v9 y dejó 3 P1 nuevos, todos sobre la cota de
  precio, con la pista clave: los cambios de gobernanza solo toman efecto
  en boundaries de períodos de mantenimiento.

## 0. Base heredada (cerrado, sin cambios)

- **P0 cerrado desde v4:** `getDynamicEnergyMaxFactor = 34000` leído del nodo
  de Nile en cada quote (`boundSource: "chain"`); sin la clave → fail-closed.
  Cota: `base × 4.4`.
- Todo lo de v7 se **refina** abajo, no se revierte: techo al estado
  simulado; quotes single-snapshot; `authorizationRecord` en SUN con `fx`
  ligada; ledger diario con reserva atómica; schema protobuf normativo con
  field numbers y decodificación ABI independiente; preimagen de 33 campos
  con vectores reproducibles; `E` post-stake; `maxNestingDepth`.
- Garantías intactas: Nile-only, verificación de génesis, `TRON_ENABLED`,
  solo-RPC-existente, sin firma ni broadcast.

## 1. Correcciones P1 (7)

### P1-1 (v7): la conversión FX era dimensionalmente incorrecta
**Hallazgo:** `fxSunPerCent` está definido como SUN por centavo, así que
`policyFeeCents × fxSunPerCent / 100` sub-autoriza por un factor de 100
(ej.: 100 centavos × 33,333 SUN/centavo daba 33,333 SUN en vez de
3,333,300 SUN). **El bug era mío.**

**Resolución:**

- `policyFeeSun = policyFeeCents × fxSunPerCent` — multiplicación directa,
  sin división (la tasa ya es SUN/centavo entero; normalmente no hace falta
  redondeo). Anchos enteros: u64 en ambos operandos, producto en u128 con
  rechazo si excede u64 (`tron_amount_overflow`).
- Se rechazan entradas negativas o fuera de rango en `policyFeeCents` y
  `fxSunPerCent`.
- **Vectores de prueba dimensionales** (en §6): `(100, 33333) → 3333300`;
  `(1, 1) → 1`; `(0, x) → 0`; `(maxU64, 2)` → `tron_amount_overflow`.
- Fixture V1 actualizado a la fórmula correcta: `10 × 10000 = 100000`
  (`policyFeeSun`), `quotedSuccessCostSun = 9471900 + 350000 + 100000 =
  9921900`; vectores regenerados (§3).

### P1-2 (v7): un intento y su reserva quedan ligados a una única transacción firmada
**Hallazgo:** un *replacement* tiene distinto `raw_data` (distinto txID);
el original y el reemplazo pueden aceptarse ambos y consumir recursos, así
que una reserva de "pérdida máxima" podía cubrir múltiples pérdidas reales.

**Resolución — máquina de estados durable con compare-and-swap:**

- Estados: `AUTHORIZED → RESERVED → SUBMITTING → {BROADCAST |
  INDETERMINATE} → TERMINAL{CONFIRMED, FAILED, EXPIRED}`.
  `SUBMITTING → BROADCAST` cuando el envío es aceptado (txID conocido,
  resultado aún desconocido); `SUBMITTING → INDETERMINATE` cuando el
  resultado del envío es desconocido (timeout RPC); `INDETERMINATE →
  BROADCAST` cuando se confirma el envío; `BROADCAST → TERMINAL` ante
  resultado autoritativo o predicado `EXPIRED` (§1 P1-4). Toda transición
  por CAS durable; ningún worker puede mover un intento sin ganar el CAS.
- **El intento y su reserva quedan ligados inmutablemente a exactamente una
  transacción firmada / un txID.** Reintentos permitidos **solo** con bytes
  firmados idénticos al byte (mismo txID).
- Un *replacement* (bytes distintos) tiene dos caminos, a elegir por
  política del servidor (versionada): (a) obtener su **propia** reserva
  mientras la transacción anterior sigue `outstanding`; o (b) **prohibido**
  hasta que la reconciliación autoritativa pruebe que la transacción
  anterior no puede ejecutarse. Sin tercer camino.
- La "idempotencia RPC" no sustituye al CAS: es solo transporte.

### P1-3 (v7): la reserva es una cota superior probada, derivada normativamente
**Hallazgo:** `maxFailedAttemptLossSun` se nombraba pero no se derivaba
como cota; variaciones del envelope (firmas adicionales) alteran el tamaño
serializado; ajustar la reserva al alza tras la confirmación no protege el
tope bajo concurrencia.

**Resolución — derivación normativa (v9: incluye overhead de resultado y
horizonte de precios):**

- `maxBillableBandwidthBytes = maxAcceptedSignedSizeBytes + 64` — los 64
  bytes de result allowance que la documentación de Tron suma a la
  transacción firmada serializada con `ret` limpiado; exigir `ret` ausente
  en el envelope no elimina ese cargo.
- `bandwidthBurnBoundSun = maxBillableBandwidthBytes ×
  transactionFeeUpperBoundSun` — se usa la **cota superior** del precio de
  bandwidth, no el snapshot cotizado (ver horizonte de precios abajo).
- `maxFailedAttemptLossSun = energyFeeLimitSun + bandwidthBurnBoundSun`;
  `reservationSun ≥ maxFailedAttemptLossSun`.
- Con los parámetros medidos: 272 bytes firmados → 336 facturables →
  336,000 SUN; 350 bytes → 414 facturables → 414,000 SUN. Si 350 denota el
  allowance facturable, se impone un tamaño firmado máximo de 286 bytes.
- La **reserva máxima se establece antes de firmar**; después se usa el
  tamaño firmado exacto para **verificar cumplimiento** (nunca para
  reducirla con la fórmula incompleta).
- **Se rechaza** (`tron_uncomputable_bound`) cualquier transacción cuya
  cota no pueda calcularse antes de firmar.
- En la reconciliación se **afirma** `actualLossSun ≤ reservationSun`;
  violarlo es invariante roto → alerta + halt del patrocinador, no ajuste
  silencioso.
- **Ledgers separados:** `dailyFailureLossLedger` (cubre solo intentos
  fallidos/indeterminados) vs contabilidad de costo exitoso. El tope diario
  de la política aplica al ledger de fallos; el diseño lo declara
  explícitamente para que "tope diario" no sea ambiguo.

**Horizonte de precios (v11 — rediseño time-based sobre maintenance boundaries):**
la v10 seguía vulnerable en tres puntos: (a) propuestas creadas *después*
de la cotización quedaban fuera del escaneo; (b) el horizonte en bloques no
se relacionaba con la expiración en timestamp de forma exigible por
consenso; (c) `feeDerivationId` era una constante, no un identificador de
contenido. Resolución v11 — el diseño deja de predecir valores de
propuestas y usa la regla de protocolo:

1. **Regla de protocolo (invariante verificable):** en Tron, los cambios de
   parámetros del comité —incluidos `transactionFeeSun` (precio de
   bandwidth) y `energyFeeSun`— toman efecto **únicamente en los boundaries
   de los períodos de mantenimiento** (intervalo `maintenanceIntervalMs`
   leído de chain params; ~6h). La implementación DEBE verificar esta regla
   en fuentes autoritativas a la altura de cotización; si no puede
   verificarse → fail-closed (`tron_governance_data_unavailable`). Sin esta
   regla no hay cota finita.
2. **Cotización sobre bloque solidificado:** `H_q` solidificado, con su
   timestamp de consenso `T_q` (del header, no del reloj local — la
   solidificación elimina el riesgo de reorganización sobre `T_q`).
3. `nextMaintenanceTimeMs` = el menor boundary de mantenimiento
   estrictamente mayor que `T_q`, computado como
   `((T_q // maintenanceIntervalMs) + 1) × maintenanceIntervalMs` con los
   valores leídos en cadena a `H_q`.
4. `pricingHorizonMs = nextMaintenanceTimeMs − marginMs` (margen explícito,
   p. ej. 60_000 ms, versionado en la política; cubre jitter de
   timestamps).
5. **La expiración de la transacción (`raw_data.expiration`, timestamp en
   ms) debe ser estrictamente anterior al horizonte:**
   `txExpirationMs < pricingHorizonMs`. Semántica de borde explícita: la
   igualdad NO basta → rechazo. No hay conversión timestamp→bloque: todo
   vive en el dominio temporal del consenso; la velocidad de producción de
   bloques es irrelevante porque los boundaries de mantenimiento son
   time-based.
6. **Consecuencia:** ninguna propuesta —pendiente, aprobada-no-efectiva o
   **creada después de la cotización**— puede activarse durante
   `[T_q, txExpirationMs]`, porque toda activación ocurre en un boundary ≥
   `nextMaintenanceTimeMs > txExpirationMs`. Por tanto
   `transactionFeeUpperBoundSun = currentFeeSun` (el valor vigente a `H_q`,
   re-verificado contra staleness). No hay estimación empírica.
7. Si la validez solicitada excedería el horizonte → se acorta la
   expiración o se rechaza la cotización (`tron_no_pricing_horizon`).
   Fail-closed también si `maintenanceIntervalMs` no es legible, si `H_q`
   no está solidificado, o si los datos están stale/inconsistentes.
8. **Binding (preimagen de 44 campos, §3):** la cota (34), el horizonte en
   ms (35), y como campos tipados separados: `quoteBlockHeight` (37),
   `quoteBlockTimestampMs` (38), `maintenanceIntervalMs` (39),
   `nextMaintenanceTimeMs` (40), `marginMs` (41), `currentFeeSun` (42),
   `proposalSnapshotHash` (43, digest del set canónico de propuestas).
   `feeDerivationId` (36) es ahora un **digest criptográfico con dominio
   separado** `sha256("TRONFEEDERIVEv1" || H_q || T_q || intervalo ||
   nextMaintenance || margen || currentFee || proposalSnapshotHash ||
   sponsorPolicyVersion)`, **computado por el generador** desde los inputs
   (no un literal): mutar cualquier input cambia el digest y la
   autorización. El generador además valida semánticamente: boundary
   correcto, `horizonte = next − margen`, `expiración < horizonte`
   estricto, y que ninguna propuesta tenga `effectiveTimeMs` anterior al
   próximo boundary.
9. Mapeo explícito de los requisitos del revisor: lifecycle/aprobación/
   activación de propuestas futuras → colapsan en "toda activación es en un
   boundary ≥ nextMaintenanceTimeMs"; solidity lag → `H_q` solidificado;
   policy margin → `marginMs` explícito y versionado.

- Tests requeridos: propuesta creada/aprobada después de la cotización (la
  tx expira antes de que pueda activarse); activación exactamente en el
  borde (igualdad → rechazo); cambio 1000→2000 SUN/byte entre cotización e
  inclusión con boundary intermedio → la cotización se rechaza o se acorta
  (no se emite con horizonte inválido); mutación de cada input de la
  derivación → `feeDerivationId` distinto; `maintenanceIntervalMs`
  ilegible → fail-closed; `H_q` no solidificado → fail-closed.

### P1-4 (v7): un cambio de política no puede invalidar una transacción ya enviada
**Hallazgo:** un broadcast indeterminado puede estar ya en el mempool o en
cadena; invalidar su reserva por un rollover de política liberaría fondos
que aún pueden consumirse.

**Resolución (v9: predicado EXPIRED explícito):**

- Los intentos en `SUBMITTING`, `INDETERMINATE` o `BROADCAST` **retienen
  irrevocablemente** su reserva y su snapshot de política hasta un
  resultado terminal autoritativo **o** el predicado `EXPIRED`, que exige
  **todas** estas condiciones:
  1. La ventana de inclusión relevante está **totalmente solidificada**
     (la solidez de la cadena supera `expiration` + margen).
  2. La fuente de consulta **cubre verificablemente** esa ventana completa
     (cobertura probada, no asumida).
  3. El txID original está **ausente** de ese historial.
  4. Evidencia faltante, stale o contradictoria → **la reserva se retiene**.
- Si la transacción **existe** en el historial → se reconcilia su resultado
  de ejecución finalizado y sus cargos, en vez de liberar.
- Si las capacidades RPC existentes no pueden establecer la ausencia →
  la reserva se retiene y el camino de reemplazo (b) queda **prohibido**.
- Una política nueva **solo** aplica a autorizaciones pre-envío. Jamás se
  libera una reserva incierta por un rollover de política.
- Test requerido: fuente RPC con historial incompleto devuelve `{}` tras la
  expiración local → ni liberación de reserva ni camino (b) disponibles.

### P1-5 (v7): la validación post-firma cubre el envelope completo
**Hallazgo:** verificar solo `raw_data` byte-por-byte no cubre `signature`
ni `ret` del envelope; el conteo de firmas cambia el costo de bandwidth.

**Resolución:**

- Se parsea la **transacción firmada completa** con el mismo decodificador
  estricto: se exige `ret` ausente, conteo y orden exactos de firmas
  esperadas, firmas válidas de firmantes autorizados, sin campos
  desconocidos ni duplicados en el envelope exterior, codificación
  canónica.
- La cota de pérdida (§1 P1-3) se calcula sobre el **tamaño firmado
  exacto**, no sobre una estimación.
- Se persiste el digest de los **bytes firmados completos** y se emiten
  **exactamente esos bytes**. Transición atómica por CAS a `SUBMITTING`
  **antes** de cualquier I/O, para que ningún worker pueda enviar otro
  envelope.

### P1-6 (v7): allowlist explícita por mensaje + requisitos ABI canónicos
**Hallazgo:** la regla de "rechazar desconocidos" no rechaza campos
conocidos-pero-no-listados (`provider = 3`, `ContractName = 4` en
`Contract`; `auths = 9`, `scripts = 12` en `raw_data`); la regla ABI no
exigía 68 bytes exactos de calldata ni ceros en el padding.

**Resolución — allowlist recursiva por mensaje (no solo "desconocidos"):**

- `raw_data` permite **solo**: 1, 3, 4, 8, 10 (vacío exigido), 11, 14, 18.
  Se **rechazan** `auths = 9` y `scripts = 12` **aunque vengan
  presentes-pero-vacíos**.
- `Contract` permite **solo**: 1 (= 31), 2, 5. Se **rechazan** `provider = 3`
  y `ContractName = 4` aunque vengan presentes-pero-vacíos.
- `Any`: 1 (type_url exacto), 2. `TriggerSmartContract`: 1, 2, 3 (= 0), 4,
  5 (= 0), 6 (ausente o 0).
- **Calldata:** longitud exactamente 68 bytes; selector exactamente
  `a9059cbb`; **12 bytes de cero** en el padding superior de la palabra de
  dirección; receptor de 20 bytes normalizado (= `to`); monto uint256
  exacto (= `amountRaw`).
- **El commit/versión del protocolo Tron verificado se pinnea en CI** y la
  implementación falla cerrado si los números publicados difieren.

### P1-7 (v7): el generador va adjunto, con constantes literales y salida de CI
**Hallazgo:** el material enviado no incluía el generador ni los vectores
(fallo de mi pipeline de envío en v7: el texto se condensó y se omitieron
esas secciones).

**Resolución (v9):**

- El generador exacto (`gen_binding_vectors.py`) va **adjunto/commiteado**;
  `EXPECTED` lleva **literales de preimagen hex, longitud y digest** para
  ambos vectores (pinneados en el archivo y en §3); el script afirma los
  tres por vector, imprime ambos vectores completos y el mensaje de éxito.
- Se ejecuta desde un **checkout limpio de CI**; el diseño documenta el
  comando y la salida capturada exitosa:
  `python3 gen_binding_vectors.py` → imprime V1 y V2 (longitud, hex,
  digest) y luego
  `assertions passed: lengths, digests and preimage hex match pinned literals`
  (verificado 2026-09-28).
- **Blindaje del envío:** el material de revisión v9 incluye el fuente
  íntegro y ambos vectores **verbatim**; la instrucción de envío exige
  verificar en el composer la presencia de las secciones "RUNNABLE
  GENERATOR SOURCE" y "VECTORS" (búsqueda del digest
  `353827787b766cfeed8682bccd8a3d6eff1f895f312de9947a002bd5526f070f`)
  **antes** de enviar; si falta alguna sección, no se envía una versión
  condensada.

## 2. Corrección P2 (1)

### P2-1 (v7): el chequeo de profundidad vive dentro del parser + cotas de miembros
**Hallazgo:** el `maxNestingDepth` debe ocurrir en el propio parser (no
después de que un parser genérico ya haya hecho recursión) y no acota
documentos playos con un string/objeto/array gigante.

**Resolución:**

- El chequeo pre-descenso ocurre **dentro de nuestro parser**, antes de
  cualquier descenso (nunca delegamos a un parser JSON genérico recursivo).
- Además se acotan **antes de alocar**: bytes de input (`maxInputBytes`),
  total de tokens/nodos (`maxTokens`), **miembros por contenedor**
  (`maxContainerMembers`), longitudes de strings/números decodificados
  (`maxDecodedStringBytes`, `maxLexemeBytes`).
- Tests de borde: anidamiento en 32 (pasa) y 33 (rechazo) niveles, más
  payloads playos anchos (objeto con `maxContainerMembers+1` claves,
  array gigante, string en el límite).

## 3. Vectores de binding v11 (preimagen de 44 campos)

Campos 1–28: tabla v5/v6 sin cambios. Campos 29–33: `quotedSuccessCostSun`
(u64be), `policyFeeSun` (u64be), `fxId` (UTF-8, prefijo u16be),
`fxSunPerCent` (u64be), `sponsorPolicyVersion` (UTF-8, prefijo u16be).
Campo 34: `transactionFeeUpperBoundSun` (u64be). Campo 35:
`pricingHorizonMs` (u64be, timestamp en ms). Campo 36: `feeDerivationId`
(digest de 32 bytes con dominio `TRONFEEDERIVEv1`, prefijo u16be —
**computado por el generador** desde los campos 37–43 + versión de
política, no un literal). Campos 37–42: `quoteBlockHeight`,
`quoteBlockTimestampMs`, `maintenanceIntervalMs`, `nextMaintenanceTimeMs`,
`marginMs`, `currentFeeSun` (todos u64be). Campo 43:
`proposalSnapshotHash` (digest de 32 bytes del set canónico de propuestas,
prefijo u16be — computado por el generador). Campo 44: verificación
implícita — el generador afirma `pricingHorizonMs =
nextMaintenanceTimeMs − marginMs`, boundary correcto,
`txExpirationMs < pricingHorizonMs` estricto y
`transactionFeeUpperBoundSun = currentFeeSun`. Digest SHA-256, hex
minúsculas. Generador: `gen_binding_vectors.py` (assertions de longitud +
digest + preimagen hex contra literales pinneados **más** validación
semántica de la derivación; corre en CI).

- **V1** (completa; `policyFeeSun = 10 × 10000 = 100000`;
  `quotedSuccessCostSun = 9471900 + 350000 + 100000 = 9921900`;
  `quoteBlockHeight = 12345678`, `quoteBlockTimestampMs = 1759000000000`,
  `maintenanceIntervalMs = 21600000`,
  `nextMaintenanceTimeMs = 1759017600000`, `marginMs = 60000`,
  `pricingHorizonMs = 1759017540000`, `currentFeeSun = 1000`,
  `transactionFeeUpperBoundSun = 1000`, `proposals = []`):
  preimagen **486 bytes** →
  `sha256 = 2206c076e53f4458498582ef996cc67b5535698a0efa48351b02b83aeec48734`
  preimagen hex:
  `000a54524332304645457631001541414141414141414141414141414141414141414100154242424242424242424242424242424242424242420015434343434343434343434343434343434343434343000731303030303030000000000000541700000000000171ff00000000000084d00005636861696e000000000000006400000000000003e8000000000090879c0000000000055730000000000095decc000000000000015e0064001974726332302d7472616e736665722d73696e676c652d73696701000000000000000a000001998c91f600000000000001d4c001abababababababab01cdcd01000001998c93cac001000001998c91f60000046e696c6501000864656164626565660000000000bc614e0020efefefefefefefefefefefefefefefefefefefefefefefefefefefefefefefef000000000097656c00000000000186a0000a746573742d66782d76310000000000002710000473702d3100000000000003e8000001998d9d99a00020c654baa36aa6fcc299a647eeeeb06886af91888da0ffdf9e9fba071c6e87469d0000000000bc614e000001998c91f6000000000001499700000001998d9e8400000000000000ea6000000000000003e80020ce252b0dddf9a6af84daa326f38185288d5cf0b397a891bb6f40362910f7ae59`
- **V2** (display-only, nulls; `policyFeeSun = 0`;
  `quotedSuccessCostSun = 6314500 + 350000 = 6664500`; mismos parámetros
  de horizonte que V1 salvo `quoteBlockHeight = 12345670`):
  preimagen **436 bytes** →
  `sha256 = dd59a1a0bc590edb0f6aa831ee9ee26aec53587aef5a84bed803dbba2c008687`
  preimagen hex:
  `000a54524332304645457631001541414141414141414141414141414141414141414100154242424242424242424242424242424242424242420015434343434343434343434343434343434343434343000130000000000000380f000000000000f6a900000000000084d00005636861696e000000000000006400000000000003e80000000000605a040000000000055730000000000065b134000000000000015e0064001974726332302d7472616e736665722d73696e676c652d73696700000001998c91f600000000000001d4c00000000000046e696c65000000000000bc614600201212121212121212121212121212121212121212121212121212121212121212000000000065b1340000000000000000000a746573742d66782d76310000000000002710000473702d3100000000000003e8000001998d9d99a000201d5194eac64f13a45a6a885158cfb129bbf9280fc83b9f6faf7c9568a57fb0950000000000bc6146000001998c91f6000000000001499700000001998d9e8400000000000000ea6000000000000003e80020ce252b0dddf9a6af84daa326f38185288d5cf0b397a891bb6f40362910f7ae59`

## 4. API final (`src/lib/tron/fees.ts`)

```ts
getTronChainParameters(config?) → { /* v9, sin cambios */ }
deriveFeeHorizon({ quoteBlockHeight, config }) → {
  // v11: lee maintenanceIntervalMs + timestamp del bloque SOLIDIFICADO H_q;
  // verifica la regla "activaciones solo en maintenance boundaries" en
  // fuentes autoritativas; computa nextMaintenanceTimeMs y pricingHorizonMs.
  // Capacidades RPC requeridas: (a) chain params a una altura; (b) header
  // con timestamp de un bloque solidificado; (c) prueba de solidez.
  // Si algo no es probable → tron_governance_data_unavailable (fail-closed).
  transactionFeeUpperBoundSun /* = currentFeeSun */,
  pricingHorizonMs, nextMaintenanceTimeMs, marginMs,
  quoteBlockTimestampMs, maintenanceIntervalMs, currentFeeSun,
  proposalSnapshotHash, feeDerivationId
}
estimateTrc20TransferEnergy(input) → { /* v9, sin cambios */ }
quoteTrc20TransferFee({from, to, contract, amountRaw, policy?, config?}) → {
  /* v9, con policyFeeSun = policyFeeCents × fxSunPerCent (sin división);
     v11: exige txExpirationMs < pricingHorizonMs (estricto; igualdad =
     rechazo); si la validez pedida excede el horizonte → acortar o
     tron_no_pricing_horizon */
  authorizationRecord: AuthorizationRecord, // §1 v9 + §1 v11
  bindingHash: string  // preimagen v11 §3 (44 campos)
}
isFeeQuoteFresh(quote, nowMs?) → boolean
isQuoteBuildReady(quote, nowMs?, freshParams) → boolean
reserveSponsorCapacity(quote) → { reserved: true, attemptId } | { error }
  // reserva atómica; intento ligado a un único txID (§1 P1-2)
attemptStateMachine.transition(attemptId, from, to) // CAS durable (§1 P1-2);
  // estados: AUTHORIZED → RESERVED → SUBMITTING → {BROADCAST|INDETERMINATE}
  // → TERMINAL{CONFIRMED,FAILED,EXPIRED}; EXPIRED exige el predicado §1 P1-4
finalGateBuild(quote, authorization, config) → { finalBytes, newQuote } | { abort: reason }
  // envelope firmado completo verificado + digest persistido (§1 P1-5);
  // broadcast de exactamente esos bytes tras CAS a SUBMITTING;
  // expiration ≤ pricingHorizonEnd (§1 P1-3)
```

Errores: los de v9 + `tron_governance_data_unavailable`,
`tron_amount_overflow`, `tron_uncomputable_bound`,
`tron_no_pricing_horizon`, `tron_ledger_conflict`, `tron_abi_mismatch`,
`tron_schema_violation` (ya), `tron_replacement_forbidden`.

## 5. Seguridad (invariantes v11)

Todo lo de v9 más: la cota de precio ya no estima nada — `txExpirationMs <
pricingHorizonMs` estricto con `pricingHorizonMs = nextMaintenanceTimeMs −
marginMs`, donde los cambios de gobernanza solo toman efecto en
boundaries de mantenimiento (regla de protocolo verificada o fail-closed);
`transactionFeeUpperBoundSun = currentFeeSun`; sin conversión
timestamp→bloque (todo en tiempo de consenso); `feeDerivationId` es un
digest computado desde inputs tipados ligados (preimagen de 44 campos,
§3); el generador valida semánticamente la derivación.

## 6. Tests (`tests/wallet/tron-fees.test.ts`)

Lo de v7 más: vectores dimensionales FX (`(100,33333)→3333300`,
`(1,1)→1`, `(0,x)→0`, overflow → `tron_amount_overflow`); reemplazo con
mismo `attemptId` pero bytes distintos → `tron_replacement_forbidden` (o
nueva reserva según política); transiciones CAS inválidas rechazadas;
`actual > reserva` en reconciliación → halt; reserva liberada por rollover
de política en `INDETERMINATE` → prohibido (test); envelope con `ret`
presente / firma extra / campo exterior desconocido → rechazo; `provider`,
`ContractName`, `auths`, `scripts` presentes-pero-vacíos → rechazo;
calldata de 67/69 bytes o padding no cero → `tron_abi_mismatch`;
anidamiento 32/33; contenedor con `maxContainerMembers+1`; vectores V1/V2
v8/v9 desde el generador con literales (longitud + digest + hex);
bandwidth: recursos agotados + tamaño firmado máximo + presupuesto de
energía del caller consumido íntegro → `actual ≤ reserva`; horizonte de
precios: propuesta creada/aprobada después de la cotización → la tx expira
antes de que pueda activarse; activación exactamente en el borde
(igualdad → rechazo); cambio 1000→2000 SUN/byte con boundary intermedio →
cotización rechazada o acortada; mutación de cada input de la derivación →
`feeDerivationId` distinto; `maintenanceIntervalMs` ilegible o `H_q` no
solidificado → fail-closed; fuente RPC con historial incompleto devuelve
`{}` tras expiración local → sin liberación ni camino (b).

## 7. Decisiones para SCRUM-91 (tras APPROVE)

1. Piloto = burn con la wallet operativa como caller (usuario sin TRX);
   staking diseñado, activación bloqueada por firma + umbral cuantitativo v8.
2. Cota dinámica = `getDynamicEnergyMaxFactor` del nodo (`"chain"`), 4.4x hoy.
3. `bindingHash` = detector de mismatch; autorización = `authorizationRecord`
   con ledger diario, CAS durable y broadcast idempotente.
4. Out-of-energy / OUT_OF_TIME = fallo posible con pérdida acotada por
   `fee_limit`; la política del patrocinador la provisiona explícitamente.

## 8. Trazabilidad v2 → v4

Ver §9 (12 filas F-xx; nota de honestidad sobre etiquetado de v3).

## 9. Trazabilidad: los 12 hallazgos de v2 → v3 → v4

Nota de honestidad: v3 etiquetó mal la severidad de dos ítems (bindingHash
era P2 en v2; contexto de bloque era P1 en v2) y no identificó el noveno P1.
La tabla usa IDs de sustancia F-xx; la columna v2 indica la severidad
original según la mejor reconstrucción.

| # | Hallazgo v2 (sustancia) | v3 (§) | v4 (§) | Test de cierre |
|---|-------------|--------|--------|----------------|
| F-P0 | techo dinámico: fórmula 4.4x + evidencia del bound en Nile | §0 (4.4x + config versionada) | §0 (4.4x + `getDynamicEnergyMaxFactor=34000` leído del nodo, `boundSource:"chain"`; fail-closed sin clave) | ejemplo 4.4x; clave ausente → `tron_unbounded_dynamic_energy` |
| F-P1-a | normalización de estimadores (`max()` de dos endpoints distintos) | §1 P1-1 (contrato semántico) | §1 P1-1 (prueba bajo hipótesis A y B; `conservativeEnergyUnits`; multiplicador aplicado una vez) | hipótesis B simulada: cota ≥ real; nominal null |
| F-P1-b | `expectedCallerCostSun` no computable (degradación `getcontractinfo`) | §1 P1-2 (`nominal…: null`) | §1 P1-1 (nominal null tipado); §1 P1-3 (autorización solo con peor caso) | `nominalCallerCostSun === null` |
| F-P1-c | reserva de bandwidth vs builder (garantía de débito máximo) | §1 P1-3 (contrato builder) | §1 P1-3 + §4 (shape + byteAllowance ligados; descarta y re-cotiza) | bytes firmados > 350 → re-quote, nunca top-up |
| F-P1-d | `bindingHash`: rol + preimagen exacta (v2: P2) | §1 P1-4 (preimagen con elipsis + disclaimer) | §1 P1-3 (no autoriza) + §2 P2-1 (tabla completa + vectores V1/V2) | vectores V1/V2 |
| F-P1-e | JSON estricto: detección de duplicados (regex evadible) | §1 P1-5 (tokenizer) | §1 P1-7 (iterativo acotado; sets por objeto; fuzzing) | `\u0067…`, lone surrogates, trailing, límites |
| F-P1-f | gramática del input de policy + semántica de cobro | §1 P1-6 | §1 P1-6 (sin cambios) | `0`→10, `1000`→10, `1001`→11, max, max+1 |
| F-P1-g | ledger del pool (unidades vs SUN) | §1 P1-7 | §1 P1-5 (pool = wallet operativa; reserve/commit/release; sin doble conteo) | doble-reserva rechazada; reconciliación desde receipts |
| F-P1-h | regla económica burn-vs-stake | §1 P1-8 | §1 P1-6 (todo en SUN; `L(h)` a altura de decisión; base temporal de Cops) | modelo con umbral fijado con datos reales |
| F-P1-i | frescura + binding del bloque de referencia (v2: P1) | §2 P2-1 | §1 P1-2 (tuple TAPOS completo) + §2 P2-2 (anti-futuro) | `blockBound:false` → no build-ready; futuro → no-fresh |
| F-P2-a | validación de inputs como invariante de API (v2: P2) | §2 P2-2 | §2 P2-2 (sin cambios) | direcciones / `amountRaw` |
| F-P1-? | **Noveno P1 de v2, no identificado en el texto de v3.** El candidato más probable es *autoridad de fondeo y ciclo de vida del pool* (la disposición de v2 lo dejó "abierto" tras v3); otros candidatos: checks de grado-autorización, outcome chain-max. | — (no enumerado) | §1 P1-3 (build-readiness ≠ autorización), §1 P1-4 (chain-max), §1 P1-5 (autoridad de fondeo + reserve/commit/release + idempotencia) — los tres candidatos cerrados | `isQuoteBuildReady` exige chain-max; pool sin ficción de débito; autorización diferida a capa servidora |

## 10. Trazabilidad v4 → v5

| # | Hallazgo v4 | v5 (§) | Cierre |
|---|-------------|--------|--------|
| P1-1 | la simulación no acota la ejecución futura | §1 P1-1: `energyBasis: "simulated-conservative-at-height"`; ancla `simulationBlockHeight/Hash`/`simulatedAtMs`; re-simulación ≤ N bloques o re-quote; out-of-energy = fallo con pérdida acotada por `fee_limit` | test re-simulación con base cambiada → re-quote |
| P1-2 | cambios de chainparams no invalidan quotes emitidas | §1 P1-2: `isQuoteBuildReady(quote, nowMs, freshParams)` con snapshot verificado-contra-génesis; igualdad exacta en los 5 parámetros; re-quote server-side mandatorio | test con `freshParams` alterado → false |
| P1-3 | invariante TAPOS/raw-data inconsistente (fee_limit cambia los bytes) | §1 P1-3: receta sobre bytes del nodo + relación parse-compare (`fee_limit` único cambio permitido); expiración en la expresión formal; validación del bloque de referencia | test parse-compare con fixture |
| P1-4 | preimagen sin nulls definidos; vectores no reproducibles | §1 P1-4: tags `0x00`/`0x01` en todos los nullables; reglas de hex; generador checked-in; V1/V2 regenerados con preimagen hex completa | test lee `binding_vectors.json` y compara |
| P1-5 | break-even: `E` sin definir, `D` sin usar, beneficio bruto | §1 P1-5: `E(S,h) = floor(S×L(h)/W(h))`; `B_e_inc` incremental; `D` en `(H+D)/365`; `N_peak`; sensibilidad en H ∈ {30,90,365} | — (modelo; umbral con datos reales) |
| P2-1 | semántica de bytes/números del parser | §2: UTF-8 estricto, BOM rechazado, token/step definidos, lexema→BigInt directo, exponentes rechazados en enteros | tests BOM, UTF-8 malformado, `1e3`, 2^53, u64 |

## 11. Trazabilidad v5 → v6

| # | Hallazgo v5 | v6 (§) | Cierre |
|---|-------------|--------|--------|
| P1-A | el límite de pérdida del patrocinador no está establecido | §1 P1-A: `quotedSuccessCostSun` vs `maxFailedAttemptLossSun`; `OUT_OF_TIME` puede consumir `fee_limit` íntegro; política de riesgo versionada; exceso → nueva autorización | test: fallo modelado consume fee_limit íntegro; exceso de cap → `tron_sponsor_policy_exceeded` |
| P1-B | los checks de build no cierran la brecha del broadcast | §1 P1-B: `finalGateBuild` con `reQuoteMaxAgeMs`, invalidación de autorización ante cualquier cambio, reintentos acotados con backoff, aborto ante fallo persistente | test: re-quote con monto cambiado → autorización invalidada |
| P1-C | la comparación protobuf puede descartar significado | §1 P1-C: schema soportado; rechazo de campos desconocidos/duplicados/varints no canónicos; serializador determinista; parse-back + identidad de bytes a firmar | test: campo desconocido/duplicado/overlong → rechazo; round-trip = identidad |
| P1-D | vectores no verificables (brecha de evidencia) | §1 P1-D: tabla + generador + fixtures + preimágenes hex íntegras inline en el material de revisión; decoder independiente en tests | test reproduce V1/V2 desde el generador |
| P1-E | la ecuación de staking mezcla unidades (bug mío: ×10⁶) | §1 P1-E: `S_trx = floor(S_sun/10⁶)` con redondeo exacto del protocolo; `E = floor(S_trx × L_current(h)/W(h))`; `L_current` vigente a la misma altura | test del factor 10⁶; capacidad y umbrales recalculados |
| P2-F | la comparación económica necesita base temporal explícita | §2 P2-F: `N`/`N_peak` en transferencias/día; `B_e_inc` por transferencia contra energía disponible en el momento; tratamiento de posición abierta si `H` termina antes del retiro | — (modelo) |
| P2-G | presupuesto del scanner sin especificar | §2 P2-G: `maxInputBytes`, `maxLexemeBytes`, presupuesto en dos dimensiones (tokens y bytes examinados), rechazo de claves duplicadas | tests de límites y `tron_duplicate_key` |

## 12. Trazabilidad v6 → v7

| # | Hallazgo v6 | v7 (§) | Cierre |
|---|-------------|--------|--------|
| P1-1 | el costo exitoso no estaba ligado (policy fee en centavos sin fx ligada) | §1 P1-1: todo en SUN; `policyFeeSun = ceil(cents × fxSunPerCent/100)` con `fx` ligada; `authorizationRecord` canónico con igualdad exacta en la compuerta; preimagen extendida (campos 29–33) | test: cambio de fee/fx → autorización invalidada |
| P1-2 | tope diario no exigible bajo concurrencia ni broadcast ambiguo | §1 P1-2: ledger diario durable, reserva atómica pre-firma, `attemptId` idempotente, indeterminados como pérdida pendiente, reconciliación solo autoritativa, re-evaluación ante cambio de política | test: concurrencia simulada; doble reserva imposible |
| P1-3 | la compuerta no ligaba todo el estado (owner, calldata, enum, type_url, …) | §1 P1-3: `authorizationRecord` cubre semántica + envelope + economía + versiones; parse del envelope firmado byte-por-byte; un único broadcast idempotente | test: envelope alterado un byte → falla |
| P1-4 | protobuf sin profundidad (Any anidado, field numbers, ABI) | §1 P1-4: field numbers/wire types normativos, exactamente un contrato, enum 31, type_url exacto, rechazo recursivo, decodificación ABI independiente `a9059cbb` | test: `tron_abi_mismatch`, `tron_schema_violation` |
| P1-5 | generador con `SyntaxError` en el texto enviado | §1 P1-5: archivo con literales + assertions (longitud, digest, preimagen hex) que pasan; ejecución en CI; fuente runnable en la revisión | CI ejecuta `gen_binding_vectors.py` |
| P2-1 | scanner sin garantía de profundidad | §2 P2-1: `maxNestingDepth` (32) antes de descender; parser iterativo o contador mandatorio; tests adversariales | test de anidamiento profundo |
| P2-2 | denominador del staking ambiguo (pre vs post stake) | §2 P2-2: `W_after = W_before + S_trx`; orden exacto `((S_trx × L) // (W+S_trx))`; pareo de snapshots a la misma altura | test: pre-stake sobrestima vs post-stake |

## 13. Trazabilidad v7 → v8 (los 8 hallazgos de la séptima revisión)

| # | Hallazgo v7 | v8 (§) | Cierre |
|---|-------------|--------|--------|
| P1-1 | FX dimensionalmente incorrecta (÷100 de más; bug mío) | §1 P1-1: `policyFeeSun = policyFeeCents × fxSunPerCent` sin división; u64/u128 con `tron_amount_overflow`; vectores dimensionales; V1 regenerado | tests `(100,33333)→3333300`, overflow |
| P1-2 | replacements podían consumir más de una reserva | §1 P1-2: intento+reserva ligados a un único txID; reintentos solo byte-idénticos; replacements con reserva propia o prohibidos; CAS durable `AUTHORIZED→…→TERMINAL` | test: replacement mismo attemptId → `tron_replacement_forbidden` |
| P1-3 | la reserva no era una cota superior probada | §1 P1-3: `maxFailedAttemptLossSun = energyFeeLimitSun + ceil(maxSignedBytes × transactionFeeSun)`; `tron_uncomputable_bound`; afirmación `actual ≤ reserva`; ledgers separados | test: `actual > reserva` → halt |
| P1-4 | un cambio de política no puede invalidar lo ya enviado | §1 P1-4: `SUBMITTING`/`INDETERMINATE`/`BROADCAST` retienen reserva+snapshot irrevocablemente hasta resultado terminal o expiración observada conservadoramente | test: rollover no libera reserva incierta |
| P1-5 | la validación post-firma solo cubría `raw_data` | §1 P1-5: envelope firmado completo parseado; `ret` ausente; firmas exactas y válidas; digest de bytes firmados persistido; CAS a `SUBMITTING` antes de I/O | test: firma extra / `ret` → rechazo |
| P1-6 | allowlist omitía campos conocidos; ABI sin requisitos canónicos | §1 P1-6: allowlist explícita por mensaje (rechaza `provider`, `ContractName`, `auths`, `scripts` aunque vacíos); calldata 68 bytes exactos, 12 ceros de padding; commit del protocolo pinneado en CI | tests `tron_schema_violation` / `tron_abi_mismatch` |
| P1-7 | el generador no iba en el material enviado (fallo de mi pipeline) | §1 P1-7: generador adjunto con constantes literales pinneadas; comando y salida de CI documentados; instrucción anti-condensación en el envío | CI: `python3 gen_binding_vectors.py` |
| P2-1 | profundidad sin cotas de miembros; chequeo fuera del parser | §2 P2-1: chequeo dentro de nuestro parser; `maxContainerMembers`; cotas pre-alocación; tests 32/33 + payloads playos | tests de borde |

## 14. Trazabilidad v8 → v9 (los 4 hallazgos de la octava revisión)

| # | Hallazgo v8 | v9 (§) | Cierre |
|---|-------------|--------|--------|
| P1-1 | la fórmula de bandwidth omite el overhead de resultado (+64 bytes) | §1 P1-3: `maxBillableBandwidthBytes = maxAcceptedSignedSizeBytes + 64`; `bandwidthBurnBoundSun` con `transactionFeeUpperBoundSun`; reserva máxima pre-firma; verificación con tamaño firmado exacto | test: bandwidth agotado + tamaño máximo + energía íntegra → `actual ≤ reserva` |
| P1-2 | el precio de bandwidth cotizado no es cota sobre la vida ejecutable (la gobernanza puede cambiarlo) | §1 P1-3: `transactionFeeUpperBoundSun` versionada en política; `expiration ≤ pricingHorizonEnd`; fail-closed `tron_no_pricing_horizon` | test: 1000→2000 SUN/byte entre cotización e inclusión → dentro de la cota |
| P1-3 | el predicado de expiración/finalidad era un placeholder; `BROADCAST` no estaba en la máquina de estados | §1 P1-4: predicado `EXPIRED` explícito (ventana solidificada + cobertura verificada + txID ausente; evidencia dudosa retiene); `BROADCAST` añadido a la máquina; camino (b) prohibido sin ausencia probada | test: RPC con historial incompleto → `{}` → sin liberación ni camino (b) |
| P1-4 | el generador enviado tenía el fuente corrompido por el paste (intervención manual a mitad del envío) | §1 P1-7: `EXPECTED` con literales hex+longitud+digest afirmados los tres; imprime ambos vectores y mensaje de éxito; verificación del composer pre-submit obligatoria (búsqueda del digest V1) | CI ejecuta `gen_binding_vectors.py`; el revisor ya verificó los digests independientemente |

## 15. Trazabilidad v9 → v10 (el único hallazgo de la novena revisión)

| # | Hallazgo v9 | v10 (§) | Cierre |
|---|-------------|---------|--------|
| P1 | la cota de precio seguía siendo empírica (máximo observado × factor), no un techo exigible por protocolo | §1 P1-3: `deriveFeeUpperBound` auditable — escanea propuestas del comité en cadena (valor + bloque efectivo por reglas del protocolo), calcula `maxEffectiveFee` sobre la ventana de inclusión, `expirationBlock < pricingHorizonBlock` estricto con margen explícito; fail-closed `tron_governance_data_unavailable` / `tron_no_pricing_horizon`; cota + horizonte + `feeDerivationId` + versión de política ligados en la autorización (preimagen de 36 campos, §3) | tests: propuesta post-cotización; activación en el borde (igualdad → rechazo); tarifa sobre el factor histórico; gobernanza stale/incompleta/inconsistente → fail-closed |

## 16. Trazabilidad v10 → v11 (los 3 hallazgos de la décima revisión)

| # | Hallazgo v10 | v11 (§) | Cierre |
|---|--------------|---------|--------|
| P1-1 | propuestas creadas después de `H_q` quedaban fuera de la cota | §1: rediseño time-based — los cambios de gobernanza solo toman efecto en boundaries de mantenimiento; `txExpirationMs < nextMaintenanceTimeMs − marginMs` estricto ⇒ ninguna propuesta (ni futura) puede activarse durante la vida de la tx; `transactionFeeUpperBoundSun = currentFeeSun`; validez que exceda el horizonte → acortar o rechazar | test: propuesta post-cotización; la tx expira antes de su posible activación |
| P1-2 | relación timestamp→bloque del horizonte sin especificar ni exigible | §1: sin conversión — todo en tiempo de consenso (ms): `nextMaintenanceTimeMs` desde el timestamp del bloque solidificado `H_q`; `raw_data.expiration < pricingHorizonMs`; boundaries time-based ⇒ velocidad de bloques irrelevante; borde explícito (igualdad = rechazo); reorg cubierto por `H_q` solidificado | tests de borde y de `H_q` no solidificado → fail-closed |
| P1-3 | `feeDerivationId` era la constante `gov-scan-v1`, no un identificador de contenido | §3: `feeDerivationId` = digest `sha256("TRONFEEDERIVEv1"‖…)` **computado por el generador**; inputs como campos tipados 37–43; el generador valida semánticamente (boundary, `horizonte = next − margen`, `expiración < horizonte`, `cota = currentFee`) | tests de mutación por cada input; fixtures con identificadores reales |
