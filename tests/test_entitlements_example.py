import json
from pathlib import Path


def test_entitlements_example_covers_runtime_access_paths() -> None:
    payload = json.loads(Path("app/settings/entitlements.example.json").read_text())

    assert payload["mod"]["role_ids"] == []

    profile_map = payload["entitlements"]["profile_map"]
    assert profile_map["role_to_profile"] == {}
    for profile in ("base", "role1", "role2", "role3", "mod"):
        assert isinstance(profile_map["profiles"][profile]["priority"], int)

    policies = payload["entitlements"]["policies"]
    commands = policies["commands"]

    # /barcello expects allowed/messages/output/capabilities in command profile config
    barcello_profiles = commands["barcello"]["profiles"]
    for profile in ("base", "role1", "role2", "role3", "mod"):
        cfg = barcello_profiles[profile]
        assert isinstance(cfg.get("allowed"), bool)
        assert isinstance(cfg.get("messages", {}), dict)
        output = cfg.get("output", {})
        for key in ("show_score", "show_motivation", "show_trend", "show_advice", "show_mod_metrics"):
            assert key in output

    # /riassunto uses profile config and max_window_seconds limit mapping
    riassunto = commands["riassunto"]
    for profile in ("base", "role1", "role2", "role3", "mod"):
        assert isinstance(riassunto["profiles"][profile]["allowed"], bool)
        assert isinstance(riassunto["limits"]["max_window_seconds"][profile], int)

    # /aura and AuraEligibilityService expect all these keys for feature profile config
    aura_profiles = commands["aura"]["profiles"]
    for profile in ("base", "role1", "role2", "role3", "mod"):
        aura_cfg = aura_profiles[profile]["features"]["aura"]
        for key in ("enabled", "limits", "render", "privacy", "missions", "eligibility"):
            assert key in aura_cfg

    # Global feature gate used by /barcello and /riassunto
    assert isinstance(policies["features"]["ai"]["allowed_profiles"], list)
