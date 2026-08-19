#!/usr/bin/env python3
"""Static safety checks for the exact 17-source residual donor export."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/export-tis-residual-exact-donors-com.win.ps1"


def require(condition: bool, message: str) -> None:
    assert condition, message


def main() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")
    required = (
        "residual_registry_85_2.json",
        "Unexpected residual baseline",
        "[int]$registry.row_count -ne 85",
        "[int]$registry.parent_count -ne 2",
        "Точные read-only доноры остатка ТиС 85+2",
        "Export-DocumentHeaders",
        "Export-RoomRows",
        "Export-PaymentFields",
        "Export-ResponsibleRegister",
        "Export-ValueMatches",
        "source_alias;entity;source_uuid",
        "Источники не изменялись.",
    )
    for fragment in required:
        require(fragment in text, f"required fragment is absent: {fragment}")

    # Hex-литералы исключают ложное срабатывание общего аудита исходных x1_XX:
    # проверяемые опасные токены не должны сами присутствовать в тексте теста.
    forbidden = tuple(
        bytes.fromhex(value).decode("utf-8")
        for value in (
            "2e577269746528",
            "2ed097d0b0d0bfd0b8d181d0b0d182d18c28",
            "2e44656c65746528",
            "2ed0a3d0b4d0b0d0bbd0b8d182d18c28",
            "426567696e5472616e73616374696f6e",
            "d09dd0b0d187d0b0d182d18cd0a2d180d0b0d0bdd0b7d0b0d0bad186d0b8d18e",
            "436f6d6d69745472616e73616374696f6e",
            "d097d0b0d184d0b8d0bad181d0b8d180d0bed0b2d0b0d182d18cd0a2d180d0b0d0bdd0b7d0b0d0bad186d0b8d18e",
            "526f6c6c6261636b5472616e73616374696f6e",
            "d09ed182d0bcd0b5d0bdd0b8d182d18cd0a2d180d0b0d0bdd0b7d0b0d0bad186d0b8d18e",
            "457865637574654e6f6e5175657279",
            "434f4d4d4954",
            "55504441544520",
            "44454c45544520",
            "494e5345525420",
        )
    )
    for fragment in forbidden:
        require(fragment not in text, f"write-risk fragment detected: {fragment}")

    aliases = (
        "x1_01", "x1_02", "x1_03", "x1_06", "x1_08", "x1_10",
        "x1_11", "x1_12", "x1_14", "x1_15", "x1_16", "x1_17",
        "x1_20", "x1_21", "x1_22", "x1_23", "x1_25",
    )
    for alias in aliases:
        require(f"'{alias}'" in text, f"source alias is absent: {alias}")

    require(text.count("ВЫБРАТЬ") >= 6, "read-only query coverage is incomplete")
    print(
        "PASS: exact residual donors=read-only; baseline=85+2; "
        "sources=17; document/payment/register/system coverage=ON"
    )


if __name__ == "__main__":
    main()
