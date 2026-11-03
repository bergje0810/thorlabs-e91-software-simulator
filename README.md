# Thorlabs EDU-QOP1(/M) & EDU-QOPA1(/M) — Experiment 25.4 E91 Simulator

An interactive, educational quantum optics learning environment for **Artur Ekert's 1991 Bell-inequality-based Quantum Key Distribution (E91) protocol**, specifically modeling the **Thorlabs "EDU-QOP1(/M) and EDU-QOPA1(/M) Quantum Optics Kit and Polarization-Entanglement Extension Kit" Experiment 25.4** and **Section 26.2 (E91 QKD Tab)**.

---

## Key Features

1. **Top-Down Animated Optical Bench (Figure 242)**:
   - High-fidelity visual simulation of the physical optical breadboard.
   - **Central SPDC Source**: 405 nm violet diode pump laser pumping crossed BBO crystals to produce paired 810 nm entangled photons in Bell state $|\psi^+\rangle = \frac{1}{\sqrt{2}}(|HH\rangle + |VV\rangle)$.
   - **Alice's Arm (Left)**: Rotatable Half-Wave Plate (0° or 22.5°), Polarizing Beamsplitter (PBS), and Detectors **T** (Transmission, Bit 0) & **B** (Reflection, Bit 1).
   - **Bob's Arm (Right)**: Rotatable Half-Wave Plate (0° or 22.5°), Polarizing Beamsplitter (PBS), and Detectors **A** (Transmission, Bit 0) & **C** (Reflection, Bit 1).
   - **Real-Time Photon Dynamics**: Individual photon wavepackets with polarization direction vectors travel through the waveplates and split at the PBS cubes into the detectors.
   - **Detector Click Sparks & Coincidence Tagger**: Visual pulse ripples and coincidence unit readout (e.g. `T&A`, `B&C`, `T&C`, `B&A`).
   - Interactive components: Click directly on Alice's or Bob's HWP in the canvas to rotate them!

2. **Interactive 8-Step Educational Learning Guide**:
   - Step 1: The Quantum Source & Detectors (SPDC and Bell state physics).
   - Step 2: Message Encoding (5-bit alphabet representation from Thorlabs manual Fig 248: "photon" = 30 bits).
   - Step 3: Basis Selection (HWP at 0° [F1] vs 22.5° [F2]).
   - Step 4: Coincidence Measurements (Simulating 75 pairs as in Fig 246).
   - Step 5: Public Basis Reconciliation / Sifting [F3].
   - Step 6: Extracting Key & Observing Physical ~5% Bit Flips (data point #10 in Fig 247).
   - Step 7: One-Time Pad Encryption via Bitwise XOR [F5].
   - Step 8: Public Channel Transmission & Decryption [F6 & F7] (reproducing "phpton" on bit flips as in Fig 250).

3. **Thorlabs Dual Software Interface (Section 26.2)**:
   - Replicates the official software windows with side-by-side or single-party view.
   - Full keyboard hotkeys (`F1` to `F12`) with turn yielding (`F12`).
   - Dual-screen pop-out support across multiple monitors using `BroadcastChannel`.
   - Table 25.4.3 coincidence rate matrix monitoring.

4. **Quantum Backend**:
   - Powered by Qiskit AerSimulator and FastAPI.

---

## Quickstart

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Test Suite
```bash
python -m pytest
```

### 3. Start the Server
```bash
python qiskit_api.py
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser.

---

## Keyboard Hotkeys Reference (Section 26.2)

| Key | Action | Physical Meaning |
| :--- | :--- | :--- |
| **F1** | `0°\|90°` (HV Basis) | Sets analyzer HWP to 0° |
| **F2** | `-45°\|45°` (Diagonal Basis) | Sets analyzer HWP to 22.5° |
| **F3** | `Filter by Bases` | Basis reconciliation (sifting) |
| **F4** | `Calculate Key` | Key extraction from matching events |
| **F5** | `Encrypt Msg` | Bitwise XOR ($\text{Message} \oplus \text{Key}$) |
| **F6** | `Send Message` | Public channel transmission |
| **F7** | `Decrypt Msg` | Bitwise XOR ($\text{Ciphertext} \oplus \text{BobKey}$) |
| **F12** | `Yield Control` | Switches control focus between Alice and Bob |
