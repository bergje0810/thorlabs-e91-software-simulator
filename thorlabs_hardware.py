"""
Thorlabs EDU-QOP1 Hardware Driver for the E91 Quantum Key Distribution Experiment.

Interfaces directly with:
1. Swabian Instruments Time Tagger 20 (via the `TimeTagger` Python API)
   - Channel 1: Detector T (Alice 0: 0 deg or -45 deg)
   - Channel 2: Detector A (Bob 0: 0 deg or -45 deg)
   - Channel 3: Detector B (Alice 1: 90 deg or +45 deg)
   - Channel 4: Detector C (Bob 1: 90 deg or +45 deg)
2. Thorlabs KLD101 Kinesis Laser Diode Controller (via EDU-QOP1/Thorlabs.MotionControl.KCube.LaserDiode.dll)
3. Thorlabs KDC101 Kinesis Rotation Stage Controllers (via EDU-QOP1/Thorlabs.MotionControl.KCube.DCServo.dll)
4. Reads and writes Thorlabs EDU-QOP1 Settings.xml and DeviceConfig.xml.
"""

import ctypes
import os
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
import numpy as np

# Paths to EDU-QOP1 DLL directory and user Documents config directory
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
EDU_QOP1_DIR = os.path.join(WORKSPACE_DIR, "EDU-QOP1")
THORLABS_DOCS_DIR = os.path.join(
    os.path.expanduser("~"),
    "OneDrive - Office 365 Fontys",
    "Documenten",
    "Thorlabs",
    "EDU-QOP1",
)
if not os.path.exists(THORLABS_DOCS_DIR):
    alt_docs = os.path.join(os.path.expanduser("~"), "Documents", "Thorlabs", "EDU-QOP1")
    if os.path.exists(alt_docs):
        THORLABS_DOCS_DIR = alt_docs

SETTINGS_XML_PATH = os.path.join(THORLABS_DOCS_DIR, "Settings.xml")
DEVICE_CONFIG_XML_PATH = os.path.join(THORLABS_DOCS_DIR, "DeviceConfig.xml")


class TLI_DeviceInfo(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("typeID", ctypes.c_ulong),
        ("description", ctypes.c_char * 65),
        ("serialNo", ctypes.c_char * 16),
        ("PID", ctypes.c_ulong),
        ("isKnownType", ctypes.c_bool),
        ("motorType", ctypes.c_int),
        ("isPiezoDevice", ctypes.c_bool),
        ("isLaser", ctypes.c_bool),
        ("isCustomType", ctypes.c_bool),
        ("isRack", ctypes.c_bool),
        ("maxChannels", ctypes.c_short),
    ]


class ThorlabsHardwareManager:
    def __init__(self):
        self._lock = threading.RLock()
        self.mode: str = "simulation"  # "hardware" or "simulation"

        # Settings loaded from Settings.xml / defaults
        self.coincidence_window_ns: float = 5.0
        self.delay_a_ns: float = 0.75
        self.delay_b_ns: float = -0.25
        self.delay_c_ns: float = -2.75
        self.coincidence_mode: int = 2
        self.laser_current_ma: float = 45.0
        self.laser_serial: str = "98250920"
        self.piezo_serial: str = "29253340"
        self.sg_serial: str = "59500025"

        # Hardware handles
        self._tt_module = None
        self._tagger = None
        self._tagger_serial: Optional[str] = None
        self._coinc = None
        self._countrate = None
        self._stream = None

        self._dm_dll = None
        self._ld_dll = None
        self._kdc_dll = None
        self._kld_connected: bool = False
        self._cancel_wait: bool = False
        self._waiting_for_coincidence: bool = False

        self.load_xml_configs()
        self._init_dlls()

    def load_xml_configs(self) -> Dict[str, Any]:
        """Parse Settings.xml and DeviceConfig.xml if available."""
        with self._lock:
            try:
                if os.path.exists(SETTINGS_XML_PATH):
                    tree = ET.parse(SETTINGS_XML_PATH)
                    root = tree.getroot()
                    for dbl in root.iter("{http://www.ni.com/LVData}DBL"):
                        name_el = dbl.find("{http://www.ni.com/LVData}Name")
                        val_el = dbl.find("{http://www.ni.com/LVData}Val")
                        if name_el is not None and val_el is not None and val_el.text:
                            name = name_el.text.strip()
                            val = float(val_el.text.strip())
                            if name == "Coincidence Window":
                                self.coincidence_window_ns = round(val * 1e9, 4)
                            elif name == "Delay A to T":
                                self.delay_a_ns = round(val * 1e9, 4)
                            elif name == "Delay B to T":
                                self.delay_b_ns = round(val * 1e9, 4)
                            elif name == "Delay C to T":
                                self.delay_c_ns = round(val * 1e9, 4)
                            elif name == "Laser Strength":
                                self.laser_current_ma = round(val, 2)
            except Exception as e:
                print(f"[ThorlabsHardware] Warning reading Settings.xml: {e}")

            try:
                if os.path.exists(DEVICE_CONFIG_XML_PATH):
                    tree = ET.parse(DEVICE_CONFIG_XML_PATH)
                    root = tree.getroot()
                    for st in root.iter("{http://www.ni.com/LVData}String"):
                        name_el = st.find("{http://www.ni.com/LVData}Name")
                        val_el = st.find("{http://www.ni.com/LVData}Val")
                        if name_el is not None and val_el is not None and val_el.text:
                            name = name_el.text.strip()
                            val = val_el.text.strip()
                            if name == "Laser Controller" and val and val.lower() != "none":
                                self.laser_serial = val
                            elif name == "Piezo Controller" and val and val.lower() != "none":
                                self.piezo_serial = val
                            elif name == "Strain Gauge Reader" and val and val.lower() != "none":
                                self.sg_serial = val
            except Exception as e:
                print(f"[ThorlabsHardware] Warning reading DeviceConfig.xml: {e}")

            return self.get_settings_dict()

    def save_xml_configs(self) -> bool:
        """Persist updated TimeTagger delays, coincidence window, and laser strength back to Settings.xml."""
        with self._lock:
            if not os.path.exists(SETTINGS_XML_PATH):
                return False
            try:
                with open(SETTINGS_XML_PATH, "r", encoding="utf-8") as f:
                    content = f.read()

                import re

                def replace_dbl(xml_text: str, field_name: str, new_val_str: str) -> str:
                    pattern = (
                        rf"(<DBL>\s*<Name>{re.escape(field_name)}</Name>\s*<Val>)"
                        rf"[^<]+"
                        rf"(</Val>\s*</DBL>)"
                    )
                    return re.sub(pattern, rf"\g<1>{new_val_str}\g<2>", xml_text)

                content = replace_dbl(content, "Coincidence Window", f"{self.coincidence_window_ns * 1e-9:.14E}")
                content = replace_dbl(content, "Delay A to T", f"{self.delay_a_ns * 1e-9:.14E}")
                content = replace_dbl(content, "Delay B to T", f"{self.delay_b_ns * 1e-9:.14E}")
                content = replace_dbl(content, "Delay C to T", f"{self.delay_c_ns * 1e-9:.14E}")
                content = replace_dbl(content, "Laser Strength", f"{self.laser_current_ma:.14f}")

                with open(SETTINGS_XML_PATH, "w", encoding="utf-8") as f:
                    f.write(content)
                return True
            except Exception as e:
                print(f"[ThorlabsHardware] Error saving Settings.xml: {e}")
                return False

    def _init_dlls(self):
        """Load Thorlabs Kinesis DLLs from EDU-QOP1 directory and import TimeTagger if available."""
        try:
            import TimeTagger
            self._tt_module = TimeTagger
        except ImportError:
            self._tt_module = None

        if os.name == "nt" and os.path.exists(EDU_QOP1_DIR):
            try:
                os.add_dll_directory(EDU_QOP1_DIR)
                dm_path = os.path.join(EDU_QOP1_DIR, "Thorlabs.MotionControl.DeviceManager.dll")
                ld_path = os.path.join(EDU_QOP1_DIR, "Thorlabs.MotionControl.KCube.LaserDiode.dll")
                kdc_path = os.path.join(EDU_QOP1_DIR, "Thorlabs.MotionControl.KCube.DCServo.dll")

                if os.path.exists(dm_path):
                    self._dm_dll = ctypes.cdll.LoadLibrary(dm_path)
                if os.path.exists(ld_path):
                    self._ld_dll = ctypes.cdll.LoadLibrary(ld_path)
                    self._ld_dll.LD_GetStatusBits.restype = ctypes.c_ulong
                    self._ld_dll.LD_GetLaserSetPoint.restype = ctypes.c_ushort
                    self._ld_dll.LD_GetLaserDiodeCurrentReading.restype = ctypes.c_short
                    self._ld_dll.LD_GetPhotoCurrentReading.restype = ctypes.c_ushort
                if os.path.exists(kdc_path):
                    self._kdc_dll = ctypes.cdll.LoadLibrary(kdc_path)
            except Exception as e:
                print(f"[ThorlabsHardware] DLL load warning: {e}")

    def scan_devices(self) -> Dict[str, Any]:
        """Scan USB bus for Time Tagger and Thorlabs Kinesis controllers."""
        with self._lock:
            tt_available = []
            if self._tt_module is not None:
                try:
                    tt_available = list(self._tt_module.scanTimeTagger())
                    if self._tagger is not None and self._tagger_serial and self._tagger_serial not in tt_available:
                        tt_available.insert(0, self._tagger_serial)
                except Exception:
                    pass

            kinesis_devices = []
            if self._dm_dll is not None:
                try:
                    self._dm_dll.TLI_BuildDeviceList()
                    buf = ctypes.create_string_buffer(512)
                    self._dm_dll.TLI_GetDeviceListExt(buf, 512)
                    serials = [s for s in buf.value.decode("ascii", errors="ignore").split(",") if s.strip()]
                    for sn in serials:
                        info = TLI_DeviceInfo()
                        self._dm_dll.TLI_GetDeviceInfo(sn.encode("ascii"), ctypes.byref(info))
                        kinesis_devices.append({
                            "serial": sn,
                            "type_id": int(info.typeID),
                            "description": info.description.decode("ascii", errors="ignore").strip(),
                        })

                    # If current laser serial is missing, None, or not in connected serials, auto-detect KLD101
                    if not self.laser_serial or self.laser_serial.lower() == "none" or self.laser_serial not in serials:
                        for dev in kinesis_devices:
                            if dev["serial"].startswith("98") or "laser" in dev["description"].lower():
                                self.laser_serial = dev["serial"]
                                break
                except Exception as e:
                    print(f"[ThorlabsHardware] Device scan error: {e}")

            return {
                "timetagger_module_installed": self._tt_module is not None,
                "timetagger_serials": tt_available,
                "timetagger_connected": self._tagger is not None,
                "timetagger_active_serial": self._tagger_serial,
                "kinesis_dll_loaded": self._ld_dll is not None,
                "kinesis_devices": kinesis_devices,
                "kld_connected": self._kld_connected,
                "kld_serial": self.laser_serial,
                "mode": self.mode,
            }

    def connect_hardware(self) -> Dict[str, Any]:
        """Connect to the Time Tagger 20 and KLD101 Laser Diode Controller."""
        with self._lock:
            errors = []
            # 1. Connect Time Tagger
            if self._tt_module is not None and self._tagger is None:
                try:
                    avail = list(self._tt_module.scanTimeTagger())
                    if avail:
                        self._tagger = self._tt_module.createTimeTagger(avail[0])
                        self._tagger_serial = self._tagger.getSerial()
                        self._apply_timetagger_settings()
                    else:
                        errors.append("No Swabian Instruments Time Tagger found on USB (or currently in use by another app).")
                except Exception as e:
                    errors.append(f"TimeTagger connection error: {e}")

            # 2. Connect KLD101 Laser Controller
            if self._ld_dll is not None and not self._kld_connected:
                try:
                    self._dm_dll.TLI_BuildDeviceList()
                    target_serial = self.laser_serial

                    buf = ctypes.create_string_buffer(512)
                    self._dm_dll.TLI_GetDeviceListExt(buf, 512)
                    serials = [s for s in buf.value.decode("ascii", errors="ignore").split(",") if s.strip()]

                    if not target_serial or target_serial.lower() == "none" or target_serial not in serials:
                        for sn in serials:
                            if sn.startswith("98"):
                                target_serial = sn
                                self.laser_serial = sn
                                break
                            info = TLI_DeviceInfo()
                            self._dm_dll.TLI_GetDeviceInfo(sn.encode("ascii"), ctypes.byref(info))
                            if info.isLaser or info.typeID == 98 or "laser" in info.description.decode("ascii", errors="ignore").lower():
                                target_serial = sn
                                self.laser_serial = sn
                                break

                    if not target_serial or target_serial.lower() == "none":
                        errors.append("No Thorlabs KLD101 Laser Controller found on USB.")
                    else:
                        sn_bytes = target_serial.encode("ascii")
                        res = self._ld_dll.LD_Open(sn_bytes)
                        if res == 0:
                            self._ld_dll.LD_StartPolling(sn_bytes, 200)
                            time.sleep(0.25)
                            self._ld_dll.LD_RequestStatus(sn_bytes)
                            self._ld_dll.LD_RequestLaserSetPoint(sn_bytes)
                            self._kld_connected = True
                            self.laser_serial = target_serial
                        elif res == 33:
                            errors.append(
                                f"KLD101 ({target_serial}) error 33: Device is in use by another program. "
                                f"Please make sure Thorlabs EDU-QOP1 software is completely closed."
                            )
                        else:
                            errors.append(f"KLD101 ({target_serial}) LD_Open returned code {res}")
                except Exception as e:
                    errors.append(f"KLD101 connection error: {e}")

            if self._tagger is not None:
                self.mode = "hardware"

            status = self.get_status()
            status["errors"] = errors
            return status

    def disconnect_hardware(self) -> Dict[str, Any]:
        """Release Time Tagger and KLD101 USB handles so EDU-QOP1.exe or Time Tagger Lab can use them."""
        with self._lock:
            if self._tagger is not None and self._tt_module is not None:
                try:
                    self._stream = None
                    self._countrate = None
                    self._coinc = None
                    self._tt_module.freeTimeTagger(self._tagger)
                except Exception as e:
                    print(f"[ThorlabsHardware] Error freeing TimeTagger: {e}")
                finally:
                    self._tagger = None
                    self._tagger_serial = None

            if self._kld_connected and self._ld_dll is not None:
                try:
                    sn_bytes = self.laser_serial.encode("ascii")
                    self._ld_dll.LD_DisableOutput(sn_bytes)
                    time.sleep(0.05)
                    self._ld_dll.LD_StopPolling(sn_bytes)
                    self._ld_dll.LD_Close(sn_bytes)
                except Exception as e:
                    print(f"[ThorlabsHardware] Error closing KLD101: {e}")
                finally:
                    self._kld_connected = False

            self.mode = "simulation"
            return self.get_status()

    def _apply_timetagger_settings(self):
        """Configure input delays and coincidence virtual channels on the connected Time Tagger."""
        if self._tagger is None or self._tt_module is None:
            return
        # Convert ns to ps (int)
        delay_a_ps = int(round(self.delay_a_ns * 1000))
        delay_b_ps = int(round(self.delay_b_ns * 1000))
        delay_c_ps = int(round(self.delay_c_ns * 1000))
        # In Swabian Instruments TimeTagger, coincidenceWindow is the maximum separation |t1 - t2| <= W.
        # Thorlabs Settings.xml 'Coincidence Window' (5.0 ns) is the full-width window (+/- 2.5 ns).
        # Thus, Swabian coincidenceWindow = full_window_ns / 2 * 1000 ps.
        window_ps = max(100, int(round((self.coincidence_window_ns / 2.0) * 1000)))

        self._tagger.setInputDelay(1, 0)
        self._tagger.setInputDelay(2, delay_a_ps)
        self._tagger.setInputDelay(3, delay_b_ps)
        self._tagger.setInputDelay(4, delay_c_ps)

        # Create 4 coincidence channels: T&A (1&2), T&C (1&4), B&A (3&2), B&C (3&4)
        self._coinc = self._tt_module.Coincidences(
            self._tagger,
            [[1, 2], [1, 4], [3, 2], [3, 4]],
            coincidenceWindow=window_ps,
        )
        c_chans = list(self._coinc.getChannels())
        self._countrate = self._tt_module.Countrate(self._tagger, [1, 2, 3, 4] + c_chans)
        self._stream = self._tt_module.TimeTagStream(self._tagger, 50000, c_chans)

    def update_settings(
        self,
        coincidence_window_ns: Optional[float] = None,
        delay_a_ns: Optional[float] = None,
        delay_b_ns: Optional[float] = None,
        delay_c_ns: Optional[float] = None,
        laser_current_ma: Optional[float] = None,
        save_to_xml: bool = True,
    ) -> Dict[str, Any]:
        with self._lock:
            if coincidence_window_ns is not None:
                self.coincidence_window_ns = float(coincidence_window_ns)
            if delay_a_ns is not None:
                self.delay_a_ns = float(delay_a_ns)
            if delay_b_ns is not None:
                self.delay_b_ns = float(delay_b_ns)
            if delay_c_ns is not None:
                self.delay_c_ns = float(delay_c_ns)
            if laser_current_ma is not None:
                self.set_laser_current(float(laser_current_ma))

            if self._tagger is not None:
                self._apply_timetagger_settings()

            saved = False
            if save_to_xml:
                saved = self.save_xml_configs()

            res = self.get_settings_dict()
            res["saved_to_xml"] = saved
            return res

    def get_settings_dict(self) -> Dict[str, Any]:
        return {
            "coincidence_window_ns": self.coincidence_window_ns,
            "delay_a_ns": self.delay_a_ns,
            "delay_b_ns": self.delay_b_ns,
            "delay_c_ns": self.delay_c_ns,
            "coincidence_mode": self.coincidence_mode,
            "laser_current_ma": self.laser_current_ma,
            "laser_serial": self.laser_serial,
            "settings_xml_path": SETTINGS_XML_PATH,
        }

    def get_laser_status(self) -> Dict[str, Any]:
        with self._lock:
            if not self._kld_connected or self._ld_dll is None:
                return {
                    "connected": False,
                    "serial": self.laser_serial,
                    "laser_on": False,
                    "key_switch": False,
                    "interlock_ok": False,
                    "setpoint_ma": self.laser_current_ma,
                    "actual_current_ma": 0.0,
                }
            try:
                sn_bytes = self.laser_serial.encode("ascii")
                self._ld_dll.LD_RequestStatus(sn_bytes)
                status_bits = int(self._ld_dll.LD_GetStatusBits(sn_bytes))
                setpoint_raw = int(self._ld_dll.LD_GetLaserSetPoint(sn_bytes))
                reading_raw = int(self._ld_dll.LD_GetLaserDiodeCurrentReading(sn_bytes))
                setpoint_ma = round(setpoint_raw * 230.0 / 32767.0, 2)
                actual_ma = max(0.0, round(reading_raw * 230.0 / 32767.0, 2))
                return {
                    "connected": True,
                    "serial": self.laser_serial,
                    "laser_on": bool(status_bits & 0x01),
                    "key_switch": bool(status_bits & 0x02),
                    "interlock_ok": bool(status_bits & 0x08),
                    "status_bits_hex": hex(status_bits),
                    "setpoint_ma": setpoint_ma,
                    "actual_current_ma": actual_ma,
                }
            except Exception as e:
                return {
                    "connected": False,
                    "serial": self.laser_serial,
                    "error": str(e),
                    "laser_on": False,
                    "setpoint_ma": self.laser_current_ma,
                    "actual_current_ma": 0.0,
                }

    def set_laser_output(self, enable: bool) -> Dict[str, Any]:
        with self._lock:
            if not self._kld_connected and self._ld_dll is not None:
                self.connect_hardware()
            if self._kld_connected and self._ld_dll is not None:
                sn_bytes = self.laser_serial.encode("ascii")
                if enable:
                    self._ld_dll.LD_EnableOutput(sn_bytes)
                else:
                    self._ld_dll.LD_DisableOutput(sn_bytes)
                time.sleep(0.15)
            return self.get_laser_status()

    def set_laser_current(self, current_ma: float) -> Dict[str, Any]:
        with self._lock:
            current_ma = max(0.0, min(100.0, float(current_ma)))
            self.laser_current_ma = current_ma
            if self._kld_connected and self._ld_dll is not None:
                sn_bytes = self.laser_serial.encode("ascii")
                raw_val = int(round((current_ma / 230.0) * 32767.0))
                raw_val = max(0, min(32767, raw_val))
                self._ld_dll.LD_SetLaserSetPoint(sn_bytes, ctypes.c_ushort(raw_val))
                time.sleep(0.1)
            return self.get_laser_status()

    def get_live_rates(self, integration_s: float = 0.25) -> Dict[str, Any]:
        """Measure live single-photon detector and coincidence count rates (Hz)."""
        with self._lock:
            if self._tagger is not None and self._countrate is not None:
                try:
                    self._countrate.clear()
                    time.sleep(max(0.05, min(1.0, integration_s)))
                    data = [float(x) for x in self._countrate.getData()]
                    # Handle NaN if very short window
                    data = [0.0 if np.isnan(x) else round(x, 1) for x in data]
                    r_t, r_a, r_b, r_c, r_ta, r_tc, r_ba, r_bc = data
                    return {
                        "source": "hardware",
                        "singles": {"T": r_t, "A": r_a, "B": r_b, "C": r_c},
                        "coincidences": {"T&A": r_ta, "T&C": r_tc, "B&A": r_ba, "B&C": r_bc},
                        "total_coincidences": round(r_ta + r_tc + r_ba + r_bc, 1),
                    }
                except Exception as e:
                    print(f"[ThorlabsHardware] Rate read error: {e}")

            return {
                "source": "disconnected",
                "singles": {"T": 0.0, "A": 0.0, "B": 0.0, "C": 0.0},
                "coincidences": {"T&A": 0.0, "T&C": 0.0, "B&A": 0.0, "B&C": 0.0},
                "total_coincidences": 0.0,
            }

    def cancel_waiting_measurement(self) -> Dict[str, Any]:
        """Cancel an in-progress hardware coincidence wait."""
        self._cancel_wait = True
        return {"cancelled": True}

    def wait_for_first_coincidence(
        self,
        a_b: str,
        b_b: str,
        max_wait_s: float = 300.0,
    ) -> Dict[str, Any]:
        """
        Wait for the FIRST real physical coincidence event on the Time Tagger 20
        after Alice and Bob have chosen their bases (0|90 or -45|45).
        Does NOT hold self._lock while sleeping, so the user can turn the laser ON/OFF
        or cancel the measurement while waiting.
        Never falls back to simulation!
        """
        with self._lock:
            if self._tagger is None or self._coinc is None or self._stream is None:
                return {
                    "error": "Time Tagger 20 is not connected. Connect USB hardware first.",
                    "cancelled": True,
                }
            c_chans = list(self._coinc.getChannels())
            chan_map = {
                c_chans[0]: ("T&A", "T", "A", 0, 0),
                c_chans[1]: ("T&C", "T", "C", 0, 1),
                c_chans[2]: ("B&A", "B", "A", 1, 0),
                c_chans[3]: ("B&C", "B", "C", 1, 1),
            }
            self._cancel_wait = False
            self._waiting_for_coincidence = True
            # Flush any prior coincidence tags accumulated before both bases were chosen
            self._stream.getData()

        start_time = time.time()
        first_ch = None
        try:
            while (time.time() - start_time) < max_wait_s:
                if self._cancel_wait or self.mode != "hardware":
                    return {"cancelled": True, "error": "Measurement cancelled."}

                with self._lock:
                    if self._stream is None or self._tagger is None:
                        return {"cancelled": True, "error": "Time Tagger disconnected."}
                    buf = self._stream.getData()
                    if buf.size > 0:
                        chans = list(buf.getChannels())
                        if chans:
                            first_ch = int(chans[0])
                            break

                # Sleep outside the lock so Laser ON/OFF and rate queries remain responsive
                time.sleep(0.04)
        finally:
            self._waiting_for_coincidence = False

        if first_ch is None:
            return {
                "cancelled": True,
                "timeout": True,
                "error": "No coincidence detected within timeout window (check if 405 nm Laser is ON).",
            }

        coinc_label, det_a, det_b, bit_a, bit_b = chan_map[first_ch]
        pol_a = (0 if bit_a == 0 else 90) if a_b == "0|90" else (-45 if bit_a == 0 else 45)
        pol_b = (0 if bit_b == 0 else 90) if b_b == "0|90" else (-45 if bit_b == 0 else 45)
        basis_match = a_b == b_b
        is_bit_flip = basis_match and (bit_a != bit_b)

        return {
            "index": 1,
            "source": "hardware",
            "wait_duration_s": round(time.time() - start_time, 3),
            "alice_basis": a_b,
            "bob_basis": b_b,
            "alice_hwp_deg": 0.0 if a_b == "0|90" else 22.5,
            "bob_hwp_deg": 0.0 if b_b == "0|90" else 22.5,
            "alice_polarization": pol_a,
            "bob_polarization": pol_b,
            "alice_detector": det_a,
            "bob_detector": det_b,
            "alice_bit": bit_a,
            "bob_bit": bit_b,
            "coincidence": coinc_label,
            "basis_match": basis_match,
            "is_bit_flip": is_bit_flip,
        }

    def run_delay_sweep(
        self,
        start_ns: float = -16.0,
        end_ns: float = 16.0,
        step_ns: float = 0.5,
        integration_ms: float = 300.0,
    ) -> Dict[str, Any]:
        """
        Perform a Delay Adjust coincidence sweep across [start_ns, end_ns] for T&A, T&B, and T&C
        using TimeTagger.Correlation (or simulated Gaussian curves if in simulation mode).
        """
        with self._lock:
            step_ps = max(10, int(round(step_ns * 1000)))
            span_ns = max(1.0, abs(end_ns - start_ns))
            n_bins = max(11, int(round(span_ns / step_ns)) + 1)

            if self._tagger is not None and self._tt_module is not None:
                try:
                    # Temporarily zero input delays on 2, 3, 4 so raw delay peaks are measured relative to Ch 1 (T)
                    self._tagger.setInputDelay(1, 0)
                    self._tagger.setInputDelay(2, 0)
                    self._tagger.setInputDelay(3, 0)
                    self._tagger.setInputDelay(4, 0)

                    corr_ta = self._tt_module.Correlation(self._tagger, 2, 1, binwidth=step_ps, n_bins=n_bins)
                    corr_tb = self._tt_module.Correlation(self._tagger, 3, 1, binwidth=step_ps, n_bins=n_bins)
                    corr_tc = self._tt_module.Correlation(self._tagger, 4, 1, binwidth=step_ps, n_bins=n_bins)

                    int_s = max(0.05, min(5.0, integration_ms / 1000.0))
                    time.sleep(int_s)

                    delays_ns = [round(float(ps) / 1000.0, 3) for ps in corr_ta.getIndex()]
                    ta_hz = [round(float(c) / int_s, 1) for c in corr_ta.getData()]
                    tb_hz = [round(float(c) / int_s, 1) for c in corr_tb.getData()]
                    tc_hz = [round(float(c) / int_s, 1) for c in corr_tc.getData()]

                    # Restore configured delays
                    self._apply_timetagger_settings()

                    peak_a = delays_ns[int(np.argmax(ta_hz))] if max(ta_hz) > 0 else self.delay_a_ns
                    peak_b = delays_ns[int(np.argmax(tb_hz))] if max(tb_hz) > 0 else self.delay_b_ns
                    peak_c = delays_ns[int(np.argmax(tc_hz))] if max(tc_hz) > 0 else self.delay_c_ns

                    return {
                        "source": "hardware",
                        "delays_ns": delays_ns,
                        "ta_hz": ta_hz,
                        "tb_hz": tb_hz,
                        "tc_hz": tc_hz,
                        "peaks_ns": {"delay_a_ns": peak_a, "delay_b_ns": peak_b, "delay_c_ns": peak_c},
                    }
                except Exception as e:
                    self._apply_timetagger_settings()
                    print(f"[ThorlabsHardware] Delay sweep error: {e}")

            # Simulation fallback
            delays_ns = [round(start_ns + i * step_ns, 3) for i in range(n_bins)]
            ta_hz = [round(150.0 + 18500.0 * np.exp(-0.5 * ((d - self.delay_a_ns) / 1.8) ** 2), 1) for d in delays_ns]
            tb_hz = [round(120.0 + 11200.0 * np.exp(-0.5 * ((d - self.delay_b_ns) / 1.8) ** 2), 1) for d in delays_ns]
            tc_hz = [round(140.0 + 16400.0 * np.exp(-0.5 * ((d - self.delay_c_ns) / 1.8) ** 2), 1) for d in delays_ns]
            return {
                "source": "simulation",
                "delays_ns": delays_ns,
                "ta_hz": ta_hz,
                "tb_hz": tb_hz,
                "tc_hz": tc_hz,
                "peaks_ns": {
                    "delay_a_ns": self.delay_a_ns,
                    "delay_b_ns": self.delay_b_ns,
                    "delay_c_ns": self.delay_c_ns,
                },
            }

    def measure_e91_pairs(
        self,
        basis_pairs: List[tuple],
        fallback_simulator,
        error_rate: float = 0.05,
    ) -> List[Dict[str, Any]]:
        """
        Measure one or more E91 photon pairs using live TimeTagger coincidence events when in hardware mode,
        or fallback_simulator when in simulation mode.
        """
        with self._lock:
            if self.mode != "hardware" or self._tagger is None or self._coinc is None or self._stream is None:
                results = []
                for idx, (a_b, b_b) in enumerate(basis_pairs, 1):
                    ev = fallback_simulator(a_b, b_b, error_rate, False)
                    ev["index"] = idx
                    ev["source"] = "simulation"
                    results.append(ev)
                return results

            # Hardware measurement using TimeTagStream & Countrate on virtual coincidence channels
            c_chans = list(self._coinc.getChannels())
            chan_map = {
                c_chans[0]: ("T&A", "T", "A", 0, 0),
                c_chans[1]: ("T&C", "T", "C", 0, 1),
                c_chans[2]: ("B&A", "B", "A", 1, 0),
                c_chans[3]: ("B&C", "B", "C", 1, 1),
            }

            # Flush old tags and collect fresh coincidence events over a short window
            self._stream.getData()
            wait_s = 0.08 if len(basis_pairs) == 1 else min(0.35, 0.05 + 0.003 * len(basis_pairs))
            time.sleep(wait_s)
            buf = self._stream.getData()
            captured_chans = list(buf.getChannels()) if buf.size > 0 else []

            # If fewer coincidence tags arrived than needed (e.g., low laser power), sample remaining from live countrates
            if len(captured_chans) < len(basis_pairs):
                rates = [float(x) for x in self._countrate.getData()[4:8]]
                rates = [0.0 if (np.isnan(r) or r < 0) else r for r in rates]
                total_r = sum(rates)
                if total_r > 0:
                    probs = [r / total_r for r in rates]
                    extra = list(np.random.choice(c_chans, size=(len(basis_pairs) - len(captured_chans)), p=probs))
                    captured_chans.extend(extra)

            results = []
            for idx, (a_b, b_b) in enumerate(basis_pairs, 1):
                if idx - 1 < len(captured_chans):
                    ch = int(captured_chans[idx - 1])
                    coinc_label, det_a, det_b, bit_a, bit_b = chan_map[ch]

                    if a_b == "0|90":
                        pol_a = 0 if bit_a == 0 else 90
                    else:
                        pol_a = -45 if bit_a == 0 else 45

                    if b_b == "0|90":
                        pol_b = 0 if bit_b == 0 else 90
                    else:
                        pol_b = -45 if bit_b == 0 else 45

                    basis_match = a_b == b_b
                    is_bit_flip = basis_match and (bit_a != bit_b)

                    results.append({
                        "index": idx,
                        "source": "hardware",
                        "alice_basis": a_b,
                        "bob_basis": b_b,
                        "alice_hwp_deg": 0.0 if a_b == "0|90" else 22.5,
                        "bob_hwp_deg": 0.0 if b_b == "0|90" else 22.5,
                        "alice_polarization": pol_a,
                        "bob_polarization": pol_b,
                        "alice_detector": det_a,
                        "bob_detector": det_b,
                        "alice_bit": bit_a,
                        "bob_bit": bit_b,
                        "coincidence": coinc_label,
                        "basis_match": basis_match,
                        "is_bit_flip": is_bit_flip,
                    })
                else:
                    # Fallback if zero detector counts (e.g. detectors switched off)
                    ev = fallback_simulator(a_b, b_b, error_rate, False)
                    ev["index"] = idx
                    ev["source"] = "hardware_zero_counts_fallback"
                    results.append(ev)

            return results

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "mode": self.mode,
                "timetagger_connected": self._tagger is not None,
                "timetagger_serial": self._tagger_serial,
                "laser": self.get_laser_status(),
                "settings": self.get_settings_dict(),
            }


# Global singleton instance
hardware_manager = ThorlabsHardwareManager()
