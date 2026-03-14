from pathlib import Path


def test_new_campagne_service_commands_registered() -> None:
    source = Path("app/plugins/commands_modular/messaggi.py").read_text()
    for cmd in ["notizie", "meteo", "oroscopo", "servizi_lista", "servizi_test", "servizi_on", "servizi_off", "servizi_delete"]:
        assert f'@campagne_group.command(name="{cmd}"' in source
