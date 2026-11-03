import os
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import numpy as np

# Qiskit imports
from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator
from thorlabs_hardware import hardware_manager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(
    title="E91 QKD Simulator API - Thorlabs EDU-QOP1 & EDU-QOPA1 Experiment 25.4",
    description="Backend simulating Artur Ekert's E91 QKD protocol and the Thorlabs Polarization-Entanglement Extension Kit Experiment 25.4"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simulator initialization
simulator = AerSimulator()

# --- Request & Response Models ---
class CHSHRequest(BaseModel):
    shots: int = 1024

class KeyGenRequest(BaseModel):
    count: int = 50

class EveRequest(BaseModel):
    shots: int = 1000
    intercept_prob: float = 0.5

class ThorlabsStepRequest(BaseModel):
    alice_basis: str = Field(default="0|90", description="'0|90' (HV) or '-45|45' (Diagonal)")
    bob_basis: str = Field(default="0|90", description="'0|90' (HV) or '-45|45' (Diagonal)")
    error_rate: float = Field(default=0.05, ge=0.0, le=0.5, description="Physical bit-flip error rate (typically ~5% in Thorlabs kit)")
    eve_active: bool = Field(default=False, description="Simulate Eve intercept-resend attack")
    use_hardware: Optional[bool] = Field(default=None, description="Use live TimeTagger hardware if True or if hardware mode is active")

class ThorlabsBatchRequest(BaseModel):
    count: int = Field(default=75, ge=1, le=500, description="Number of photon pairs to measure (e.g. 75 pairs as in Thorlabs Fig 246)")
    error_rate: float = Field(default=0.05, ge=0.0, le=0.5)
    eve_active: bool = Field(default=False)
    eve_intercept_prob: float = Field(default=1.0, ge=0.0, le=1.0)
    use_hardware: Optional[bool] = Field(default=None)

class ThorlabsRatesRequest(BaseModel):
    shots: int = Field(default=1000, ge=100, le=10000)
    error_rate: float = Field(default=0.05, ge=0.0, le=0.5)

class HardwareModeRequest(BaseModel):
    mode: str = Field(description="'hardware' or 'simulation'")

class HardwareLaserRequest(BaseModel):
    enable: Optional[bool] = None
    current_ma: Optional[float] = Field(default=None, ge=0.0, le=100.0)

class HardwareSettingsRequest(BaseModel):
    coincidence_window_ns: Optional[float] = Field(default=None, ge=0.1, le=100.0)
    delay_a_ns: Optional[float] = Field(default=None, ge=-100.0, le=100.0)
    delay_b_ns: Optional[float] = Field(default=None, ge=-100.0, le=100.0)
    delay_c_ns: Optional[float] = Field(default=None, ge=-100.0, le=100.0)
    laser_current_ma: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    save_to_xml: bool = True

class DelaySweepRequest(BaseModel):
    start_ns: float = -16.0
    end_ns: float = 16.0
    step_ns: float = 0.5
    integration_ms: float = 300.0

# --- Phase 1: CHSH Bell Inequality Verification ---
@app.post("/api/phase1/chsh")
async def run_chsh(req: CHSHRequest):
    """
    Computes CHSH inequality violation (S-value) using Qiskit AerSimulator.
    Measures at 4 analyzer angle combinations:
    E1: (0°, 22.5°), E2: (0°, 67.5°), E3: (45°, 22.5°), E4: (45°, 67.5°)
    """
    pairs = [
        (0, 22.5),   # E1
        (0, 67.5),   # E2
        (45, 22.5),  # E3
        (45, 67.5)   # E4
    ]
    
    correlations = []
    
    for theta_a, theta_b in pairs:
        qc = QuantumCircuit(2, 2)
        # Bell state preparation |Phi+> = (|00> + |11>)/sqrt(2)
        qc.h(0)
        qc.cx(0, 1)
        
        # Basis rotation
        qc.ry(-2 * np.radians(theta_a), 0)
        qc.ry(-2 * np.radians(theta_b), 1)
        
        qc.measure(0, 0)
        qc.measure(1, 1)
        
        transpiled_qc = transpile(qc, simulator)
        job = simulator.run(transpiled_qc, shots=req.shots)
        counts = job.result().get_counts()
        
        n_same = counts.get('00', 0) + counts.get('11', 0)
        n_diff = counts.get('01', 0) + counts.get('10', 0)
        corr = (n_same - n_diff) / req.shots
        correlations.append(round(corr, 4))
    
    # S = E1 - E2 + E3 + E4
    s_raw = correlations[0] - correlations[1] + correlations[2] + correlations[3]
    s_value = abs(s_raw)
    
    return {
        "s_value": round(s_value, 4),
        "correlations": correlations,
        "violation": s_value > 2.0,
        "source": "Qiskit AerSimulator"
    }

# --- Phase 2: Key Generation & Sifting ---
@app.post("/api/phase2/keygen")
async def run_keygen(req: KeyGenRequest):
    """
    Simulates random basis selection and measurement for Alice and Bob.
    Aligns with E91 and Thorlabs kit bases:
    0° (HV basis) and 45° (Diagonal basis).
    """
    alice_bases = []
    bob_bases = []
    raw_bits_a = []
    raw_bits_b = []
    
    basis_opts = [0, 45]  # HV (0) and Diagonal (45)
    
    for _ in range(req.count):
        b_a = int(np.random.choice(basis_opts))
        b_b = int(np.random.choice(basis_opts))
        
        qc = QuantumCircuit(2, 2)
        qc.h(0)
        qc.cx(0, 1)
        
        qc.ry(-2 * np.radians(b_a), 0)
        qc.ry(-2 * np.radians(b_b), 1)
        
        qc.measure(0, 0)
        qc.measure(1, 1)
        
        job = simulator.run(transpile(qc, simulator), shots=1)
        res = list(job.result().get_counts().keys())[0]
        
        bit_a = int(res[1])
        bit_b = int(res[0])
        
        alice_bases.append(b_a)
        bob_bases.append(b_b)
        raw_bits_a.append(bit_a)
        raw_bits_b.append(bit_b)
    
    return {
        "alice_bases": alice_bases,
        "bob_bases": bob_bases,
        "raw_bits_a": raw_bits_a,
        "raw_bits_b": raw_bits_b
    }

# --- Phase 3: Eavesdropping & Noise Analysis ---
@app.post("/api/phase3/attack")
async def run_eve_attack(req: EveRequest):
    """
    Simulates CHSH Bell violation degradation when Eve intercepts photons.
    """
    pairs = [(0, 22.5), (0, 67.5), (45, 22.5), (45, 67.5)]
    correlations = []
    
    for theta_a, theta_b in pairs:
        if np.random.random() < req.intercept_prob:
            # Eve intercepts and measures
            qc = QuantumCircuit(2, 2)
            qc.h(0)
            qc.cx(0, 1)
            
            eve_angle = np.random.choice([0, 45])
            qc.ry(-2 * np.radians(eve_angle), 0)
            qc.ry(-2 * np.radians(eve_angle), 1)
            qc.measure(0, 0)
            qc.measure(1, 1)
            
            temp_job = simulator.run(transpile(qc, simulator), shots=1)
            eve_result = list(temp_job.result().get_counts().keys())[0]
            
            qc = QuantumCircuit(2, 2)
            if eve_result[1] == '1':
                qc.x(0)
            if eve_result[0] == '1':
                qc.x(1)
            
            qc.ry(-2 * np.radians(theta_a), 0)
            qc.ry(-2 * np.radians(theta_b), 1)
            qc.measure(0, 0)
            qc.measure(1, 1)
        else:
            qc = QuantumCircuit(2, 2)
            qc.h(0)
            qc.cx(0, 1)
            qc.ry(-2 * np.radians(theta_a), 0)
            qc.ry(-2 * np.radians(theta_b), 1)
            qc.measure(0, 0)
            qc.measure(1, 1)
        
        job = simulator.run(transpile(qc, simulator), shots=req.shots)
        counts = job.result().get_counts()
        
        n_same = counts.get('00', 0) + counts.get('11', 0)
        n_diff = counts.get('01', 0) + counts.get('10', 0)
        corr = (n_same - n_diff) / req.shots
        correlations.append(corr)
    
    s_value = abs(correlations[0] - correlations[1] + correlations[2] + correlations[3])
    
    return {
        "s_value": round(s_value, 4),
        "correlations": correlations,
        "is_secure": s_value > 2.0,
        "eve_active": req.intercept_prob > 0
    }

# ============================================================================
# --- Thorlabs EDU-QOP1 & EDU-QOPA1 Experiment 25.4 Specialized Endpoints ---
# ============================================================================

def _normalize_basis(b: str) -> str:
    b_str = str(b).strip()
    if b_str in ["0", "0°", "0|90", "0°|90°", "HV", "hv"]:
        return "0|90"
    if b_str in ["45", "45°", "-45|45", "-45°|45°", "diag", "DIAG", "-45", "22.5"]:
        return "-45|45"
    return "0|90"

def _simulate_single_thorlabs_pair(
    alice_b: str,
    bob_b: str,
    error_rate: float = 0.05,
    eve_active: bool = False
) -> Dict[str, Any]:
    """
    Simulates a single photon pair event in the 4-detector Thorlabs setup.
    State: |Psi+> = (|HH> + |VV>)/sqrt(2)
    Detectors:
      Alice: T (Transmitted, Bit 0), B (Reflected, Bit 1)
      Bob:   A (Transmitted, Bit 0), C (Reflected, Bit 1)
    Bit mapping:
      0° (H) and -45° -> Bit 0 (Detectors T and A)
      90° (V) and +45° -> Bit 1 (Detectors B and C)
    """
    is_match = (alice_b == bob_b)
    
    if eve_active:
        # Eve intercept-resend attack:
        # Eve chooses random basis (HV or Diag), measures and resends
        eve_basis = np.random.choice(["0|90", "-45|45"])
        eve_bit = int(np.random.choice([0, 1]))
        
        # Alice measures
        if alice_b == eve_basis:
            bit_a = eve_bit
        else:
            bit_a = int(np.random.choice([0, 1]))
            
        # Bob measures
        if bob_b == eve_basis:
            bit_b = eve_bit
        else:
            bit_b = int(np.random.choice([0, 1]))
            
        is_bit_flip = (bit_a != bit_b) if is_match else False
    else:
        # Normal quantum channel from SPDC entangled source
        if is_match:
            # Same basis: quantum correlations produce identical results
            # Imperfection (finite extinction ratio, alignment, Migdall effect) ~ error_rate
            if np.random.random() < error_rate:
                # Bit flip error
                bit_a = int(np.random.choice([0, 1]))
                bit_b = 1 - bit_a
                is_bit_flip = True
            else:
                common_bit = int(np.random.choice([0, 1]))
                bit_a = common_bit
                bit_b = common_bit
                is_bit_flip = False
        else:
            # Different bases: 50/50 uncorrelated
            bit_a = int(np.random.choice([0, 1]))
            bit_b = int(np.random.choice([0, 1]))
            is_bit_flip = False

    # Map bits to detectors & physical polarizations
    # Alice: T -> 0, B -> 1
    alice_det = "T" if bit_a == 0 else "B"
    # Bob: A -> 0, C -> 1
    bob_det = "A" if bit_b == 0 else "C"

    # Polarization angles
    if alice_b == "0|90":
        alice_pol = 0 if bit_a == 0 else 90
    else:
        alice_pol = -45 if bit_a == 0 else 45

    if bob_b == "0|90":
        bob_pol = 0 if bit_b == 0 else 90
    else:
        bob_pol = -45 if bit_b == 0 else 45

    coincidence_label = f"{alice_det}&{bob_det}"

    return {
        "alice_basis": alice_b,
        "bob_basis": bob_b,
        "alice_detector": alice_det,
        "bob_detector": bob_det,
        "coincidence": coincidence_label,
        "alice_polarization": alice_pol,
        "bob_polarization": bob_pol,
        "alice_bit": bit_a,
        "bob_bit": bit_b,
        "basis_match": is_match,
        "is_bit_flip": is_bit_flip
    }

@app.post("/api/thorlabs/step")
async def thorlabs_step(req: ThorlabsStepRequest):
    """
    Measures or simulates one coincidence event between Alice and Bob when both have set their bases.
    In Real Hardware Mode, waits for the first physical coincidence event on the Swabian Time Tagger 20
    (and NEVER falls back to simulation).
    """
    a_b = _normalize_basis(req.alice_basis)
    b_b = _normalize_basis(req.bob_basis)
    want_hw = req.use_hardware if req.use_hardware is not None else (hardware_manager.mode == "hardware")
    if want_hw:
        return await asyncio.to_thread(hardware_manager.wait_for_first_coincidence, a_b, b_b)
    res = _simulate_single_thorlabs_pair(a_b, b_b, req.error_rate, req.eve_active)
    res["source"] = "simulation"
    return res

@app.post("/api/thorlabs/batch")
async def thorlabs_batch(req: ThorlabsBatchRequest):
    """
    Simulates N photon pairs with random basis choices (Simulation Mode only).
    Disabled in Real Hardware Mode.
    """
    want_hw = req.use_hardware if req.use_hardware is not None else (hardware_manager.mode == "hardware")
    if want_hw:
        return {
            "error": "Batch simulation is disabled in Real Hardware Mode. Only real physical measurements can be performed.",
            "count": 0,
            "source": "hardware",
            "events": [],
            "matching_count": 0,
            "bit_flip_count": 0,
            "qber": 0.0,
            "raw_key_alice": "",
            "raw_key_bob": "",
        }

    basis_options = ["0|90", "-45|45"]
    basis_pairs = [(str(np.random.choice(basis_options)), str(np.random.choice(basis_options))) for _ in range(req.count)]
    events = []
    for i, (a_b, b_b) in enumerate(basis_pairs):
        is_eve = req.eve_active and (np.random.random() < req.eve_intercept_prob)
        ev = _simulate_single_thorlabs_pair(a_b, b_b, req.error_rate, is_eve)
        ev["index"] = i + 1
        ev["source"] = "simulation"
        events.append(ev)
        
    matching_events = [e for e in events if e["basis_match"]]
    total_matching = len(matching_events)
    bit_flips = sum(1 for e in matching_events if e["is_bit_flip"])
    qber = (bit_flips / total_matching) if total_matching > 0 else 0.0

    return {
        "count": req.count,
        "source": "simulation",
        "events": events,
        "matching_count": total_matching,
        "bit_flip_count": bit_flips,
        "qber": round(qber, 4),
        "raw_key_alice": "".join(str(e["alice_bit"]) for e in matching_events),
        "raw_key_bob": "".join(str(e["bob_bit"]) for e in matching_events),
    }

# ============================================================================
# --- Thorlabs EDU-QOP1 Live Hardware Control & Calibration Endpoints ---
# ============================================================================

@app.get("/api/hardware/scan")
async def hardware_scan():
    return await asyncio.to_thread(hardware_manager.scan_devices)

@app.get("/api/hardware/status")
async def hardware_status():
    return await asyncio.to_thread(hardware_manager.get_status)

@app.post("/api/hardware/connect")
async def hardware_connect():
    return await asyncio.to_thread(hardware_manager.connect_hardware)

@app.post("/api/hardware/disconnect")
async def hardware_disconnect():
    hardware_manager.cancel_waiting_measurement()
    return await asyncio.to_thread(hardware_manager.disconnect_hardware)

@app.post("/api/hardware/cancel-wait")
async def hardware_cancel_wait():
    return hardware_manager.cancel_waiting_measurement()

@app.post("/api/hardware/mode")
async def hardware_set_mode(req: HardwareModeRequest):
    if req.mode == "hardware":
        if hardware_manager._tagger is None:
            return await asyncio.to_thread(hardware_manager.connect_hardware)
        hardware_manager.mode = "hardware"
    else:
        hardware_manager.cancel_waiting_measurement()
        hardware_manager.set_laser_output(False)
        hardware_manager.mode = "simulation"
    return await asyncio.to_thread(hardware_manager.get_status)

@app.get("/api/hardware/rates")
async def hardware_live_rates(integration_s: float = 0.25):
    return await asyncio.to_thread(hardware_manager.get_live_rates, integration_s)

@app.post("/api/hardware/laser")
async def hardware_laser_control(req: HardwareLaserRequest):
    def _do_laser():
        res = {}
        if req.current_ma is not None:
            res = hardware_manager.set_laser_current(req.current_ma)
        if req.enable is not None:
            res = hardware_manager.set_laser_output(req.enable)
        if not res:
            res = hardware_manager.get_laser_status()
        return res
    return await asyncio.to_thread(_do_laser)

@app.post("/api/hardware/settings")
async def hardware_update_settings(req: HardwareSettingsRequest):
    return hardware_manager.update_settings(
        coincidence_window_ns=req.coincidence_window_ns,
        delay_a_ns=req.delay_a_ns,
        delay_b_ns=req.delay_b_ns,
        delay_c_ns=req.delay_c_ns,
        laser_current_ma=req.laser_current_ma,
        save_to_xml=req.save_to_xml,
    )

@app.post("/api/hardware/delay-sweep")
async def hardware_delay_sweep(req: DelaySweepRequest):
    return hardware_manager.run_delay_sweep(
        start_ns=req.start_ns,
        end_ns=req.end_ns,
        step_ns=req.step_ns,
        integration_ms=req.integration_ms,
    )

@app.post("/api/thorlabs/coincidence_rates")
async def thorlabs_coincidence_rates(req: ThorlabsRatesRequest):
    """
    Calculates the 4 coincidence rates (T&A, T&C, B&A, B&C) across all 4 waveplate configurations
    matching Table 25.4.3 of the Thorlabs manual:
      0°/0°: High (T&A, B&C), Close to zero (T&C, B&A)
      0°/22.5°: Medium for all 4
      22.5°/0°: Medium for all 4
      22.5°/22.5°: High (T&A, B&C), Close to zero (T&C, B&A)
    """
    configs = [
        {"alice_hwp": "0°", "bob_hwp": "0°", "alice_basis": "0|90", "bob_basis": "0|90"},
        {"alice_hwp": "0°", "bob_hwp": "22.5°", "alice_basis": "0|90", "bob_basis": "-45|45"},
        {"alice_hwp": "22.5°", "bob_hwp": "0°", "alice_basis": "-45|45", "bob_basis": "0|90"},
        {"alice_hwp": "22.5°", "bob_hwp": "22.5°", "alice_basis": "-45|45", "bob_basis": "-45|45"},
    ]
    
    results = []
    shots_per_config = req.shots // 4
    
    for cfg in configs:
        counts = {"T&A": 0, "T&C": 0, "B&A": 0, "B&C": 0}
        for _ in range(shots_per_config):
            ev = _simulate_single_thorlabs_pair(cfg["alice_basis"], cfg["bob_basis"], req.error_rate)
            counts[ev["coincidence"]] += 1
            
        rates = {k: round(v / shots_per_config, 4) for k, v in counts.items()}
        results.append({
            "alice_hwp": cfg["alice_hwp"],
            "bob_hwp": cfg["bob_hwp"],
            "rates": rates,
            "counts": counts,
            "total_shots": shots_per_config
        })
        
    return {
        "configurations": results,
        "nominal_bit_error_rate": req.error_rate
    }

# Mount static files directly from project root
app.mount("/", StaticFiles(directory=BASE_DIR, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("qiskit_api:app", host="0.0.0.0", port=8000, reload=False)
