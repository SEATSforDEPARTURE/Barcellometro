# Command Tree Validation Report

Questo report inventaria i comandi realmente registrati nel repository. Per il vocabolario canonico delle action e la loro semantica normativa fa fede `docs/command_standards.md`; le action composte (`config_set`, `schedule_add`, `template_global_reset`, ecc.) vanno lette come estensioni dei verbi canonici e non introducono nuove action standard.

- Commands discovered: **332**
- Errors: **0**
- Warnings: **62**

## Inventory

| Root | Subgroup | Action | Description | Source |
| --- | --- | --- | --- | --- |
| `ai` | `—` | `fallback_reset` | Reset the AI fallback model override for a task. | `app/plugins/commands_modular/admin.py:487` |
| `ai` | `—` | `fallback_set` | Set the AI fallback model for a task. | `app/plugins/commands_modular/admin.py:465` |
| `ai` | `—` | `fallback_show` | Show configured AI fallback models. | `app/plugins/commands_modular/admin.py:477` |
| `ai` | `—` | `model_reset` | Reset the AI model override for a task. | `app/plugins/commands_modular/admin.py:455` |
| `ai` | `—` | `model_set` | Set the AI model for a task. | `app/plugins/commands_modular/admin.py:433` |
| `ai` | `—` | `model_show` | Show configured AI models. | `app/plugins/commands_modular/admin.py:445` |
| `ai` | `—` | `off` | Disable the AI service. | `app/plugins/commands_modular/admin.py:398` |
| `ai` | `—` | `on` | Enable the AI service. | `app/plugins/commands_modular/admin.py:391` |
| `ai` | `—` | `run` | Run an AI test prompt. | `app/plugins/commands_modular/admin.py:496` |
| `ai` | `—` | `status` | Show AI service status. | `app/plugins/commands_modular/admin.py:405` |
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
| `ban` | `—` | `ban` | Alias of /users ban. | `app/plugins/commands_modular/moderazione_utenti.py:1017` |
| `barcello` | `—` | `ieri` | Mostra lo stato del barcello di ieri (in DM) | `app/plugins/commands_modular/barcello.py:1906` |
| `barcello` | `—` | `intervallo` | Mostra lo stato del barcello per intervallo. | `app/plugins/commands_modular/barcello.py:1933` |
| `barcello` | `—` | `oggi` | Mostra lo stato del barcello di oggi (in DM) | `app/plugins/commands_modular/barcello.py:1898` |
| `barcello` | `—` | `ultimi` | Mostra lo stato del barcello per gli ultimi N periodi. | `app/plugins/commands_modular/barcello.py:1923` |
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
| `database` | `backfill` | `limits_reset` | Reset backfill limits to defaults. | `app/plugins/commands_modular/admin.py:345` |
| `database` | `backfill` | `limits_set` | Update backfill limits. | `app/plugins/commands_modular/admin.py:294` |
| `database` | `backfill` | `limits_show` | Show backfill limits. | `app/plugins/commands_modular/admin.py:332` |
| `database` | `backfill` | `off` | Disable backfill. | `app/plugins/commands_modular/admin.py:271` |
| `database` | `backfill` | `on` | Enable backfill. | `app/plugins/commands_modular/admin.py:264` |
| `database` | `backfill` | `run` | Run backfill now. | `app/plugins/commands_modular/admin.py:361` |
| `database` | `backfill` | `status` | Show backfill status. | `app/plugins/commands_modular/admin.py:278` |
| `database` | `events` | `off` | Disable event collection for this channel. | `app/plugins/commands_modular/admin.py:155` |
| `database` | `events` | `on` | Enable event collection for this channel. | `app/plugins/commands_modular/admin.py:149` |
| `database` | `events` | `status` | Show event collection status for this channel. | `app/plugins/commands_modular/admin.py:161` |
| `database` | `retention` | `limits_reset` | Reset retention limits to defaults. | `app/plugins/commands_modular/admin.py:248` |
| `database` | `retention` | `limits_set` | Update retention limits. | `app/plugins/commands_modular/admin.py:197` |
| `database` | `retention` | `limits_show` | Show retention limits. | `app/plugins/commands_modular/admin.py:235` |
| `database` | `retention` | `off` | Disable the retention task. | `app/plugins/commands_modular/admin.py:174` |
| `database` | `retention` | `on` | Enable the retention task. | `app/plugins/commands_modular/admin.py:167` |
| `database` | `retention` | `status` | Show retention status. | `app/plugins/commands_modular/admin.py:181` |
| `dmchannelsummary` | `barcello` | `last` | Run Barcello summary for the last N units. | `app/plugins/commands_modular/barcello.py:1861` |
| `dmchannelsummary` | `barcello` | `off` | Disable Barcello DM summary in this channel. | `app/plugins/commands_modular/barcello.py:1820` |
| `dmchannelsummary` | `barcello` | `on` | Enable Barcello DM summary in this channel. | `app/plugins/commands_modular/barcello.py:1816` |
| `dmchannelsummary` | `barcello` | `range` | Run Barcello summary for a custom range. | `app/plugins/commands_modular/barcello.py:1880` |
| `dmchannelsummary` | `barcello` | `status` | Show Barcello DM summary status in this channel. | `app/plugins/commands_modular/barcello.py:1824` |
| `dmchannelsummary` | `barcello` | `today` | Run Barcello summary for today. | `app/plugins/commands_modular/barcello.py:1828` |
| `dmchannelsummary` | `barcello` | `yesterday` | Run Barcello summary for yesterday. | `app/plugins/commands_modular/barcello.py:1840` |
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
| `grace` | `—` | `grace` | Alias of /users grace. | `app/plugins/commands_modular/moderazione_utenti.py:1067` |
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
| `inactivity` | `autokick` | `off` | Disable automatic inactivity actions. | `app/plugins/commands_modular/inattivi.py:226` |
| `inactivity` | `autokick` | `on` | Enable automatic inactivity actions. | `app/plugins/commands_modular/inattivi.py:219` |
| `inactivity` | `autokick` | `status` | Show the automatic inactivity action status. | `app/plugins/commands_modular/inattivi.py:233` |
| `inactivity` | `dms` | `cooldown_reset` | Reset the reminder DM cooldown. | `app/plugins/commands_modular/inattivi.py:378` |
| `inactivity` | `dms` | `cooldown_set` | Set the reminder DM cooldown. | `app/plugins/commands_modular/inattivi.py:364` |
| `inactivity` | `dms` | `cooldown_show` | Show the reminder DM cooldown. | `app/plugins/commands_modular/inattivi.py:371` |
| `inactivity` | `dms` | `invite_reset` | Reset the invite link used in inactivity DMs. | `app/plugins/commands_modular/inattivi.py:403` |
| `inactivity` | `dms` | `invite_set` | Set the invite link used in inactivity DMs. | `app/plugins/commands_modular/inattivi.py:389` |
| `inactivity` | `dms` | `invite_show` | Show the invite link used in inactivity DMs. | `app/plugins/commands_modular/inattivi.py:396` |
| `inactivity` | `dms` | `template_reminder_reset` | Reset the reminder DM template. | `app/plugins/commands_modular/inattivi.py:356` |
| `inactivity` | `dms` | `template_reminder_set` | Set the reminder DM template. | `app/plugins/commands_modular/inattivi.py:335` |
| `inactivity` | `dms` | `template_reminder_show` | Show the reminder DM template. | `app/plugins/commands_modular/inattivi.py:342` |
| `inactivity` | `grace` | `limits_reset` | Reset the inactivity grace period limits. | `app/plugins/commands_modular/inattivi.py:280` |
| `inactivity` | `grace` | `limits_set` | Set the inactivity grace period limits. | `app/plugins/commands_modular/inattivi.py:265` |
| `inactivity` | `grace` | `limits_show` | Show the inactivity grace period limits. | `app/plugins/commands_modular/inattivi.py:272` |
| `inactivity` | `grace` | `off` | Disable the inactivity grace period. | `app/plugins/commands_modular/inattivi.py:249` |
| `inactivity` | `grace` | `on` | Enable the inactivity grace period. | `app/plugins/commands_modular/inattivi.py:240` |
| `inactivity` | `grace` | `status` | Show the inactivity grace period status. | `app/plugins/commands_modular/inattivi.py:256` |
| `inactivity` | `—` | `off` | Disable inactivity moderation. | `app/plugins/commands_modular/inattivi.py:180` |
| `inactivity` | `—` | `on` | Enable inactivity moderation. | `app/plugins/commands_modular/inattivi.py:173` |
| `inactivity` | `policy` | `default_reset` | Reset the default inactivity policy. | `app/plugins/commands_modular/inattivi.py:444` |
| `inactivity` | `policy` | `default_set` | Set the default inactivity policy. | `app/plugins/commands_modular/inattivi.py:417` |
| `inactivity` | `policy` | `default_show` | Show the default inactivity policy. | `app/plugins/commands_modular/inattivi.py:436` |
| `inactivity` | `policy` | `exceptions_add` | Add a role to the inactivity exception list. | `app/plugins/commands_modular/inattivi.py:503` |
| `inactivity` | `policy` | `exceptions_list` | List all inactivity exception roles. | `app/plugins/commands_modular/inattivi.py:540` |
| `inactivity` | `policy` | `exceptions_remove` | Remove a role from the inactivity exception list. | `app/plugins/commands_modular/inattivi.py:517` |
| `inactivity` | `policy` | `exceptions_show` | Show whether a role is excluded from inactivity moderation. | `app/plugins/commands_modular/inattivi.py:531` |
| `inactivity` | `policy` | `role_reset` | Reset an inactivity policy for a role. | `app/plugins/commands_modular/inattivi.py:495` |
| `inactivity` | `policy` | `role_set` | Set an inactivity policy for a role. | `app/plugins/commands_modular/inattivi.py:460` |
| `inactivity` | `policy` | `role_show` | Show an inactivity policy for a role. | `app/plugins/commands_modular/inattivi.py:482` |
| `inactivity` | `—` | `run` | Run the inactivity moderation scan now. | `app/plugins/commands_modular/inattivi.py:555` |
| `inactivity` | `—` | `status` | Show the inactivity moderation status. | `app/plugins/commands_modular/inattivi.py:187` |
| `inactivity` | `tempban` | `limits_reset` | Reset the inactivity tempban limits. | `app/plugins/commands_modular/inattivi.py:327` |
| `inactivity` | `tempban` | `limits_set` | Set the inactivity tempban limits. | `app/plugins/commands_modular/inattivi.py:312` |
| `inactivity` | `tempban` | `limits_show` | Show the inactivity tempban limits. | `app/plugins/commands_modular/inattivi.py:319` |
| `inactivity` | `tempban` | `off` | Disable temporary bans after inactivity kicks. | `app/plugins/commands_modular/inattivi.py:296` |
| `inactivity` | `tempban` | `on` | Enable temporary bans after inactivity kicks. | `app/plugins/commands_modular/inattivi.py:287` |
| `inactivity` | `tempban` | `status` | Show the inactivity tempban status. | `app/plugins/commands_modular/inattivi.py:303` |
| `kick` | `—` | `kick` | Alias of /users kick. | `app/plugins/commands_modular/moderazione_utenti.py:1012` |
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
| `resocontocanale` | `aura` | `ieri` | Show manual channel aura details for yesterday. | `app/plugins/commands_modular/resoconto.py:797` |
| `resocontocanale` | `aura` | `oggi` | Show manual channel aura details for today. | `app/plugins/commands_modular/resoconto.py:773` |
| `resocontocanale` | `aura` | `range` | Show manual channel aura details for a range. | `app/plugins/commands_modular/resoconto.py:873` |
| `resocontocanale` | `aura` | `ultimi` | Show manual channel aura details for the last window. | `app/plugins/commands_modular/resoconto.py:841` |
| `resocontocanale` | `—` | `ieri` | Show manual channel summary for yesterday. | `app/plugins/commands_modular/resoconto.py:785` |
| `resocontocanale` | `—` | `off` | Disable automatic channel summaries for the current channel. | `app/plugins/commands_modular/resoconto.py:551` |
| `resocontocanale` | `—` | `oggi` | Show manual channel summary for today. | `app/plugins/commands_modular/resoconto.py:761` |
| `resocontocanale` | `—` | `on` | Enable automatic channel summaries for the current channel. | `app/plugins/commands_modular/resoconto.py:535` |
| `resocontocanale` | `—` | `range` | Show manual channel summary for a range. | `app/plugins/commands_modular/resoconto.py:857` |
| `resocontocanale` | `—` | `schedule_add` | Add a channel summary schedule. | `app/plugins/commands_modular/resoconto.py:610` |
| `resocontocanale` | `—` | `schedule_edit` | Edit a channel summary schedule. | `app/plugins/commands_modular/resoconto.py:638` |
| `resocontocanale` | `—` | `schedule_list` | List channel summary schedules for the current channel. | `app/plugins/commands_modular/resoconto.py:739` |
| `resocontocanale` | `—` | `schedule_remove` | Remove a channel summary schedule. | `app/plugins/commands_modular/resoconto.py:692` |
| `resocontocanale` | `—` | `schedule_show` | Show one channel summary schedule. | `app/plugins/commands_modular/resoconto.py:716` |
| `resocontocanale` | `—` | `status` | Show the channel summary schedule status. | `app/plugins/commands_modular/resoconto.py:567` |
| `resocontocanale` | `—` | `ultimi` | Show manual channel summary for the last window. | `app/plugins/commands_modular/resoconto.py:817` |
| `resocontoserver` | `aura` | `ieri` | Show manual server aura details for yesterday. | `app/plugins/commands_modular/resoconto.py:1138` |
| `resocontoserver` | `aura` | `oggi` | Show manual server aura details for today. | `app/plugins/commands_modular/resoconto.py:1115` |
| `resocontoserver` | `aura` | `range` | Show manual server aura details for a range. | `app/plugins/commands_modular/resoconto.py:1212` |
| `resocontoserver` | `aura` | `ultimi` | Show manual server aura details for the last window. | `app/plugins/commands_modular/resoconto.py:1181` |
| `resocontoserver` | `—` | `ieri` | Show manual server summary for yesterday. | `app/plugins/commands_modular/resoconto.py:1126` |
| `resocontoserver` | `—` | `off` | Disable automatic server summaries. | `app/plugins/commands_modular/resoconto.py:906` |
| `resocontoserver` | `—` | `oggi` | Show manual server summary for today. | `app/plugins/commands_modular/resoconto.py:1103` |
| `resocontoserver` | `—` | `on` | Enable automatic server summaries. | `app/plugins/commands_modular/resoconto.py:889` |
| `resocontoserver` | `—` | `range` | Show manual server summary for a range. | `app/plugins/commands_modular/resoconto.py:1196` |
| `resocontoserver` | `—` | `schedule_add` | Add a server summary schedule. | `app/plugins/commands_modular/resoconto.py:965` |
| `resocontoserver` | `—` | `schedule_edit` | Edit a server summary schedule. | `app/plugins/commands_modular/resoconto.py:993` |
| `resocontoserver` | `—` | `schedule_list` | List server summary schedules. | `app/plugins/commands_modular/resoconto.py:1081` |
| `resocontoserver` | `—` | `schedule_remove` | Remove a server summary schedule. | `app/plugins/commands_modular/resoconto.py:1042` |
| `resocontoserver` | `—` | `schedule_show` | Show one server summary schedule. | `app/plugins/commands_modular/resoconto.py:1062` |
| `resocontoserver` | `—` | `status` | Show the server summary schedule status. | `app/plugins/commands_modular/resoconto.py:922` |
| `resocontoserver` | `—` | `ultimi` | Show manual server summary for the last window. | `app/plugins/commands_modular/resoconto.py:1157` |
| `riassunto` | `—` | `off` | Disable DM channel summary in this channel. | `app/plugins/commands_modular/riassunto.py:2166` |
| `riassunto` | `—` | `on` | Enable DM channel summary in this channel. | `app/plugins/commands_modular/riassunto.py:2162` |
| `riassunto` | `—` | `status` | Show DM channel summary status in this channel. | `app/plugins/commands_modular/riassunto.py:2170` |
| `status` | `—` | `mood_reset` | Reset the Barcello mood for this channel. | `app/plugins/commands_modular/status.py:204` |
| `status` | `—` | `mood_set` | Set the Barcello mood for this channel. | `app/plugins/commands_modular/status.py:144` |
| `status` | `—` | `mood_show` | Show the Barcello mood for this channel. | `app/plugins/commands_modular/status.py:198` |
| `status` | `—` | `show` | Show the Barcellometro status. | `app/plugins/commands_modular/status.py:102` |
| `tempban` | `—` | `tempban` | Alias of /users tempban. | `app/plugins/commands_modular/moderazione_utenti.py:1050` |
| `triggers` | `barcello` | `calibrate` | Recalculate Barcello calibration weights. | `app/plugins/commands_modular/barcello.py:205` |
| `triggers` | `barcello` | `off` | Disable Barcello triggers in the current channel. | `app/plugins/commands_modular/barcello.py:197` |
| `triggers` | `barcello` | `on` | Enable Barcello triggers in the current channel. | `app/plugins/commands_modular/barcello.py:193` |
| `triggers` | `barcello` | `run` | Run the Barcello analysis. | `app/plugins/commands_modular/barcello.py:1684` |
| `triggers` | `barcello` | `status` | Show Barcello trigger status for the current channel. | `app/plugins/commands_modular/barcello.py:201` |
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
| `unban` | `—` | `unban` | Alias of /users unban. | `app/plugins/commands_modular/moderazione_utenti.py:1022` |
| `ungrace` | `—` | `ungrace` | Alias of /users ungrace. | `app/plugins/commands_modular/moderazione_utenti.py:1078` |
| `untempban` | `—` | `untempban` | Alias of /users untempban. | `app/plugins/commands_modular/moderazione_utenti.py:1030` |
| `users` | `—` | `ban` | Ban a user permanently. | `app/plugins/commands_modular/moderazione_utenti.py:714` |
| `users` | `—` | `ban_list` | List active permanent bans. | `app/plugins/commands_modular/moderazione_utenti.py:718` |
| `users` | `—` | `grace` | Assign a manual grace period to a user. | `app/plugins/commands_modular/moderazione_utenti.py:916` |
| `users` | `—` | `grace_list` | List active grace periods. | `app/plugins/commands_modular/moderazione_utenti.py:926` |
| `users` | `—` | `kick` | Remove a user from the server. | `app/plugins/commands_modular/moderazione_utenti.py:705` |
| `users` | `—` | `kick_list` | List recent user removals. | `app/plugins/commands_modular/moderazione_utenti.py:709` |
| `users` | `—` | `tempban` | Ban a user temporarily. | `app/plugins/commands_modular/moderazione_utenti.py:895` |
| `users` | `—` | `tempban_list` | List active temporary bans. | `app/plugins/commands_modular/moderazione_utenti.py:905` |
| `users` | `unban` | `ieri` | Revoca i ban creati ieri. | `app/plugins/commands_modular/moderazione_utenti.py:754` |
| `users` | `unban` | `intervallo` | Revoca i ban creati in un intervallo esplicito. | `app/plugins/commands_modular/moderazione_utenti.py:798` |
| `users` | `unban` | `last` | Revoke bans created in the last rolling window. | `app/plugins/commands_modular/moderazione_utenti.py:760` |
| `users` | `unban` | `oggi` | Revoca i ban creati oggi. | `app/plugins/commands_modular/moderazione_utenti.py:744` |
| `users` | `unban` | `range` | Revoke bans created in an explicit range. | `app/plugins/commands_modular/moderazione_utenti.py:789` |
| `users` | `unban` | `today` | Revoke bans created today. | `app/plugins/commands_modular/moderazione_utenti.py:739` |
| `users` | `unban` | `ultimi` | Revoca i ban creati nella finestra mobile. | `app/plugins/commands_modular/moderazione_utenti.py:775` |
| `users` | `unban` | `user` | Revoke an active ban for one user. | `app/plugins/commands_modular/moderazione_utenti.py:731` |
| `users` | `unban` | `yesterday` | Revoke bans created yesterday. | `app/plugins/commands_modular/moderazione_utenti.py:749` |
| `users` | `ungrace` | `ieri` | Revoca i grace creati ieri. | `app/plugins/commands_modular/moderazione_utenti.py:980` |
| `users` | `ungrace` | `intervallo` | Revoca i grace creati in un intervallo esplicito. | `app/plugins/commands_modular/moderazione_utenti.py:1000` |
| `users` | `ungrace` | `last` | Revoke grace periods created in the last rolling window. | `app/plugins/commands_modular/moderazione_utenti.py:952` |
| `users` | `ungrace` | `oggi` | Revoca i grace creati oggi. | `app/plugins/commands_modular/moderazione_utenti.py:975` |
| `users` | `ungrace` | `range` | Revoke grace periods created in an explicit range. | `app/plugins/commands_modular/moderazione_utenti.py:966` |
| `users` | `ungrace` | `today` | Revoke grace periods created today. | `app/plugins/commands_modular/moderazione_utenti.py:941` |
| `users` | `ungrace` | `ultimi` | Revoca i grace creati nella finestra mobile. | `app/plugins/commands_modular/moderazione_utenti.py:986` |
| `users` | `ungrace` | `user` | Revoke an active grace period for one user. | `app/plugins/commands_modular/moderazione_utenti.py:933` |
| `users` | `ungrace` | `yesterday` | Revoke grace periods created yesterday. | `app/plugins/commands_modular/moderazione_utenti.py:946` |
| `users` | `untempban` | `ieri` | Revoca i temp ban creati ieri. | `app/plugins/commands_modular/moderazione_utenti.py:858` |
| `users` | `untempban` | `intervallo` | Revoca i temp ban creati in un intervallo esplicito. | `app/plugins/commands_modular/moderazione_utenti.py:878` |
| `users` | `untempban` | `last` | Revoke temporary bans created in the last rolling window. | `app/plugins/commands_modular/moderazione_utenti.py:830` |
| `users` | `untempban` | `oggi` | Revoca i temp ban creati oggi. | `app/plugins/commands_modular/moderazione_utenti.py:853` |
| `users` | `untempban` | `range` | Revoke temporary bans created in an explicit range. | `app/plugins/commands_modular/moderazione_utenti.py:844` |
| `users` | `untempban` | `today` | Revoke temporary bans created today. | `app/plugins/commands_modular/moderazione_utenti.py:819` |
| `users` | `untempban` | `ultimi` | Revoca i temp ban creati nella finestra mobile. | `app/plugins/commands_modular/moderazione_utenti.py:864` |
| `users` | `untempban` | `user` | Revoke an active temporary ban for one user. | `app/plugins/commands_modular/moderazione_utenti.py:811` |
| `users` | `untempban` | `yesterday` | Revoke temporary bans created yesterday. | `app/plugins/commands_modular/moderazione_utenti.py:824` |
| `voice_ingest` | `—` | `join` | Join a voice channel manually. | `app/plugins/commands_modular/voice_ingest.py:24` |
| `voice_ingest` | `—` | `leave` | Leave the current voice channel manually. | `app/plugins/commands_modular/voice_ingest.py:48` |

## Issues

- **WARNING missing_param_description** — `barcello.intervallo`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/barcello.py:1933`)
- **WARNING missing_param_description** — `barcello.intervallo`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/barcello.py:1933`)
- **WARNING missing_param_description** — `barcello.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/barcello.py:1923`)
- **WARNING missing_param_description** — `barcello.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/barcello.py:1923`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.last`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/barcello.py:1863`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.last`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/barcello.py:1864`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.last`: Parameter 'user1' is missing a description. (`app/plugins/commands_modular/barcello.py:1865`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.last`: Parameter 'user2' is missing a description. (`app/plugins/commands_modular/barcello.py:1866`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/barcello.py:1882`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/barcello.py:1883`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.range`: Parameter 'user1' is missing a description. (`app/plugins/commands_modular/barcello.py:1884`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.range`: Parameter 'user2' is missing a description. (`app/plugins/commands_modular/barcello.py:1885`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.today`: Parameter 'user1' is missing a description. (`app/plugins/commands_modular/barcello.py:1829`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.today`: Parameter 'user2' is missing a description. (`app/plugins/commands_modular/barcello.py:1829`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.yesterday`: Parameter 'user1' is missing a description. (`app/plugins/commands_modular/barcello.py:1841`)
- **WARNING missing_param_description** — `dmchannelsummary.barcello.yesterday`: Parameter 'user2' is missing a description. (`app/plugins/commands_modular/barcello.py:1841`)
- **WARNING missing_param_description** — `inactivity.dms.template_reminder_set`: Parameter 'text' is missing a description. (`app/plugins/commands_modular/inattivi.py:335`)
- **WARNING missing_param_description** — `resocontocanale.aura.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/resoconto.py:873`)
- **WARNING missing_param_description** — `resocontocanale.aura.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/resoconto.py:873`)
- **WARNING missing_param_description** — `resocontocanale.aura.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/resoconto.py:841`)
- **WARNING missing_param_description** — `resocontocanale.aura.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/resoconto.py:841`)
- **WARNING missing_param_description** — `resocontocanale.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/resoconto.py:857`)
- **WARNING missing_param_description** — `resocontocanale.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/resoconto.py:857`)
- **WARNING missing_param_description** — `resocontocanale.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/resoconto.py:817`)
- **WARNING missing_param_description** — `resocontocanale.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/resoconto.py:817`)
- **WARNING missing_param_description** — `resocontoserver.aura.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/resoconto.py:1212`)
- **WARNING missing_param_description** — `resocontoserver.aura.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/resoconto.py:1212`)
- **WARNING missing_param_description** — `resocontoserver.aura.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/resoconto.py:1181`)
- **WARNING missing_param_description** — `resocontoserver.aura.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/resoconto.py:1181`)
- **WARNING missing_param_description** — `resocontoserver.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/resoconto.py:1196`)
- **WARNING missing_param_description** — `resocontoserver.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/resoconto.py:1196`)
- **WARNING missing_param_description** — `resocontoserver.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/resoconto.py:1157`)
- **WARNING missing_param_description** — `resocontoserver.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/resoconto.py:1157`)
- **WARNING required_param** — `ai.fallback_set`: Parameter 'model' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/admin.py:465`)
- **WARNING required_param** — `ai.model_set`: Parameter 'model' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/admin.py:433`)
- **WARNING required_param** — `campaigns.cap.limits_set`: Parameter 'daily_limit' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/messaggi.py:588`)
- **WARNING required_param** — `campaigns.insights.template_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:1027`)
- **WARNING required_param** — `campaigns.prompt.schedule_show`: Parameter 'id_or_name' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:755`)
- **WARNING required_param** — `campaigns.quiet.range_set`: Parameter 'start' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/messaggi.py:541`)
- **WARNING required_param** — `campaigns.quiet.range_set`: Parameter 'end' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/messaggi.py:541`)
- **WARNING required_param** — `embed.description.template_service_set`: Parameter 'template' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/embed.py:870`)
- **WARNING required_param** — `inactivity.dms.cooldown_set`: Parameter 'days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:364`)
- **WARNING required_param** — `inactivity.dms.invite_set`: Parameter 'url' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:389`)
- **WARNING required_param** — `inactivity.dms.template_reminder_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:335`)
- **WARNING required_param** — `inactivity.grace.limits_set`: Parameter 'days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:265`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'inactive_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:419`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'window_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:420`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'min_messages' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:421`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'mode' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:422`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'inactive_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:463`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'window_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:464`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'min_messages' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:465`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'mode' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:466`)
- **WARNING required_param** — `inactivity.tempban.limits_set`: Parameter 'days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:312`)
- **WARNING required_param** — `qna.bonus_set`: Parameter 'amount' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:964`)
- **WARNING required_param** — `qna.limits_set`: Parameter 'tier' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:933`)
- **WARNING required_param** — `qna.limits_set`: Parameter 'limit' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:933`)
- **WARNING required_param** — `status.mood_set`: Parameter 'value' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/status.py:144`)
- **WARNING required_param** — `triggers.phrases.template_global_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:553`)
- **WARNING required_param** — `triggers.phrases.template_milestone_set`: Parameter 'threshold' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:510`)
- **WARNING required_param** — `triggers.phrases.template_milestone_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:510`)
- **WARNING required_param** — `triggers.phrases.template_user_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:598`)

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
- `users.unban.ieri`
- `users.unban.intervallo`
- `users.unban.oggi`
- `users.unban.ultimi`
- `users.ungrace.ieri`
- `users.ungrace.intervallo`
- `users.ungrace.oggi`
- `users.ungrace.ultimi`
- `users.untempban.ieri`
- `users.untempban.intervallo`
- `users.untempban.oggi`
- `users.untempban.ultimi`

## Usage

- Run `python -m scripts.validate_commands` for a console report.
- Run `python -m scripts.validate_commands --write-report` to refresh this markdown file.
- Run `pytest tests/test_command_standard_validator.py` to fail CI on validator errors.
