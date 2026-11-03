# Thorlabs EDU-QOP1 & EDU-QOPA1 — E91 QKD Simulator

An interactive quantum optics laboratory simulator and hardware interface for Artur Ekert's 1991 Bell-inequality Quantum Key Distribution (E91) protocol, modeled directly after **Thorlabs EDU-QOP1(/M) & EDU-QOPA1(/M)** Experiment 25.4.

---

## Features

1. **Top-Down Animated Optical Bench (Fig 242)**:
   - SPDC Bell state source: 405 nm violet diode laser pumping crossed BBO crystals producing $|\psi^+\rangle = \frac{1}{\sqrt{2}}(|HH\rangle + |VV\rangle)$ at 810 nm.
   - Alice (Left): Rotatable Half-Wave Plate ($0^\circ$ or $22.5^\circ$), PBS cube, Detectors T (Bit 0) & B (Bit 1).
   - Bob (Right): Rotatable Half-Wave Plate ($0^\circ$ or $22.5^\circ$), PBS cube, Detectors A (Bit 0) & C (Bit 1).
   - Real-time photon wavepacket dynamics, detector clicks, and coincidence tagging.

2. **Game-Style Interactive Spotlight Tutorial (Simulation Only)**:
   - Floating HUD walkthrough that points directly at optical bench elements and software controls with a glowing spotlight.
   - Interactive action buttons per step (emit pair, randomize bases, measure 75 pairs, sift, extract key, encrypt, decrypt).
   - Automatically hidden when connected to real hardware.

3. **Dual Software Interface (Section 26.2)**:
   - Dual View, Alice View, Bob View, and Dual-Screen Pop-Out across multiple displays via `BroadcastChannel`.
   - Full keyboard shortcuts (`F1` through `F12`, `Space` to emit, `Esc` to close tour).
   - One-Time Pad Vernam bitwise XOR encryption and decryption.

4. **Thorlabs Hardware Control (KLD101 & Swabian Time Tagger 20)**:
   - Direct USB integration with Thorlabs KLD101 Laser Controller (405 nm pump diode) and Swabian Instruments Time Tagger 20.
   - Live 4-channel count rate monitoring and coincidence detection.
   - Automatic laser shutoff on mode switch and USB disconnect.

---

## Quickstart

### 1. Requirements
```bash
pip install -r requirements.txt
```

### 2. Run Tests
```bash
python -m pytest
```

### 3. Start Application
```bash
python server.py
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser.

---

## Hotkeys

| Key | Action | Physical Function |
| :--- | :--- | :--- |
| **Space** | Emit Single Pair | Emits one entangled photon pair |
| **F1** | `0°\|90°` (HV Basis) | Sets analyzer HWP to $0^\circ$ |
| **F2** | `-45°\|45°` (Diagonal Basis) | Sets analyzer HWP to $22.5^\circ$ |
| **F3** | Filter by Bases | Public channel basis reconciliation (sifting) |
| **F4** | Calculate Key | Extracts key from matching events |
| **F5** | Encrypt Msg | Bitwise XOR ($\text{Message} \oplus \text{Key}$) |
| **F6** | Send Message | Transmits ciphertext over public channel |
| **F7** | Decrypt Msg | Bitwise XOR ($\text{Ciphertext} \oplus \text{BobKey}$) |
| **F9** | Clear Last | Removes last coincidence point |
| **F10** | Clear All | Resets experiment state |
| **F12** | Yield Control | Toggles control turn between Alice and Bob |
| **Esc** | Close Guide | Dismisses interactive spotlight tour |
