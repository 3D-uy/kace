"""Phase 0/1 BoardContract catalog, security, and shadow-mode tests."""

from __future__ import annotations

from copy import deepcopy
import glob
import json
import os
import unittest

import yaml

from firmware.boards.catalog import (
    BoardCatalog,
    BoardCatalogError,
    CatalogEntry,
    load_default_catalog,
)
from firmware.boards.models import (
    BoardContract,
    BoardContractError,
    compute_contract_digest,
)
from firmware.boards.resolver import (
    BoardResolver,
    ResolutionStatus,
    ShadowDivergence,
    capture_shadow_comparison,
    compare_legacy_resolution,
)
from firmware.boards.upstream import (
    load_klipper_source_contract,
    sha256_lf,
)


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONTRACT_DIR = os.path.join(ROOT, "data", "board_contracts", "v1")
SCHEMA_PATH = os.path.join(ROOT, "data", "board_contracts.schema.json")


def _payloads():
    result = []
    for path in sorted(glob.glob(os.path.join(CONTRACT_DIR, "*.yaml"))):
        with open(path, "r", encoding="utf-8") as source:
            result.append((path, yaml.safe_load(source)))
    return result


def _resign(payload):
    payload["contract_digest"] = compute_contract_digest(payload)
    return payload


class BoardContractSchemaTests(unittest.TestCase):
    def test_schema_is_valid_and_all_documents_conform(self):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as source:
            schema = json.load(source)
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is not installed; typed model validation still runs")
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema)
        for path, payload in _payloads():
            with self.subTest(path=os.path.basename(path)):
                errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
                self.assertEqual([], errors)

    def test_catalog_contains_the_versioned_board_contracts(self):
        catalog = load_default_catalog(refresh=True)
        self.assertEqual(
            {
                "creality.v4.2.7",
                "btt.skr-mini-e3.v3.0",
                "btt.octopus-pro.v1.0",
                "mks.robin-nano.v3",
                "printrboard.rev-b-d",
                "btt.skr-pico.v1.0",
                "btt.skr-v1.4",
            },
            {contract.board_id for contract in catalog.contracts},
        )

    def test_global_source_contract_is_full_and_reproducible(self):
        source = load_klipper_source_contract()
        self.assertEqual("fe4eb8650bd7de4c2100a14eaf09b0965c430e29", source.validated_commit)
        self.assertEqual("https://github.com/Klipper3d/klipper.git", source.repository)
        self.assertEqual("refs/heads/master", source.upstream_monitor_ref)
        self.assertFalse(source.upstream_monitor_mutation_allowed)
        for contract in load_default_catalog(refresh=True).contracts:
            self.assertEqual(source.validated_commit, contract.upstream.validated_commit)
            self.assertEqual(source.repository, contract.upstream.repository)
            self.assertEqual(
                contract.upstream.header_sha256_lf,
                sha256_lf(contract.upstream.header_text),
            )


class BoardCatalogIdentityTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_default_catalog(refresh=True)
        self.resolver = BoardResolver(self.catalog)

    def test_resolution_uses_exact_aliases_only(self):
        resolved = self.resolver.resolve(
            "generic-bigtreetech-skr-mini-e3-v3.0.cfg",
            hardware_variant_id="stm32g0b1",
            build_target_id="usb-pa11-pa12",
        )
        self.assertEqual(ResolutionStatus.RESOLVED, resolved.status)
        self.assertEqual(
            "btt.skr-mini-e3.v3.0/stm32g0b1/usb-pa11-pa12",
            resolved.qualified_target_id,
        )
        self.assertEqual(
            ResolutionStatus.NOT_FOUND,
            self.resolver.resolve("skr-mini-e3-v3").status,
        )
        self.assertEqual(
            ResolutionStatus.NOT_FOUND,
            self.resolver.resolve("prefix-generic-bigtreetech-skr-mini-e3-v3.0.cfg").status,
        )

    def test_exact_normalization_does_not_add_fuzzy_matching(self):
        self.assertIsNotNone(self.catalog.resolve_exact("  SKR-PICO  "))
        self.assertIsNone(self.catalog.resolve_exact("skr pico"))
        self.assertIsNone(self.catalog.resolve_exact("pico"))
        self.assertIsNone(self.catalog.resolve_exact(".*skr-pico.*"))

    def test_ambiguous_alias_invalidates_the_whole_catalog(self):
        first = deepcopy(_payloads()[0][1])
        second = deepcopy(_payloads()[1][1])
        second["aliases"]["legacy_exact"] = [first["aliases"]["legacy_exact"][0]]
        _resign(second)
        entries = [
            CatalogEntry(BoardContract.from_mapping(first, source="first"), "first"),
            CatalogEntry(BoardContract.from_mapping(second, source="second"), "second"),
        ]
        with self.assertRaisesRegex(BoardCatalogError, "ambiguous exact alias"):
            BoardCatalog(entries)

    def test_regex_like_alias_is_rejected_before_indexing(self):
        payload = deepcopy(_payloads()[0][1])
        payload["aliases"]["legacy_exact"] = ["octopus.*"]
        _resign(payload)
        with self.assertRaisesRegex(BoardContractError, "exact literals"):
            BoardContract.from_mapping(payload)

    def test_multi_mcu_board_requires_an_explicit_variant(self):
        result = self.resolver.resolve("octopus-pro-v1.0")
        self.assertEqual(ResolutionStatus.AMBIGUOUS_VARIANT, result.status)
        self.assertEqual({"stm32f446", "stm32f429", "stm32h723"}, set(result.candidates))

    def test_skr_v14_resolves_only_with_exact_variant_and_target_ids(self):
        unresolved = self.resolver.resolve("generic-bigtreetech-skr-v1.4.cfg")
        self.assertEqual(ResolutionStatus.AMBIGUOUS_VARIANT, unresolved.status)
        self.assertEqual(
            {"lpc1768", "lpc1769-turbo"}, set(unresolved.candidates)
        )
        for variant_id in ("lpc1768", "lpc1769-turbo"):
            resolved = self.resolver.resolve(
                "generic-bigtreetech-skr-v1.4.cfg",
                hardware_variant_id=variant_id,
                build_target_id="usb-native",
            )
            self.assertEqual(ResolutionStatus.RESOLVED, resolved.status)
        self.assertEqual(
            ResolutionStatus.VARIANT_NOT_FOUND,
            self.resolver.resolve(
                "generic-bigtreetech-skr-v1.4.cfg",
                hardware_variant_id="lpc176",
            ).status,
        )

    def test_multi_transport_variant_requires_an_explicit_target(self):
        result = self.resolver.resolve(
            "creality-v4.2.7", hardware_variant_id="stm32f103-ret6"
        )
        self.assertEqual(ResolutionStatus.AMBIGUOUS_TARGET, result.status)
        self.assertEqual(
            {"uart-usart1-pa10-pa9", "uart-usart3-pb11-pb10"},
            set(result.candidates),
        )


class BoardContractIntegrityTests(unittest.TestCase):
    def test_every_contract_has_provenance_for_all_decision_fields(self):
        for contract in load_default_catalog(refresh=True).contracts:
            with self.subTest(board=contract.board_id):
                for variant in contract.hardware_variants:
                    self.assertTrue(variant.processor.provenance)
                    self.assertTrue(variant.bootloader.provenance)
                    self.assertTrue(variant.clock.provenance)
                    for target in variant.build_targets:
                        self.assertTrue(target.transport.provenance)
                        self.assertTrue(target.low_level.provenance)
                        self.assertTrue(target.kconfig_provenance)
                        self.assertTrue(target.artifact.provenance)
                        self.assertTrue(target.flash.provenance)
                        self.assertTrue(target.requested_kconfig)
                        self.assertTrue(target.resolved_assertions)
                for warning in contract.warnings:
                    self.assertTrue(warning.provenance)

    def test_canonical_serialization_ignores_yaml_key_order_and_declared_digest(self):
        payload = deepcopy(_payloads()[0][1])
        reordered = dict(reversed(list(payload.items())))
        reordered["contract_digest"] = "f" * 64
        self.assertEqual(
            compute_contract_digest(payload),
            compute_contract_digest(reordered),
        )
        contract = BoardContract.from_mapping(payload)
        self.assertEqual(contract.canonical_bytes(), contract.canonical_bytes())

    def test_all_declared_contract_digests_are_current(self):
        for path, payload in _payloads():
            with self.subTest(path=os.path.basename(path)):
                self.assertEqual(payload["contract_digest"], compute_contract_digest(payload))
                contract = BoardContract.from_mapping(payload, source=path)
                self.assertEqual(contract.declared_digest, contract.contract_digest)

    def test_digest_detects_metadata_tampering(self):
        payload = deepcopy(_payloads()[0][1])
        payload["display_name"] += " tampered"
        with self.assertRaisesRegex(BoardContractError, "contract_digest mismatch"):
            BoardContract.from_mapping(payload)

    def test_unknown_schema_fields_are_rejected_by_the_runtime_loader(self):
        payload = deepcopy(_payloads()[0][1])
        payload["hardware_variants"][0]["processor"]["legacy_guess"] = "stm32"
        _resign(payload)
        with self.assertRaisesRegex(BoardContractError, "unexpected fields"):
            BoardContract.from_mapping(payload)

    def test_requested_kconfig_must_encode_variant_and_target_contract(self):
        payload = deepcopy(_payloads()[1][1])
        target = payload["hardware_variants"][0]["build_targets"][0]
        target["requested_kconfig"].pop("CONFIG_MACH_STM32G0B1")
        _resign(payload)
        with self.assertRaisesRegex(BoardContractError, "requested_kconfig does not encode"):
            BoardContract.from_mapping(payload)

    def test_pseudo_mcu_is_rejected_in_model_and_resolved_value(self):
        for field in ("model", "resolved_mcu"):
            with self.subTest(field=field):
                payload = deepcopy(_payloads()[0][1])
                payload["hardware_variants"][0]["processor"][field] = "mks-gen-l"
                _resign(payload)
                with self.assertRaisesRegex(BoardContractError, "allow-listed"):
                    BoardContract.from_mapping(payload)

    def test_shell_backends_and_shell_syntax_are_rejected(self):
        printrboard = next(
            deepcopy(payload) for _, payload in _payloads()
            if payload["board_id"] == "printrboard.rev-b-d"
        )
        command = printrboard["hardware_variants"][0]["build_targets"][0]["flash"]["command"]
        command["backend"] = "shell"
        _resign(printrboard)
        with self.assertRaisesRegex(BoardContractError, "not allow-listed"):
            BoardContract.from_mapping(printrboard)

        printrboard = next(
            deepcopy(payload) for _, payload in _payloads()
            if payload["board_id"] == "printrboard.rev-b-d"
        )
        command = printrboard["hardware_variants"][0]["build_targets"][0]["flash"]["command"]
        command["argv"].append("{artifact};rm")
        _resign(printrboard)
        with self.assertRaisesRegex(BoardContractError, "shell syntax"):
            BoardContract.from_mapping(printrboard)


class LegacyCompatibilityAndShadowTests(unittest.TestCase):
    EXPECTED_LEGACY = {
        "creality.v4.2.7": ("creality-v4.2.7", "stm32f103"),
        "btt.skr-mini-e3.v3.0": ("skr-mini-e3-v3.0", "stm32g0b1"),
        "btt.octopus-pro.v1.0": ("octopus-pro-v1.0", "stm32f429"),
        "mks.robin-nano.v3": ("mks-robin-nano-v3", "stm32f407"),
        "printrboard.rev-b-d": ("printrboard", "at90usb1286"),
        "btt.skr-pico.v1.0": ("skr-pico", "rp2040"),
        "btt.skr-v1.4": ("skr-v1.4", ("lpc1768", "lpc1769")),
    }

    def test_each_contract_retains_an_exact_current_legacy_term(self):
        with open(os.path.join(ROOT, "data", "boards.yaml"), "r", encoding="utf-8") as source:
            legacy = yaml.safe_load(source)
        exact_terms = {
            term: {
                candidate["mcu"]
                for candidate in legacy["boards"]
                if term in candidate.get("search_terms", [])
            }
            for board in legacy["boards"]
            for term in board.get("search_terms", [])
        }
        catalog = load_default_catalog(refresh=True)
        for board_id, (alias, expected_mcu) in self.EXPECTED_LEGACY.items():
            with self.subTest(board=board_id):
                contract = catalog.by_id(board_id)
                self.assertIn(alias, contract.legacy_aliases)
                expected_mcus = (
                    set(expected_mcu)
                    if isinstance(expected_mcu, tuple)
                    else {expected_mcu}
                )
                self.assertEqual(expected_mcus, exact_terms[alias])

    def test_shadow_comparison_reports_agreement_and_known_divergence(self):
        agreement = compare_legacy_resolution("skr-mini-e3-v3.0", "stm32g0b1")
        self.assertEqual(ShadowDivergence.AGREES, agreement.divergence)
        self.assertEqual(("stm32g0b1",), agreement.matching_variant_ids)

        divergence = compare_legacy_resolution("skr-mini-e3-v3.0", "stm32f103")
        self.assertEqual(ShadowDivergence.MCU_DIVERGENCE, divergence.divergence)
        self.assertEqual("btt.skr-mini-e3.v3.0", divergence.board_contract_id)

    def test_shadow_capture_does_not_change_legacy_decisions(self):
        user_data = {
            "board": "generic-bigtreetech-skr-pico-v1.0.cfg",
            "mcu_type": "rp2040",
            "derivation": {"legacy": True},
        }
        before = deepcopy(user_data)
        capture_shadow_comparison(user_data, user_data["board"])
        self.assertEqual(before["board"], user_data["board"])
        self.assertEqual(before["mcu_type"], user_data["mcu_type"])
        self.assertEqual(before["derivation"], user_data["derivation"])
        self.assertEqual("AGREES", user_data["board_contract_shadow"]["divergence"])

    def test_legacy_only_substring_is_not_accepted_by_shadow_catalog(self):
        result = compare_legacy_resolution("my-printrboard-g2-custom.cfg", "at90usb1286")
        self.assertEqual(ShadowDivergence.BOARD_NOT_COVERED, result.divergence)


if __name__ == "__main__":
    unittest.main()
