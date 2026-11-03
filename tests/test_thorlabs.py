import pytest
from fastapi.testclient import TestClient
import server

client = TestClient(server.app)

def test_thorlabs_step_same_basis():
    # Both in HV basis
    res = client.post("/api/thorlabs/step", json={"alice_basis": "0|90", "bob_basis": "0|90", "error_rate": 0.0})
    assert res.status_code == 200
    data = res.json()
    assert data["basis_match"] is True
    assert data["alice_bit"] == data["bob_bit"]
    assert data["alice_detector"] in ("T", "B")
    assert data["bob_detector"] in ("A", "C")
    assert data["alice_polarization"] in (0, 90)
    assert data["bob_polarization"] in (0, 90)
    if data["alice_bit"] == 0:
        assert data["alice_detector"] == "T"
        assert data["bob_detector"] == "A"
        assert data["coincidence"] == "T&A"
    else:
        assert data["alice_detector"] == "B"
        assert data["bob_detector"] == "C"
        assert data["coincidence"] == "B&C"

def test_thorlabs_step_diagonal_basis():
    # Both in diagonal basis
    res = client.post("/api/thorlabs/step", json={"alice_basis": "-45|45", "bob_basis": "-45|45", "error_rate": 0.0})
    assert res.status_code == 200
    data = res.json()
    assert data["basis_match"] is True
    assert data["alice_bit"] == data["bob_bit"]
    assert data["alice_polarization"] in (-45, 45)
    assert data["bob_polarization"] in (-45, 45)

def test_thorlabs_step_different_basis():
    # One HV, one diagonal
    res = client.post("/api/thorlabs/step", json={"alice_basis": "0|90", "bob_basis": "-45|45"})
    assert res.status_code == 200
    data = res.json()
    assert data["basis_match"] is False
    assert data["alice_polarization"] in (0, 90)
    assert data["bob_polarization"] in (-45, 45)

def test_thorlabs_batch():
    res = client.post("/api/thorlabs/batch", json={"count": 75, "error_rate": 0.05})
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 75
    assert len(data["events"]) == 75
    assert data["matching_count"] > 0
    assert len(data["raw_key_alice"]) == data["matching_count"]
    assert len(data["raw_key_bob"]) == data["matching_count"]

def test_thorlabs_coincidence_rates():
    res = client.post("/api/thorlabs/coincidence_rates", json={"shots": 2000, "error_rate": 0.05})
    assert res.status_code == 200
    data = res.json()
    assert len(data["configurations"]) == 4
    
    # 0° / 0° (HV / HV)
    cfg00 = data["configurations"][0]
    assert cfg00["rates"]["T&A"] > 0.35
    assert cfg00["rates"]["B&C"] > 0.35
    assert cfg00["rates"]["T&C"] < 0.12
    assert cfg00["rates"]["B&A"] < 0.12
    
    # 0° / 22.5° (HV / Diag)
    cfg01 = data["configurations"][1]
    for rate in cfg01["rates"].values():
        assert 0.15 <= rate <= 0.35

def test_hardware_endpoints_and_ui():
    res_status = client.get("/api/hardware/status")
    assert res_status.status_code == 200
    status_data = res_status.json()
    assert "timetagger_connected" in status_data
    assert "laser" in status_data
    assert "settings" in status_data

    res_rates = client.get("/api/hardware/rates?integration_s=0.05")
    assert res_rates.status_code == 200
    rates_data = res_rates.json()
    assert "singles" in rates_data
    assert "coincidences" in rates_data
    for ch in ("T", "A", "B", "C"):
        assert ch in rates_data["singles"]

    res_html = client.get("/")
    assert res_html.status_code == 200
    html = res_html.text
    assert "hardwareSetupSection" in html
    assert "aliceEncryptedText" in html
    assert "bobDecryptedText" in html
    assert "clearLastPoint" in html
    assert "yKeyBit" in html
