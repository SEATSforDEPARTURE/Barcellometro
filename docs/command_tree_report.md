# Command Tree Validation Report

Questo report inventaria i comandi realmente registrati nel repository. Per il vocabolario canonico delle action e la loro semantica normativa fa fede `docs/command_standards.md`; le action composte (`config_set`, `schedule_add`, `template_global_reset`, ecc.) vanno lette come estensioni dei verbi canonici e non introducono nuove action standard.

- Commands discovered: **362**
- Errors: **0**
- Warnings: **90**

## Inventory

| Root | Subgroup | Action | Description | Source |
| --- | --- | --- | --- | --- |
| `ai` | `—` | `fallback_reset` | Reset the AI fallback model override for a task. | `app/plugins/commands_modular/admin.py:488` |
| `ai` | `—` | `fallback_set` | Set the AI fallback model for a task. | `app/plugins/commands_modular/admin.py:466` |
| `ai` | `—` | `fallback_show` | Show configured AI fallback models. | `app/plugins/commands_modular/admin.py:478` |
| `ai` | `—` | `model_reset` | Reset the AI model override for a task. | `app/plugins/commands_modular/admin.py:456` |
| `ai` | `—` | `model_set` | Set the AI model for a task. | `app/plugins/commands_modular/admin.py:434` |
| `ai` | `—` | `model_show` | Show configured AI models. | `app/plugins/commands_modular/admin.py:446` |
| `ai` | `—` | `off` | Disable the AI service. | `app/plugins/commands_modular/admin.py:399` |
| `ai` | `—` | `on` | Enable the AI service. | `app/plugins/commands_modular/admin.py:392` |
| `ai` | `—` | `run` | Run an AI test prompt. | `app/plugins/commands_modular/admin.py:497` |
| `ai` | `—` | `status` | Show AI service status. | `app/plugins/commands_modular/admin.py:406` |
| `attivita` | `—` | `off` | Disable activity summary in this channel. | `app/plugins/commands_modular/attivita.py:654` |
| `attivita` | `—` | `on` | Enable activity summary in this channel. | `app/plugins/commands_modular/attivita.py:650` |
| `attivita` | `—` | `status` | Show activity summary status in this channel. | `app/plugins/commands_modular/attivita.py:658` |
| `audio` | `—` | `limits_reset` | Reset the audio clip limits to domain defaults. | `app/plugins/commands_modular/audio_notes.py:193` |
| `audio` | `—` | `limits_set` | Update the audio clip limits. | `app/plugins/commands_modular/audio_notes.py:118` |
| `audio` | `—` | `limits_show` | Show the audio clip limits. | `app/plugins/commands_modular/audio_notes.py:180` |
| `audio` | `—` | `off` | Disable audio notes. | `app/plugins/commands_modular/audio_notes.py:77` |
| `audio` | `—` | `on` | Enable audio notes. | `app/plugins/commands_modular/audio_notes.py:62` |
| `audio` | `—` | `status` | Show the audio status. | `app/plugins/commands_modular/audio_notes.py:92` |
| `aura` | `—` | `off` | Disable Aura summary. | `app/plugins/commands_modular/aura.py:470` |
| `aura` | `—` | `on` | Enable Aura summary. | `app/plugins/commands_modular/aura.py:466` |
| `aura` | `—` | `status` | Show Aura summary status. | `app/plugins/commands_modular/aura.py:474` |
| `ban` | `—` | `ban` | Alias of /users ban. | `app/plugins/commands_modular/moderazione_utenti.py:1864` |
| `barcello` | `—` | `ieri` | Mostra lo stato del barcello di ieri (in DM) | `app/plugins/commands_modular/barcello.py:2402` |
| `barcello` | `—` | `intervallo` | Mostra lo stato del barcello per intervallo. | `app/plugins/commands_modular/barcello.py:2429` |
| `barcello` | `—` | `oggi` | Mostra lo stato del barcello di oggi (in DM) | `app/plugins/commands_modular/barcello.py:2394` |
| `barcello` | `—` | `ultimi` | Mostra lo stato del barcello per gli ultimi N periodi. | `app/plugins/commands_modular/barcello.py:2419` |
| `campaigns` | `cap` | `limits_reset` | Reset the daily cap limit | `app/plugins/commands_modular/messaggi.py:605` |
| `campaigns` | `cap` | `limits_set` | Set the daily cap limit | `app/plugins/commands_modular/messaggi.py:588` |
| `campaigns` | `cap` | `limits_show` | Show the daily cap limit | `app/plugins/commands_modular/messaggi.py:598` |
| `campaigns` | `cap` | `off` | Disable the daily cap | `app/plugins/commands_modular/messaggi.py:572` |
| `campaigns` | `cap` | `on` | Enable the daily cap | `app/plugins/commands_modular/messaggi.py:565` |
| `campaigns` | `cap` | `status` | Show the daily cap status | `app/plugins/commands_modular/messaggi.py:579` |
| `campaigns` | `custom` | `off` | Disable custom campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:616` |
| `campaigns` | `custom` | `on` | Enable custom campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:612` |
| `campaigns` | `custom` | `run` | Run a custom campaign schedule now | `app/plugins/commands_modular/messaggi.py:752` |
| `campaigns` | `custom` | `schedule_add` | Add a custom campaign schedule | `app/plugins/commands_modular/messaggi.py:639` |
| `campaigns` | `custom` | `schedule_edit` | Edit a custom campaign schedule | `app/plugins/commands_modular/messaggi.py:793` |
| `campaigns` | `custom` | `schedule_list` | List custom campaign schedules | `app/plugins/commands_modular/messaggi.py:709` |
| `campaigns` | `custom` | `schedule_remove` | Remove a custom campaign schedule | `app/plugins/commands_modular/messaggi.py:737` |
| `campaigns` | `custom` | `schedule_show` | Show a custom campaign schedule | `app/plugins/commands_modular/messaggi.py:723` |
| `campaigns` | `custom` | `status` | Show custom campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:620` |
| `campaigns` | `horoscope` | `off` | Disable horoscope campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:1082` |
| `campaigns` | `horoscope` | `on` | Enable horoscope campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:1078` |
| `campaigns` | `horoscope` | `run` | Run the horoscope campaign immediately | `app/plugins/commands_modular/messaggi.py:1163` |
| `campaigns` | `horoscope` | `schedule_add` | Add a horoscope campaign schedule | `app/plugins/commands_modular/messaggi.py:1097` |
| `campaigns` | `horoscope` | `schedule_edit` | Edit a horoscope campaign schedule | `app/plugins/commands_modular/messaggi.py:1126` |
| `campaigns` | `horoscope` | `schedule_list` | List horoscope campaign schedules | `app/plugins/commands_modular/messaggi.py:1159` |
| `campaigns` | `horoscope` | `schedule_remove` | Remove a horoscope campaign schedule | `app/plugins/commands_modular/messaggi.py:1155` |
| `campaigns` | `horoscope` | `schedule_show` | Show a horoscope campaign schedule | `app/plugins/commands_modular/messaggi.py:1150` |
| `campaigns` | `horoscope` | `status` | Show horoscope campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:1086` |
| `campaigns` | `insights` | `off` | Disable insights in the current channel | `app/plugins/commands_modular/triggers.py:1009` |
| `campaigns` | `insights` | `on` | Enable insights in the current channel | `app/plugins/commands_modular/triggers.py:1005` |
| `campaigns` | `insights` | `status` | Show insights status for the current channel | `app/plugins/commands_modular/triggers.py:1013` |
| `campaigns` | `insights` | `template_reset` | Reset the insights template to defaults | `app/plugins/commands_modular/triggers.py:1049` |
| `campaigns` | `insights` | `template_set` | Set the insights template | `app/plugins/commands_modular/triggers.py:1027` |
| `campaigns` | `insights` | `template_show` | Show the insights template | `app/plugins/commands_modular/triggers.py:1037` |
| `campaigns` | `news` | `off` | Disable news campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:905` |
| `campaigns` | `news` | `on` | Enable news campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:901` |
| `campaigns` | `news` | `run` | Run the news campaign immediately | `app/plugins/commands_modular/messaggi.py:985` |
| `campaigns` | `news` | `schedule_add` | Add a news campaign schedule | `app/plugins/commands_modular/messaggi.py:921` |
| `campaigns` | `news` | `schedule_edit` | Edit a news campaign schedule | `app/plugins/commands_modular/messaggi.py:950` |
| `campaigns` | `news` | `schedule_list` | List news campaign schedules | `app/plugins/commands_modular/messaggi.py:981` |
| `campaigns` | `news` | `schedule_remove` | Remove a news campaign schedule | `app/plugins/commands_modular/messaggi.py:977` |
| `campaigns` | `news` | `schedule_show` | Show a news campaign schedule | `app/plugins/commands_modular/messaggi.py:972` |
| `campaigns` | `news` | `status` | Show news campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:909` |
| `campaigns` | `—` | `off` | Disable campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:493` |
| `campaigns` | `—` | `on` | Enable campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:482` |
| `campaigns` | `prompt` | `off` | Disable prompt campaigns in the current channel | `app/plugins/commands_modular/triggers.py:651` |
| `campaigns` | `prompt` | `on` | Enable prompt campaigns in the current channel | `app/plugins/commands_modular/triggers.py:639` |
| `campaigns` | `prompt` | `run` | Run a prompt campaign schedule now | `app/plugins/commands_modular/triggers.py:784` |
| `campaigns` | `prompt` | `schedule_add` | Add a prompt campaign schedule | `app/plugins/commands_modular/triggers.py:682` |
| `campaigns` | `prompt` | `schedule_edit` | Edit a prompt campaign schedule | `app/plugins/commands_modular/triggers.py:828` |
| `campaigns` | `prompt` | `schedule_list` | List prompt campaign schedules | `app/plugins/commands_modular/triggers.py:741` |
| `campaigns` | `prompt` | `schedule_remove` | Remove a prompt campaign schedule | `app/plugins/commands_modular/triggers.py:769` |
| `campaigns` | `prompt` | `schedule_show` | Show a prompt campaign schedule | `app/plugins/commands_modular/triggers.py:755` |
| `campaigns` | `prompt` | `status` | Show prompt campaign status for the current channel | `app/plugins/commands_modular/triggers.py:663` |
| `campaigns` | `quiet` | `off` | Disable quiet hours | `app/plugins/commands_modular/messaggi.py:524` |
| `campaigns` | `quiet` | `on` | Enable quiet hours | `app/plugins/commands_modular/messaggi.py:517` |
| `campaigns` | `quiet` | `range_reset` | Reset the quiet-hours start/end range | `app/plugins/commands_modular/messaggi.py:557` |
| `campaigns` | `quiet` | `range_set` | Set the quiet-hours start/end range | `app/plugins/commands_modular/messaggi.py:541` |
| `campaigns` | `quiet` | `range_show` | Show the quiet-hours start/end range | `app/plugins/commands_modular/messaggi.py:549` |
| `campaigns` | `quiet` | `status` | Show quiet hours status | `app/plugins/commands_modular/messaggi.py:531` |
| `campaigns` | `—` | `status` | Show campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:504` |
| `campaigns` | `weather` | `off` | Disable weather campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:993` |
| `campaigns` | `weather` | `on` | Enable weather campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:989` |
| `campaigns` | `weather` | `run` | Run the weather campaign immediately | `app/plugins/commands_modular/messaggi.py:1074` |
| `campaigns` | `weather` | `schedule_add` | Add a weather campaign schedule | `app/plugins/commands_modular/messaggi.py:1008` |
| `campaigns` | `weather` | `schedule_edit` | Edit a weather campaign schedule | `app/plugins/commands_modular/messaggi.py:1037` |
| `campaigns` | `weather` | `schedule_list` | List weather campaign schedules | `app/plugins/commands_modular/messaggi.py:1070` |
| `campaigns` | `weather` | `schedule_remove` | Remove a weather campaign schedule | `app/plugins/commands_modular/messaggi.py:1066` |
| `campaigns` | `weather` | `schedule_show` | Show a weather campaign schedule | `app/plugins/commands_modular/messaggi.py:1061` |
| `campaigns` | `weather` | `status` | Show weather campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:997` |
| `clips` | `—` | `stt_reset` | Reset the clip STT configuration to domain defaults. | `app/plugins/commands_modular/stt.py:120` |
| `clips` | `—` | `stt_set` | Update the clip STT configuration. | `app/plugins/commands_modular/stt.py:62` |
| `clips` | `—` | `stt_show` | Show the clip STT configuration. | `app/plugins/commands_modular/stt.py:107` |
| `clips` | `—` | `translate_reset` | Reset the clip translation configuration to domain defaults. | `app/plugins/commands_modular/translate.py:79` |
| `clips` | `—` | `translate_set` | Update the clip translation configuration. | `app/plugins/commands_modular/translate.py:32` |
| `clips` | `—` | `translate_show` | Show the clip translation configuration. | `app/plugins/commands_modular/translate.py:66` |
| `commandguard` | `—` | `role_add` | Add a role command policy. | `app/plugins/commands_modular/roles.py:80` |
| `commandguard` | `—` | `role_edit` | Edit a role command policy. | `app/plugins/commands_modular/roles.py:91` |
| `commandguard` | `—` | `role_list` | List all role policies. | `app/plugins/commands_modular/roles.py:122` |
| `commandguard` | `—` | `role_remove` | Remove a role command policy. | `app/plugins/commands_modular/roles.py:102` |
| `commandguard` | `—` | `role_show` | Show role policies. | `app/plugins/commands_modular/roles.py:110` |
| `commandguard` | `—` | `user_add` | Add a user command policy. | `app/plugins/commands_modular/roles.py:133` |
| `commandguard` | `—` | `user_edit` | Edit a user command policy. | `app/plugins/commands_modular/roles.py:144` |
| `commandguard` | `—` | `user_list` | List all user policies. | `app/plugins/commands_modular/roles.py:175` |
| `commandguard` | `—` | `user_remove` | Remove a user command policy. | `app/plugins/commands_modular/roles.py:155` |
| `commandguard` | `—` | `user_show` | Show user policies. | `app/plugins/commands_modular/roles.py:163` |
| `database` | `backfill` | `limits_reset` | Reset backfill limits to defaults. | `app/plugins/commands_modular/admin.py:346` |
| `database` | `backfill` | `limits_set` | Update backfill limits. | `app/plugins/commands_modular/admin.py:295` |
| `database` | `backfill` | `limits_show` | Show backfill limits. | `app/plugins/commands_modular/admin.py:333` |
| `database` | `backfill` | `off` | Disable backfill. | `app/plugins/commands_modular/admin.py:272` |
| `database` | `backfill` | `on` | Enable backfill. | `app/plugins/commands_modular/admin.py:265` |
| `database` | `backfill` | `run` | Run backfill now. | `app/plugins/commands_modular/admin.py:362` |
| `database` | `backfill` | `status` | Show backfill status. | `app/plugins/commands_modular/admin.py:279` |
| `database` | `events` | `off` | Disable event collection for this channel. | `app/plugins/commands_modular/admin.py:156` |
| `database` | `events` | `on` | Enable event collection for this channel. | `app/plugins/commands_modular/admin.py:150` |
| `database` | `events` | `status` | Show event collection status for this channel. | `app/plugins/commands_modular/admin.py:162` |
| `database` | `retention` | `limits_reset` | Reset retention limits to defaults. | `app/plugins/commands_modular/admin.py:249` |
| `database` | `retention` | `limits_set` | Update retention limits. | `app/plugins/commands_modular/admin.py:198` |
| `database` | `retention` | `limits_show` | Show retention limits. | `app/plugins/commands_modular/admin.py:236` |
| `database` | `retention` | `off` | Disable the retention task. | `app/plugins/commands_modular/admin.py:175` |
| `database` | `retention` | `on` | Enable the retention task. | `app/plugins/commands_modular/admin.py:168` |
| `database` | `retention` | `status` | Show retention status. | `app/plugins/commands_modular/admin.py:182` |
| `dmchannelsummary` | `barcello` | `last` | Run Barcello summary for the last N units. | `app/plugins/commands_modular/barcello.py:2357` |
| `dmchannelsummary` | `barcello` | `off` | Disable Barcello DM summary in this channel. | `app/plugins/commands_modular/barcello.py:2316` |
| `dmchannelsummary` | `barcello` | `on` | Enable Barcello DM summary in this channel. | `app/plugins/commands_modular/barcello.py:2312` |
| `dmchannelsummary` | `barcello` | `range` | Run Barcello summary for a custom range. | `app/plugins/commands_modular/barcello.py:2376` |
| `dmchannelsummary` | `barcello` | `status` | Show Barcello DM summary status in this channel. | `app/plugins/commands_modular/barcello.py:2320` |
| `dmchannelsummary` | `barcello` | `today` | Run Barcello summary for today. | `app/plugins/commands_modular/barcello.py:2324` |
| `dmchannelsummary` | `barcello` | `yesterday` | Run Barcello summary for yesterday. | `app/plugins/commands_modular/barcello.py:2336` |
| `embed` | `author` | `off` | Disable author rendering. | `app/plugins/commands_modular/embed.py:541` |
| `embed` | `author` | `on` | Enable author rendering. | `app/plugins/commands_modular/embed.py:531` |
| `embed` | `author` | `status` | Show author status and effective service templates. | `app/plugins/commands_modular/embed.py:741` |
| `embed` | `author` | `template_global_reset` | Reset the global author template. | `app/plugins/commands_modular/embed.py:625` |
| `embed` | `author` | `template_global_set` | Set the global author template. | `app/plugins/commands_modular/embed.py:552` |
| `embed` | `author` | `template_global_show` | Show the global author template. | `app/plugins/commands_modular/embed.py:600` |
| `embed` | `author` | `template_service_reset` | Reset a service-specific author template. | `app/plugins/commands_modular/embed.py:724` |
| `embed` | `author` | `template_service_set` | Set a service-specific author template. | `app/plugins/commands_modular/embed.py:640` |
| `embed` | `author` | `template_service_show` | Show a service-specific author template. | `app/plugins/commands_modular/embed.py:690` |
| `embed` | `description` | `off` | Disable centralized description template overrides. | `app/plugins/commands_modular/embed.py:819` |
| `embed` | `description` | `on` | Enable centralized description template overrides. | `app/plugins/commands_modular/embed.py:809` |
| `embed` | `description` | `status` | Show centralized description template override status. | `app/plugins/commands_modular/embed.py:829` |
| `embed` | `description` | `template_service_reset` | Reset a service-specific description template. | `app/plugins/commands_modular/embed.py:943` |
| `embed` | `description` | `template_service_set` | Set a service-specific description template. | `app/plugins/commands_modular/embed.py:870` |
| `embed` | `description` | `template_service_show` | Show a service-specific description template. | `app/plugins/commands_modular/embed.py:910` |
| `embed` | `footer` | `off` | Disable footer rendering. | `app/plugins/commands_modular/embed.py:179` |
| `embed` | `footer` | `on` | Enable footer rendering. | `app/plugins/commands_modular/embed.py:157` |
| `embed` | `footer` | `status` | Show footer status and rendered variants. | `app/plugins/commands_modular/embed.py:458` |
| `embed` | `footer` | `template_global_reset` | Reset the global footer template. | `app/plugins/commands_modular/embed.py:286` |
| `embed` | `footer` | `template_global_set` | Set the global footer template. | `app/plugins/commands_modular/embed.py:202` |
| `embed` | `footer` | `template_global_show` | Show the global footer template. | `app/plugins/commands_modular/embed.py:259` |
| `embed` | `footer` | `template_service_reset` | Reset a service-specific footer template. | `app/plugins/commands_modular/embed.py:423` |
| `embed` | `footer` | `template_service_set` | Set a service-specific footer template. | `app/plugins/commands_modular/embed.py:312` |
| `embed` | `footer` | `template_service_show` | Show a service-specific footer template. | `app/plugins/commands_modular/embed.py:382` |
| `embed` | `images` | `off` | Disable centralized embed images rendering. | `app/plugins/commands_modular/embed.py:970` |
| `embed` | `images` | `on` | Enable centralized embed images rendering. | `app/plugins/commands_modular/embed.py:960` |
| `embed` | `images` | `status` | Show embed images status. | `app/plugins/commands_modular/embed.py:980` |
| `embed` | `images` | `template_global_reset` | Reset global image and thumbnail templates. | `app/plugins/commands_modular/embed.py:1050` |
| `embed` | `images` | `template_global_set` | Set global image and thumbnail templates. | `app/plugins/commands_modular/embed.py:1003` |
| `embed` | `images` | `template_global_show` | Show global image and thumbnail templates. | `app/plugins/commands_modular/embed.py:1033` |
| `embed` | `images` | `template_service_reset` | Reset service-level image and thumbnail templates. | `app/plugins/commands_modular/embed.py:1125` |
| `embed` | `images` | `template_service_set` | Set service-level image and thumbnail templates. | `app/plugins/commands_modular/embed.py:1063` |
| `embed` | `images` | `template_service_show` | Show service-level image and thumbnail templates. | `app/plugins/commands_modular/embed.py:1099` |
| `grace` | `—` | `grace` | Alias of /users grace. | `app/plugins/commands_modular/moderazione_utenti.py:1914` |
| `greetings` | `backfill` | `off` | Disable greetings timeline backfill. | `app/plugins/commands_modular/greetings.py:105` |
| `greetings` | `backfill` | `on` | Enable greetings timeline backfill. | `app/plugins/commands_modular/greetings.py:94` |
| `greetings` | `backfill` | `run` | Run greetings timeline backfill now. | `app/plugins/commands_modular/greetings.py:122` |
| `greetings` | `backfill` | `status` | Show greetings timeline backfill status. | `app/plugins/commands_modular/greetings.py:116` |
| `greetings` | `—` | `notify_reset` | Reset the greetings notification channel. | `app/plugins/commands_modular/greetings.py:209` |
| `greetings` | `—` | `notify_set` | Set the greetings notification channel. | `app/plugins/commands_modular/greetings.py:187` |
| `greetings` | `—` | `notify_show` | Show the greetings notification channel. | `app/plugins/commands_modular/greetings.py:201` |
| `greetings` | `—` | `off` | Disable greetings notifications. | `app/plugins/commands_modular/greetings.py:173` |
| `greetings` | `—` | `on` | Enable greetings notifications for a channel. | `app/plugins/commands_modular/greetings.py:153` |
| `greetings` | `—` | `status` | Show the greetings configuration status. | `app/plugins/commands_modular/greetings.py:180` |
| `greetings` | `user_card` | `off` | Disable the greetings notification user card. | `app/plugins/commands_modular/greetings.py:223` |
| `greetings` | `user_card` | `on` | Enable the greetings notification user card. | `app/plugins/commands_modular/greetings.py:216` |
| `greetings` | `user_card` | `status` | Show whether the greetings notification user card is enabled. | `app/plugins/commands_modular/greetings.py:230` |
| `inactivity` | `autokick` | `off` | Disable automatic inactivity actions. | `app/plugins/commands_modular/inattivi.py:284` |
| `inactivity` | `autokick` | `on` | Enable automatic inactivity actions. | `app/plugins/commands_modular/inattivi.py:277` |
| `inactivity` | `autokick` | `status` | Show the automatic inactivity action status. | `app/plugins/commands_modular/inattivi.py:291` |
| `inactivity` | `dms` | `cooldown_reset` | Reset the reminder DM cooldown. | `app/plugins/commands_modular/inattivi.py:575` |
| `inactivity` | `dms` | `cooldown_set` | Set the reminder DM cooldown. | `app/plugins/commands_modular/inattivi.py:534` |
| `inactivity` | `dms` | `cooldown_show` | Show the reminder DM cooldown. | `app/plugins/commands_modular/inattivi.py:556` |
| `inactivity` | `dms` | `invite_reset` | Reset the invite link used in inactivity DMs. | `app/plugins/commands_modular/inattivi.py:602` |
| `inactivity` | `dms` | `invite_set` | Set the invite link used in inactivity DMs. | `app/plugins/commands_modular/inattivi.py:588` |
| `inactivity` | `dms` | `invite_show` | Show the invite link used in inactivity DMs. | `app/plugins/commands_modular/inattivi.py:595` |
| `inactivity` | `dms` | `off` | Disable inactivity reminder DMs. | `app/plugins/commands_modular/inattivi.py:416` |
| `inactivity` | `dms` | `on` | Enable inactivity reminder DMs. | `app/plugins/commands_modular/inattivi.py:409` |
| `inactivity` | `dms` | `status` | Show inactivity DM status and delivery metrics. | `app/plugins/commands_modular/inattivi.py:423` |
| `inactivity` | `dms` | `template_grace_reset` | Reset the DM template sent when a member enters inactivity grace. | `app/plugins/commands_modular/inattivi.py:487` |
| `inactivity` | `dms` | `template_grace_set` | Set the DM template sent when a member enters inactivity grace. | `app/plugins/commands_modular/inattivi.py:393` |
| `inactivity` | `dms` | `template_grace_show` | Show the DM template sent when a member enters inactivity grace. | `app/plugins/commands_modular/inattivi.py:473` |
| `inactivity` | `dms` | `template_tempban_reset` | Reset the DM template sent before automatic inactivity tempban. | `app/plugins/commands_modular/inattivi.py:525` |
| `inactivity` | `dms` | `template_tempban_set` | Set the DM template sent before automatic inactivity tempban. | `app/plugins/commands_modular/inattivi.py:495` |
| `inactivity` | `dms` | `template_tempban_show` | Show the DM template sent before automatic inactivity tempban. | `app/plugins/commands_modular/inattivi.py:511` |
| `inactivity` | `grace` | `limits_reset` | Reset the inactivity grace period limits. | `app/plugins/commands_modular/inattivi.py:338` |
| `inactivity` | `grace` | `limits_set` | Set the inactivity grace period limits. | `app/plugins/commands_modular/inattivi.py:323` |
| `inactivity` | `grace` | `limits_show` | Show the inactivity grace period limits. | `app/plugins/commands_modular/inattivi.py:330` |
| `inactivity` | `grace` | `off` | Disable the inactivity grace period. | `app/plugins/commands_modular/inattivi.py:307` |
| `inactivity` | `grace` | `on` | Enable the inactivity grace period. | `app/plugins/commands_modular/inattivi.py:298` |
| `inactivity` | `grace` | `status` | Show the inactivity grace period status. | `app/plugins/commands_modular/inattivi.py:314` |
| `inactivity` | `—` | `off` | Disable inactivity moderation. | `app/plugins/commands_modular/inattivi.py:238` |
| `inactivity` | `—` | `on` | Enable inactivity moderation. | `app/plugins/commands_modular/inattivi.py:231` |
| `inactivity` | `policy` | `default_reset` | Reset the default inactivity policy. | `app/plugins/commands_modular/inattivi.py:643` |
| `inactivity` | `policy` | `default_set` | Set the default inactivity policy. | `app/plugins/commands_modular/inattivi.py:616` |
| `inactivity` | `policy` | `default_show` | Show the default inactivity policy. | `app/plugins/commands_modular/inattivi.py:635` |
| `inactivity` | `policy` | `exceptions_add` | Add a role to the inactivity exception list. | `app/plugins/commands_modular/inattivi.py:702` |
| `inactivity` | `policy` | `exceptions_list` | List all inactivity exception roles. | `app/plugins/commands_modular/inattivi.py:739` |
| `inactivity` | `policy` | `exceptions_remove` | Remove a role from the inactivity exception list. | `app/plugins/commands_modular/inattivi.py:716` |
| `inactivity` | `policy` | `exceptions_show` | Show whether a role is excluded from inactivity moderation. | `app/plugins/commands_modular/inattivi.py:730` |
| `inactivity` | `policy` | `role_reset` | Reset an inactivity policy for a role. | `app/plugins/commands_modular/inattivi.py:694` |
| `inactivity` | `policy` | `role_set` | Set an inactivity policy for a role. | `app/plugins/commands_modular/inattivi.py:659` |
| `inactivity` | `policy` | `role_show` | Show an inactivity policy for a role. | `app/plugins/commands_modular/inattivi.py:681` |
| `inactivity` | `—` | `run` | Run the inactivity moderation scan now. | `app/plugins/commands_modular/inattivi.py:754` |
| `inactivity` | `—` | `status` | Show the inactivity moderation status. | `app/plugins/commands_modular/inattivi.py:245` |
| `inactivity` | `tempban` | `limits_reset` | Reset the inactivity tempban limits. | `app/plugins/commands_modular/inattivi.py:385` |
| `inactivity` | `tempban` | `limits_set` | Set the inactivity tempban limits. | `app/plugins/commands_modular/inattivi.py:370` |
| `inactivity` | `tempban` | `limits_show` | Show the inactivity tempban limits. | `app/plugins/commands_modular/inattivi.py:377` |
| `inactivity` | `tempban` | `off` | Disable temporary bans after inactivity kicks. | `app/plugins/commands_modular/inattivi.py:354` |
| `inactivity` | `tempban` | `on` | Enable temporary bans after inactivity kicks. | `app/plugins/commands_modular/inattivi.py:345` |
| `inactivity` | `tempban` | `status` | Show the inactivity tempban status. | `app/plugins/commands_modular/inattivi.py:361` |
| `kick` | `—` | `kick` | Alias of /users kick. | `app/plugins/commands_modular/moderazione_utenti.py:1855` |
| `privacy` | `—` | `off` | Disable voice privacy. | `app/plugins/commands_modular/privacy.py:90` |
| `privacy` | `—` | `on` | Enable voice privacy. | `app/plugins/commands_modular/privacy.py:68` |
| `privacy` | `—` | `status` | Show the current voice privacy status. | `app/plugins/commands_modular/privacy.py:113` |
| `qna` | `—` | `bonus_reset` | Reset a user's QnA bonus | `app/plugins/commands_modular/triggers.py:995` |
| `qna` | `—` | `bonus_set` | Set a QnA bonus for a user | `app/plugins/commands_modular/triggers.py:964` |
| `qna` | `—` | `bonus_show` | Show a user's QnA bonus | `app/plugins/commands_modular/triggers.py:984` |
| `qna` | `—` | `limits_reset` | Reset QnA daily limits to defaults | `app/plugins/commands_modular/triggers.py:954` |
| `qna` | `—` | `limits_set` | Set a QnA daily limit | `app/plugins/commands_modular/triggers.py:933` |
| `qna` | `—` | `limits_show` | Show QnA daily limits | `app/plugins/commands_modular/triggers.py:910` |
| `qna` | `—` | `off` | Disable QnA in the current channel | `app/plugins/commands_modular/triggers.py:900` |
| `qna` | `—` | `on` | Enable QnA in the current channel | `app/plugins/commands_modular/triggers.py:896` |
| `qna` | `—` | `status` | Show QnA status for the current channel | `app/plugins/commands_modular/triggers.py:904` |
| `resocontocanale` | `aura` | `ieri` | Show manual channel aura details for yesterday. | `app/plugins/commands_modular/resoconto.py:796` |
| `resocontocanale` | `aura` | `oggi` | Show manual channel aura details for today. | `app/plugins/commands_modular/resoconto.py:772` |
| `resocontocanale` | `aura` | `range` | Show manual channel aura details for a range. | `app/plugins/commands_modular/resoconto.py:872` |
| `resocontocanale` | `aura` | `ultimi` | Show manual channel aura details for the last window. | `app/plugins/commands_modular/resoconto.py:840` |
| `resocontocanale` | `—` | `ieri` | Show manual channel summary for yesterday. | `app/plugins/commands_modular/resoconto.py:784` |
| `resocontocanale` | `—` | `off` | Disable automatic channel summaries for the current channel. | `app/plugins/commands_modular/resoconto.py:550` |
| `resocontocanale` | `—` | `oggi` | Show manual channel summary for today. | `app/plugins/commands_modular/resoconto.py:760` |
| `resocontocanale` | `—` | `on` | Enable automatic channel summaries for the current channel. | `app/plugins/commands_modular/resoconto.py:534` |
| `resocontocanale` | `—` | `range` | Show manual channel summary for a range. | `app/plugins/commands_modular/resoconto.py:856` |
| `resocontocanale` | `—` | `schedule_add` | Add a channel summary schedule. | `app/plugins/commands_modular/resoconto.py:609` |
| `resocontocanale` | `—` | `schedule_edit` | Edit a channel summary schedule. | `app/plugins/commands_modular/resoconto.py:637` |
| `resocontocanale` | `—` | `schedule_list` | List channel summary schedules for the current channel. | `app/plugins/commands_modular/resoconto.py:738` |
| `resocontocanale` | `—` | `schedule_remove` | Remove a channel summary schedule. | `app/plugins/commands_modular/resoconto.py:691` |
| `resocontocanale` | `—` | `schedule_show` | Show one channel summary schedule. | `app/plugins/commands_modular/resoconto.py:715` |
| `resocontocanale` | `—` | `status` | Show the channel summary schedule status. | `app/plugins/commands_modular/resoconto.py:566` |
| `resocontocanale` | `—` | `ultimi` | Show manual channel summary for the last window. | `app/plugins/commands_modular/resoconto.py:816` |
| `resocontoserver` | `aura` | `ieri` | Show manual server aura details for yesterday. | `app/plugins/commands_modular/resoconto.py:1137` |
| `resocontoserver` | `aura` | `oggi` | Show manual server aura details for today. | `app/plugins/commands_modular/resoconto.py:1114` |
| `resocontoserver` | `aura` | `range` | Show manual server aura details for a range. | `app/plugins/commands_modular/resoconto.py:1211` |
| `resocontoserver` | `aura` | `ultimi` | Show manual server aura details for the last window. | `app/plugins/commands_modular/resoconto.py:1180` |
| `resocontoserver` | `—` | `ieri` | Show manual server summary for yesterday. | `app/plugins/commands_modular/resoconto.py:1125` |
| `resocontoserver` | `—` | `off` | Disable automatic server summaries. | `app/plugins/commands_modular/resoconto.py:905` |
| `resocontoserver` | `—` | `oggi` | Show manual server summary for today. | `app/plugins/commands_modular/resoconto.py:1102` |
| `resocontoserver` | `—` | `on` | Enable automatic server summaries. | `app/plugins/commands_modular/resoconto.py:888` |
| `resocontoserver` | `—` | `range` | Show manual server summary for a range. | `app/plugins/commands_modular/resoconto.py:1195` |
| `resocontoserver` | `—` | `schedule_add` | Add a server summary schedule. | `app/plugins/commands_modular/resoconto.py:964` |
| `resocontoserver` | `—` | `schedule_edit` | Edit a server summary schedule. | `app/plugins/commands_modular/resoconto.py:992` |
| `resocontoserver` | `—` | `schedule_list` | List server summary schedules. | `app/plugins/commands_modular/resoconto.py:1080` |
| `resocontoserver` | `—` | `schedule_remove` | Remove a server summary schedule. | `app/plugins/commands_modular/resoconto.py:1041` |
| `resocontoserver` | `—` | `schedule_show` | Show one server summary schedule. | `app/plugins/commands_modular/resoconto.py:1061` |
| `resocontoserver` | `—` | `status` | Show the server summary schedule status. | `app/plugins/commands_modular/resoconto.py:921` |
| `resocontoserver` | `—` | `ultimi` | Show manual server summary for the last window. | `app/plugins/commands_modular/resoconto.py:1156` |
| `riassunto` | `—` | `off` | Disable DM channel summary in this channel. | `app/plugins/commands_modular/riassunto.py:2166` |
| `riassunto` | `—` | `on` | Enable DM channel summary in this channel. | `app/plugins/commands_modular/riassunto.py:2162` |
| `riassunto` | `—` | `status` | Show DM channel summary status in this channel. | `app/plugins/commands_modular/riassunto.py:2170` |
| `status` | `—` | `mood_reset` | Reset the Barcello mood for this channel. | `app/plugins/commands_modular/status.py:204` |
| `status` | `—` | `mood_set` | Set the Barcello mood for this channel. | `app/plugins/commands_modular/status.py:144` |
| `status` | `—` | `mood_show` | Show the Barcello mood for this channel. | `app/plugins/commands_modular/status.py:198` |
| `status` | `—` | `show` | Show the Barcellometro status. | `app/plugins/commands_modular/status.py:102` |
| `tempban` | `—` | `tempban` | Alias of /users tempban. | `app/plugins/commands_modular/moderazione_utenti.py:1892` |
| `triggers` | `barcello` | `calibrate` | Recalculate Barcello calibration weights. | `app/plugins/commands_modular/barcello.py:625` |
| `triggers` | `barcello` | `off` | Disable Barcello triggers in the current channel. | `app/plugins/commands_modular/barcello.py:617` |
| `triggers` | `barcello` | `on` | Enable Barcello triggers in the current channel. | `app/plugins/commands_modular/barcello.py:613` |
| `triggers` | `barcello` | `quiet_reset` | Rimuove quiet hours Barcello dal canale corrente. | `app/plugins/commands_modular/barcello.py:581` |
| `triggers` | `barcello` | `quiet_set` | Imposta quiet hours per schedule Barcello nel canale corrente. | `app/plugins/commands_modular/barcello.py:507` |
| `triggers` | `barcello` | `quiet_show` | Mostra quiet hours Barcello del canale corrente. | `app/plugins/commands_modular/barcello.py:543` |
| `triggers` | `barcello` | `run` | Run the Barcello analysis. | `app/plugins/commands_modular/barcello.py:2180` |
| `triggers` | `barcello` | `schedule_add` | Aggiunge una schedule Barcello per questo canale. | `app/plugins/commands_modular/barcello.py:241` |
| `triggers` | `barcello` | `schedule_edit` | Modifica una schedule Barcello del canale corrente. | `app/plugins/commands_modular/barcello.py:310` |
| `triggers` | `barcello` | `schedule_list` | Elenca le schedule Barcello del canale corrente. | `app/plugins/commands_modular/barcello.py:477` |
| `triggers` | `barcello` | `schedule_remove` | Rimuove una schedule Barcello del canale corrente. | `app/plugins/commands_modular/barcello.py:395` |
| `triggers` | `barcello` | `schedule_show` | Mostra i dettagli di una schedule Barcello del canale corrente. | `app/plugins/commands_modular/barcello.py:433` |
| `triggers` | `barcello` | `status` | Show Barcello trigger status for the current channel. | `app/plugins/commands_modular/barcello.py:621` |
| `triggers` | `phrases` | `entry_add` | Add a phrase trigger entry | `app/plugins/commands_modular/triggers.py:328` |
| `triggers` | `phrases` | `entry_edit` | Edit a phrase trigger entry | `app/plugins/commands_modular/triggers.py:437` |
| `triggers` | `phrases` | `entry_list` | List phrase trigger entries | `app/plugins/commands_modular/triggers.py:383` |
| `triggers` | `phrases` | `entry_remove` | Remove a phrase trigger entry | `app/plugins/commands_modular/triggers.py:370` |
| `triggers` | `phrases` | `entry_show` | Show a phrase trigger entry | `app/plugins/commands_modular/triggers.py:396` |
| `triggers` | `phrases` | `off` | Disable phrase triggers | `app/plugins/commands_modular/triggers.py:312` |
| `triggers` | `phrases` | `on` | Enable phrase triggers | `app/plugins/commands_modular/triggers.py:308` |
| `triggers` | `phrases` | `status` | Show phrase trigger status | `app/plugins/commands_modular/triggers.py:316` |
| `triggers` | `phrases` | `template_global_reset` | Reset the global phrase template | `app/plugins/commands_modular/triggers.py:580` |
| `triggers` | `phrases` | `template_global_set` | Set the global phrase template | `app/plugins/commands_modular/triggers.py:553` |
| `triggers` | `phrases` | `template_global_show` | Show the global phrase template | `app/plugins/commands_modular/triggers.py:567` |
| `triggers` | `phrases` | `template_milestone_reset` | Reset all milestone templates | `app/plugins/commands_modular/triggers.py:540` |
| `triggers` | `phrases` | `template_milestone_set` | Create or update a milestone template | `app/plugins/commands_modular/triggers.py:510` |
| `triggers` | `phrases` | `template_milestone_show` | Show milestone templates | `app/plugins/commands_modular/triggers.py:527` |
| `triggers` | `phrases` | `template_user_reset` | Reset a user-specific phrase template | `app/plugins/commands_modular/triggers.py:628` |
| `triggers` | `phrases` | `template_user_set` | Set a user-specific phrase template | `app/plugins/commands_modular/triggers.py:598` |
| `triggers` | `phrases` | `template_user_show` | Show a user-specific phrase template | `app/plugins/commands_modular/triggers.py:615` |
| `users` | `aura` | `off` | Disable the Aura program for this server. | `app/plugins/commands_modular/moderazione_utenti.py:1584` |
| `users` | `aura` | `on` | Enable the Aura program for this server. | `app/plugins/commands_modular/moderazione_utenti.py:1574` |
| `users` | `aura` | `policy_reset` | Reset Aura policy fields to defaults. | `app/plugins/commands_modular/moderazione_utenti.py:1677` |
| `users` | `aura` | `policy_set` | Update Aura eligibility policy fields. | `app/plugins/commands_modular/moderazione_utenti.py:1611` |
| `users` | `aura` | `policy_show` | Show one Aura policy field or the full policy. | `app/plugins/commands_modular/moderazione_utenti.py:1656` |
| `users` | `aura` | `status` | Show Aura runtime status and policy. | `app/plugins/commands_modular/moderazione_utenti.py:1594` |
| `users` | `—` | `ban` | Ban a user permanently. | `app/plugins/commands_modular/moderazione_utenti.py:1110` |
| `users` | `—` | `ban_list` | List active permanent bans. | `app/plugins/commands_modular/moderazione_utenti.py:1117` |
| `users` | `dms` | `cooldown_reset` | Reset the DM cooldown for USERS contexts. | `app/plugins/commands_modular/moderazione_utenti.py:1506` |
| `users` | `dms` | `cooldown_set` | Set the DM cooldown for USERS contexts. | `app/plugins/commands_modular/moderazione_utenti.py:1464` |
| `users` | `dms` | `cooldown_show` | Show the DM cooldown for USERS contexts. | `app/plugins/commands_modular/moderazione_utenti.py:1487` |
| `users` | `dms` | `invite_reset` | Reset the invite link used in USERS DMs. | `app/plugins/commands_modular/moderazione_utenti.py:1533` |
| `users` | `dms` | `invite_set` | Set the invite link used in USERS DMs. | `app/plugins/commands_modular/moderazione_utenti.py:1519` |
| `users` | `dms` | `invite_show` | Show the invite link used in USERS DMs. | `app/plugins/commands_modular/moderazione_utenti.py:1526` |
| `users` | `dms` | `off` | Disable USERS DMs for manual grace and auto-tempban. | `app/plugins/commands_modular/moderazione_utenti.py:1239` |
| `users` | `dms` | `on` | Enable USERS DMs for manual grace and auto-tempban. | `app/plugins/commands_modular/moderazione_utenti.py:1232` |
| `users` | `dms` | `status` | Show USERS DM status and delivery metrics. | `app/plugins/commands_modular/moderazione_utenti.py:1246` |
| `users` | `dms` | `template_ban_reset` | Reset the DM template for ban events. | `app/plugins/commands_modular/moderazione_utenti.py:1455` |
| `users` | `dms` | `template_ban_set` | Set the DM template for ban events. | `app/plugins/commands_modular/moderazione_utenti.py:1422` |
| `users` | `dms` | `template_ban_show` | Show the DM template for ban events. | `app/plugins/commands_modular/moderazione_utenti.py:1438` |
| `users` | `dms` | `template_grace_reset` | Reset the DM template for manual grace entry. | `app/plugins/commands_modular/moderazione_utenti.py:1332` |
| `users` | `dms` | `template_grace_set` | Set the DM template for manual grace entry. | `app/plugins/commands_modular/moderazione_utenti.py:1299` |
| `users` | `dms` | `template_grace_show` | Show the DM template for manual grace entry. | `app/plugins/commands_modular/moderazione_utenti.py:1315` |
| `users` | `dms` | `template_kick_reset` | Reset the DM template for kick events. | `app/plugins/commands_modular/moderazione_utenti.py:1414` |
| `users` | `dms` | `template_kick_set` | Set the DM template for kick events. | `app/plugins/commands_modular/moderazione_utenti.py:1381` |
| `users` | `dms` | `template_kick_show` | Show the DM template for kick events. | `app/plugins/commands_modular/moderazione_utenti.py:1397` |
| `users` | `dms` | `template_tempban_reset` | Reset the DM template for auto-tempban after manual grace. | `app/plugins/commands_modular/moderazione_utenti.py:1373` |
| `users` | `dms` | `template_tempban_set` | Set the DM template for auto-tempban after manual grace. | `app/plugins/commands_modular/moderazione_utenti.py:1340` |
| `users` | `dms` | `template_tempban_show` | Show the DM template for auto-tempban after manual grace. | `app/plugins/commands_modular/moderazione_utenti.py:1356` |
| `users` | `grace` | `manual` | Assign a manual grace period to a user. | `app/plugins/commands_modular/moderazione_utenti.py:1706` |
| `users` | `grace` | `tempban_reset` | Disable the automatic tempban applied after manual grace. | `app/plugins/commands_modular/moderazione_utenti.py:1750` |
| `users` | `grace` | `tempban_set` | Set the default tempban applied when a manual grace expires. | `app/plugins/commands_modular/moderazione_utenti.py:1721` |
| `users` | `grace` | `tempban_show` | Show the default tempban applied when a manual grace expires. | `app/plugins/commands_modular/moderazione_utenti.py:1739` |
| `users` | `—` | `grace_list` | List active grace periods. | `app/plugins/commands_modular/moderazione_utenti.py:1764` |
| `users` | `—` | `ieri` | Revoca le azioni create ieri. | `app/plugins/commands_modular/moderazione_utenti.py:1817` |
| `users` | `—` | `kick` | Remove a user from the server. | `app/plugins/commands_modular/moderazione_utenti.py:1097` |
| `users` | `—` | `kick_list` | List recent user removals. | `app/plugins/commands_modular/moderazione_utenti.py:1104` |
| `users` | `—` | `oggi` | Revoca le azioni create oggi. | `app/plugins/commands_modular/moderazione_utenti.py:1812` |
| `users` | `—` | `range` | Revoca le azioni create in un intervallo esplicito. | `app/plugins/commands_modular/moderazione_utenti.py:1838` |
| `users` | `—` | `tempban` | Ban a user temporarily. | `app/plugins/commands_modular/moderazione_utenti.py:1213` |
| `users` | `—` | `tempban_list` | List active temporary bans. | `app/plugins/commands_modular/moderazione_utenti.py:1226` |
| `users` | `—` | `ultimi` | Revoca le azioni create nella finestra mobile. | `app/plugins/commands_modular/moderazione_utenti.py:1824` |
| `users` | `unban` | `last` | Revoke bans created in the last rolling window. | `app/plugins/commands_modular/moderazione_utenti.py:1141` |
| `users` | `unban` | `range` | Revoke bans created in an explicit range. | `app/plugins/commands_modular/moderazione_utenti.py:1156` |
| `users` | `unban` | `today` | Revoke bans created today. | `app/plugins/commands_modular/moderazione_utenti.py:1130` |
| `users` | `unban` | `yesterday` | Revoke bans created yesterday. | `app/plugins/commands_modular/moderazione_utenti.py:1135` |
| `users` | `ungrace` | `last` | Revoke grace periods created in the last rolling window. | `app/plugins/commands_modular/moderazione_utenti.py:1782` |
| `users` | `ungrace` | `range` | Revoke grace periods created in an explicit range. | `app/plugins/commands_modular/moderazione_utenti.py:1797` |
| `users` | `ungrace` | `today` | Revoke grace periods created today. | `app/plugins/commands_modular/moderazione_utenti.py:1771` |
| `users` | `ungrace` | `yesterday` | Revoke grace periods created yesterday. | `app/plugins/commands_modular/moderazione_utenti.py:1776` |
| `users` | `untempban` | `last` | Revoke temporary bans created in the last rolling window. | `app/plugins/commands_modular/moderazione_utenti.py:1180` |
| `users` | `untempban` | `range` | Revoke temporary bans created in an explicit range. | `app/plugins/commands_modular/moderazione_utenti.py:1195` |
| `users` | `untempban` | `today` | Revoke temporary bans created today. | `app/plugins/commands_modular/moderazione_utenti.py:1169` |
| `users` | `untempban` | `yesterday` | Revoke temporary bans created yesterday. | `app/plugins/commands_modular/moderazione_utenti.py:1174` |
| `voice_ingest` | `—` | `join` | Join a voice channel manually. | `app/plugins/commands_modular/voice_ingest.py:24` |
| `voice_ingest` | `—` | `leave` | Leave the current voice channel manually. | `app/plugins/commands_modular/voice_ingest.py:48` |

## Issues

- **WARNING localized_description** — `triggers.barcello.quiet_reset`: Command description looks non-English. (`app/plugins/commands_modular/barcello.py:581`)
- **WARNING localized_description** — `triggers.barcello.quiet_set`: Command description looks non-English. (`app/plugins/commands_modular/barcello.py:507`)
- **WARNING localized_description** — `triggers.barcello.quiet_show`: Command description looks non-English. (`app/plugins/commands_modular/barcello.py:543`)
- **WARNING localized_description** — `triggers.barcello.schedule_add`: Command description looks non-English. (`app/plugins/commands_modular/barcello.py:241`)
- **WARNING localized_description** — `triggers.barcello.schedule_edit`: Command description looks non-English. (`app/plugins/commands_modular/barcello.py:310`)
- **WARNING localized_description** — `triggers.barcello.schedule_list`: Command description looks non-English. (`app/plugins/commands_modular/barcello.py:477`)
- **WARNING localized_description** — `triggers.barcello.schedule_remove`: Command description looks non-English. (`app/plugins/commands_modular/barcello.py:395`)
- **WARNING localized_description** — `triggers.barcello.schedule_show`: Command description looks non-English. (`app/plugins/commands_modular/barcello.py:433`)
- **WARNING localized_description** — `users.ieri`: Command description looks non-English. (`app/plugins/commands_modular/moderazione_utenti.py:1817`)
- **WARNING localized_description** — `users.oggi`: Command description looks non-English. (`app/plugins/commands_modular/moderazione_utenti.py:1812`)
- **WARNING missing_param_description** — `barcello.intervallo`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/barcello.py:2429`)
- **WARNING missing_param_description** — `barcello.intervallo`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/barcello.py:2429`)
- **WARNING missing_param_description** — `barcello.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/barcello.py:2419`)
- **WARNING missing_param_description** — `barcello.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/barcello.py:2419`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.last`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/barcello.py:2359`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.last`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/barcello.py:2360`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.last`: Parameter 'user1' is missing a description. (`app/plugins/commands_modular/barcello.py:2361`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.last`: Parameter 'user2' is missing a description. (`app/plugins/commands_modular/barcello.py:2362`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/barcello.py:2378`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/barcello.py:2379`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.range`: Parameter 'user1' is missing a description. (`app/plugins/commands_modular/barcello.py:2380`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.range`: Parameter 'user2' is missing a description. (`app/plugins/commands_modular/barcello.py:2381`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.today`: Parameter 'user1' is missing a description. (`app/plugins/commands_modular/barcello.py:2325`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.today`: Parameter 'user2' is missing a description. (`app/plugins/commands_modular/barcello.py:2325`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.yesterday`: Parameter 'user1' is missing a description. (`app/plugins/commands_modular/barcello.py:2337`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.yesterday`: Parameter 'user2' is missing a description. (`app/plugins/commands_modular/barcello.py:2337`)
- **WARNING missing_param_description** — `inactivity.dms.template_grace_set`: Parameter 'text' is missing a description. (`app/plugins/commands_modular/inattivi.py:393`)
- **WARNING missing_param_description** — `inactivity.dms.template_tempban_set`: Parameter 'text' is missing a description. (`app/plugins/commands_modular/inattivi.py:495`)
- **WARNING missing_param_description** — `resocontocanale.aura.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/resoconto.py:872`)
- **WARNING missing_param_description** — `resocontocanale.aura.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/resoconto.py:872`)
- **WARNING missing_param_description** — `resocontocanale.aura.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/resoconto.py:840`)
- **WARNING missing_param_description** — `resocontocanale.aura.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/resoconto.py:840`)
- **WARNING missing_param_description** — `resocontocanale.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/resoconto.py:856`)
- **WARNING missing_param_description** — `resocontocanale.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/resoconto.py:856`)
- **WARNING missing_param_description** — `resocontocanale.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/resoconto.py:816`)
- **WARNING missing_param_description** — `resocontocanale.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/resoconto.py:816`)
- **WARNING missing_param_description** — `resocontoserver.aura.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/resoconto.py:1211`)
- **WARNING missing_param_description** — `resocontoserver.aura.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/resoconto.py:1211`)
- **WARNING missing_param_description** — `resocontoserver.aura.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/resoconto.py:1180`)
- **WARNING missing_param_description** — `resocontoserver.aura.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/resoconto.py:1180`)
- **WARNING missing_param_description** — `resocontoserver.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/resoconto.py:1195`)
- **WARNING missing_param_description** — `resocontoserver.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/resoconto.py:1195`)
- **WARNING missing_param_description** — `resocontoserver.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/resoconto.py:1156`)
- **WARNING missing_param_description** — `resocontoserver.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/resoconto.py:1156`)
- **WARNING missing_param_description** — `users.dms.template_ban_set`: Parameter 'text' is missing a description. (`app/plugins/commands_modular/moderazione_utenti.py:1422`)
- **WARNING missing_param_description** — `users.dms.template_grace_set`: Parameter 'text' is missing a description. (`app/plugins/commands_modular/moderazione_utenti.py:1299`)
- **WARNING missing_param_description** — `users.dms.template_kick_set`: Parameter 'text' is missing a description. (`app/plugins/commands_modular/moderazione_utenti.py:1381`)
- **WARNING missing_param_description** — `users.dms.template_tempban_set`: Parameter 'text' is missing a description. (`app/plugins/commands_modular/moderazione_utenti.py:1340`)
- **WARNING required_param** — `ai.fallback_set`: Parameter 'model' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/admin.py:466`)
- **WARNING required_param** — `ai.model_set`: Parameter 'model' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/admin.py:434`)
- **WARNING required_param** — `campaigns.cap.limits_set`: Parameter 'daily_limit' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/messaggi.py:588`)
- **WARNING required_param** — `campaigns.insights.template_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:1027`)
- **WARNING required_param** — `campaigns.prompt.schedule_show`: Parameter 'id_or_name' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:755`)
- **WARNING required_param** — `campaigns.quiet.range_set`: Parameter 'start' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/messaggi.py:541`)
- **WARNING required_param** — `campaigns.quiet.range_set`: Parameter 'end' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/messaggi.py:541`)
- **WARNING required_param** — `embed.description.template_service_set`: Parameter 'template' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/embed.py:870`)
- **WARNING required_param** — `inactivity.dms.cooldown_set`: Parameter 'quantity' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:536`)
- **WARNING required_param** — `inactivity.dms.cooldown_set`: Parameter 'unit' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:537`)
- **WARNING required_param** — `inactivity.dms.invite_set`: Parameter 'url' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:588`)
- **WARNING required_param** — `inactivity.dms.template_grace_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:393`)
- **WARNING required_param** — `inactivity.dms.template_tempban_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:495`)
- **WARNING required_param** — `inactivity.grace.limits_set`: Parameter 'days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:323`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'inactive_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:618`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'window_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:619`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'min_messages' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:620`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'mode' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:621`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'inactive_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:662`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'window_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:663`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'min_messages' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:664`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'mode' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:665`)
- **WARNING required_param** — `inactivity.tempban.limits_set`: Parameter 'days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:370`)
- **WARNING required_param** — `qna.bonus_set`: Parameter 'amount' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:964`)
- **WARNING required_param** — `qna.limits_set`: Parameter 'tier' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:933`)
- **WARNING required_param** — `qna.limits_set`: Parameter 'limit' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:933`)
- **WARNING required_param** — `status.mood_set`: Parameter 'value' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/status.py:144`)
- **WARNING required_param** — `triggers.barcello.quiet_set`: Parameter 'start' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/barcello.py:507`)
- **WARNING required_param** — `triggers.barcello.quiet_set`: Parameter 'end' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/barcello.py:507`)
- **WARNING required_param** — `triggers.phrases.template_global_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:553`)
- **WARNING required_param** — `triggers.phrases.template_milestone_set`: Parameter 'threshold' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:510`)
- **WARNING required_param** — `triggers.phrases.template_milestone_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:510`)
- **WARNING required_param** — `triggers.phrases.template_user_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:598`)
- **WARNING required_param** — `users.dms.cooldown_set`: Parameter 'quantity' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/moderazione_utenti.py:1466`)
- **WARNING required_param** — `users.dms.cooldown_set`: Parameter 'unit' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/moderazione_utenti.py:1467`)
- **WARNING required_param** — `users.dms.invite_set`: Parameter 'url' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/moderazione_utenti.py:1519`)
- **WARNING required_param** — `users.dms.template_ban_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/moderazione_utenti.py:1422`)
- **WARNING required_param** — `users.dms.template_grace_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/moderazione_utenti.py:1299`)
- **WARNING required_param** — `users.dms.template_kick_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/moderazione_utenti.py:1381`)
- **WARNING required_param** — `users.dms.template_tempban_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/moderazione_utenti.py:1340`)
- **WARNING required_param** — `users.grace.tempban_set`: Parameter 'quantity' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/moderazione_utenti.py:1723`)
- **WARNING required_param** — `users.grace.tempban_set`: Parameter 'unit' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/moderazione_utenti.py:1724`)

## Localized exceptions

The following commands remain intentionally localized and are excluded from the English-only rule for now:
- `attivita.off`
- `attivita.on`
- `attivita.status`
- `aura.off`
- `aura.on`
- `aura.status`
- `barcello.ieri`
- `barcello.intervallo`
- `barcello.oggi`
- `barcello.ultimi`
- `dmchannelsummary.barcello.last`
- `dmchannelsummary.barcello.range`
- `dmchannelsummary.barcello.today`
- `dmchannelsummary.barcello.yesterday`
- `resocontocanale.aura.ieri`
- `resocontocanale.aura.oggi`
- `resocontocanale.aura.range`
- `resocontocanale.aura.ultimi`
- `resocontocanale.ieri`
- `resocontocanale.off`
- `resocontocanale.oggi`
- `resocontocanale.on`
- `resocontocanale.range`
- `resocontocanale.schedule_add`
- `resocontocanale.schedule_edit`
- `resocontocanale.schedule_list`
- `resocontocanale.schedule_remove`
- `resocontocanale.schedule_show`
- `resocontocanale.status`
- `resocontocanale.ultimi`
- `resocontoserver.aura.ieri`
- `resocontoserver.aura.oggi`
- `resocontoserver.aura.range`
- `resocontoserver.aura.ultimi`
- `resocontoserver.ieri`
- `resocontoserver.off`
- `resocontoserver.oggi`
- `resocontoserver.on`
- `resocontoserver.range`
- `resocontoserver.schedule_add`
- `resocontoserver.schedule_edit`
- `resocontoserver.schedule_list`
- `resocontoserver.schedule_remove`
- `resocontoserver.schedule_show`
- `resocontoserver.status`
- `resocontoserver.ultimi`
- `riassunto.off`
- `riassunto.on`
- `riassunto.status`

## Usage

- Run `python -m scripts.validate_commands` for a console report.
- Run `python -m scripts.validate_commands --write-report` to refresh this markdown file.
- Run `pytest tests/test_command_standard_validator.py` to fail CI on validator errors.
