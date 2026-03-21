# Command Tree Validation Report

Questo report inventaria i comandi realmente registrati nel repository. Per il vocabolario canonico delle action e la loro semantica normativa fa fede `docs/command_standards.md`; le action composte (`config_set`, `schedule_add`, `template_global_reset`, ecc.) vanno lette come estensioni dei verbi canonici e non introducono nuove action standard.

- Commands discovered: **267**
- Errors: **0**
- Warnings: **53**

## Inventory

| Root | Subgroup | Action | Description | Source |
| --- | --- | --- | --- | --- |
| `admin` | `ai` | `fallback_set` | Set the AI fallback model for a task. | `app/plugins/commands_modular/admin.py:598` |
| `admin` | `ai` | `fallback_show` | Show configured AI fallback models. | `app/plugins/commands_modular/admin.py:627` |
| `admin` | `ai` | `model_set` | Set the AI model for a task. | `app/plugins/commands_modular/admin.py:555` |
| `admin` | `ai` | `model_show` | Show configured AI models. | `app/plugins/commands_modular/admin.py:584` |
| `admin` | `ai` | `off` | Disable the AI service. | `app/plugins/commands_modular/admin.py:545` |
| `admin` | `ai` | `on` | Enable the AI service. | `app/plugins/commands_modular/admin.py:538` |
| `admin` | `ai` | `run` | Run an AI test prompt. | `app/plugins/commands_modular/admin.py:672` |
| `admin` | `ai` | `status` | Show AI service status. | `app/plugins/commands_modular/admin.py:638` |
| `admin` | `backfill` | `config_reset` | Reset backfill configuration to defaults. | `app/plugins/commands_modular/admin.py:500` |
| `admin` | `backfill` | `config_set` | Update backfill configuration. | `app/plugins/commands_modular/admin.py:457` |
| `admin` | `backfill` | `config_show` | Show backfill configuration. | `app/plugins/commands_modular/admin.py:489` |
| `admin` | `backfill` | `off` | Disable backfill. | `app/plugins/commands_modular/admin.py:436` |
| `admin` | `backfill` | `on` | Enable backfill. | `app/plugins/commands_modular/admin.py:429` |
| `admin` | `backfill` | `run` | Run backfill now. | `app/plugins/commands_modular/admin.py:514` |
| `admin` | `backfill` | `status` | Show backfill status. | `app/plugins/commands_modular/admin.py:443` |
| `admin` | `barcello` | `calibrate` | Recalculate Barcello calibration weights. | `app/plugins/commands_modular/barcello.py:257` |
| `admin` | `barcello` | `mood_reset` | Reset the Barcello mood for this channel. | `app/plugins/commands_modular/barcello.py:246` |
| `admin` | `barcello` | `mood_set` | Set the Barcello mood for this channel. | `app/plugins/commands_modular/barcello.py:213` |
| `admin` | `barcello` | `mood_show` | Show the Barcello mood for this channel. | `app/plugins/commands_modular/barcello.py:242` |
| `admin` | `barcello` | `off` | Disable the Barcello trigger for this channel. | `app/plugins/commands_modular/barcello.py:204` |
| `admin` | `barcello` | `on` | Enable the Barcello trigger for this channel. | `app/plugins/commands_modular/barcello.py:200` |
| `admin` | `barcello` | `run` | Run the Barcello analysis. | `app/plugins/commands_modular/barcello.py:1716` |
| `admin` | `barcello` | `status` | Show Barcello trigger status for this channel. | `app/plugins/commands_modular/barcello.py:208` |
| `admin` | `events` | `off` | Disable event collection for this channel. | `app/plugins/commands_modular/admin.py:332` |
| `admin` | `events` | `on` | Enable event collection for this channel. | `app/plugins/commands_modular/admin.py:326` |
| `admin` | `events` | `status` | Show event collection status for this channel. | `app/plugins/commands_modular/admin.py:338` |
| `admin` | `footer` | `off` | Disable footer rendering. | `app/plugins/commands_modular/admin.py:712` |
| `admin` | `footer` | `on` | Enable footer rendering. | `app/plugins/commands_modular/admin.py:702` |
| `admin` | `footer` | `status` | Show footer status and rendered variants. | `app/plugins/commands_modular/admin.py:855` |
| `admin` | `footer` | `template_global_reset` | Reset the global footer template. | `app/plugins/commands_modular/admin.py:775` |
| `admin` | `footer` | `template_global_set` | Set the global footer template. | `app/plugins/commands_modular/admin.py:723` |
| `admin` | `footer` | `template_global_show` | Show the global footer template. | `app/plugins/commands_modular/admin.py:756` |
| `admin` | `footer` | `template_service_reset` | Reset a service-specific footer template. | `app/plugins/commands_modular/admin.py:835` |
| `admin` | `footer` | `template_service_set` | Set a service-specific footer template. | `app/plugins/commands_modular/admin.py:793` |
| `admin` | `footer` | `template_service_show` | Show a service-specific footer template. | `app/plugins/commands_modular/admin.py:812` |
| `admin` | `retention` | `config_reset` | Reset retention configuration to defaults. | `app/plugins/commands_modular/admin.py:415` |
| `admin` | `retention` | `config_set` | Update retention configuration. | `app/plugins/commands_modular/admin.py:372` |
| `admin` | `retention` | `config_show` | Show retention configuration. | `app/plugins/commands_modular/admin.py:404` |
| `admin` | `retention` | `off` | Disable the retention task. | `app/plugins/commands_modular/admin.py:351` |
| `admin` | `retention` | `on` | Enable the retention task. | `app/plugins/commands_modular/admin.py:344` |
| `admin` | `retention` | `status` | Show retention status. | `app/plugins/commands_modular/admin.py:358` |
| `admin` | `—` | `status` | Show the Barcellometro status. | `app/plugins/commands_modular/status.py:18` |
| `attivita` | `—` | `ieri` | Report attività di ieri (DM staff) | `app/plugins/commands_modular/attivita.py:610` |
| `attivita` | `—` | `oggi` | Report attività di oggi (DM staff) | `app/plugins/commands_modular/attivita.py:605` |
| `attivita` | `—` | `range` | Report attività per range custom | `app/plugins/commands_modular/attivita.py:638` |
| `attivita` | `—` | `ultimi` | Report attività ultimi N periodi | `app/plugins/commands_modular/attivita.py:623` |
| `audionotes` | `—` | `config_reset` | Reset the audio notes configuration to defaults. | `app/plugins/commands_modular/audio_notes.py:164` |
| `audionotes` | `—` | `config_set` | Update the audio notes configuration. | `app/plugins/commands_modular/audio_notes.py:83` |
| `audionotes` | `—` | `config_show` | Show the audio notes configuration. | `app/plugins/commands_modular/audio_notes.py:146` |
| `audionotes` | `—` | `off` | Disable audio notes. | `app/plugins/commands_modular/audio_notes.py:43` |
| `audionotes` | `—` | `on` | Enable audio notes. | `app/plugins/commands_modular/audio_notes.py:30` |
| `audionotes` | `—` | `status` | Show the audio notes status. | `app/plugins/commands_modular/audio_notes.py:56` |
| `aura` | `—` | `ieri` | Aura di ieri | `app/plugins/commands_modular/aura.py:457` |
| `aura` | `—` | `oggi` | Aura di oggi | `app/plugins/commands_modular/aura.py:452` |
| `aura` | `—` | `range` | Aura per intervallo | `app/plugins/commands_modular/aura.py:463` |
| `aura` | `—` | `ultimi` | Aura ultimi N periodi | `app/plugins/commands_modular/aura.py:435` |
| `barcello` | `—` | `barcello` | Mostra lo stato del barcello (in DM) | `app/plugins/commands_modular/barcello.py:1738` |
| `campagne` | `cap` | `config_reset` | Reset the daily cap configuration | `app/plugins/commands_modular/messaggi.py:605` |
| `campagne` | `cap` | `config_set` | Set the daily cap configuration | `app/plugins/commands_modular/messaggi.py:588` |
| `campagne` | `cap` | `config_show` | Show the daily cap configuration | `app/plugins/commands_modular/messaggi.py:598` |
| `campagne` | `cap` | `off` | Disable the daily cap | `app/plugins/commands_modular/messaggi.py:572` |
| `campagne` | `cap` | `on` | Enable the daily cap | `app/plugins/commands_modular/messaggi.py:565` |
| `campagne` | `cap` | `status` | Show the daily cap status | `app/plugins/commands_modular/messaggi.py:579` |
| `campagne` | `custom` | `off` | Disable custom campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:616` |
| `campagne` | `custom` | `on` | Enable custom campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:612` |
| `campagne` | `custom` | `run` | Run a custom campaign schedule now | `app/plugins/commands_modular/messaggi.py:752` |
| `campagne` | `custom` | `schedule_add` | Add a custom campaign schedule | `app/plugins/commands_modular/messaggi.py:639` |
| `campagne` | `custom` | `schedule_edit` | Edit a custom campaign schedule | `app/plugins/commands_modular/messaggi.py:793` |
| `campagne` | `custom` | `schedule_list` | List custom campaign schedules | `app/plugins/commands_modular/messaggi.py:709` |
| `campagne` | `custom` | `schedule_remove` | Remove a custom campaign schedule | `app/plugins/commands_modular/messaggi.py:737` |
| `campagne` | `custom` | `schedule_show` | Show a custom campaign schedule | `app/plugins/commands_modular/messaggi.py:723` |
| `campagne` | `custom` | `status` | Show custom campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:620` |
| `campagne` | `horoscope` | `off` | Disable horoscope campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:1082` |
| `campagne` | `horoscope` | `on` | Enable horoscope campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:1078` |
| `campagne` | `horoscope` | `run` | Run the horoscope campaign immediately | `app/plugins/commands_modular/messaggi.py:1163` |
| `campagne` | `horoscope` | `schedule_add` | Add a horoscope campaign schedule | `app/plugins/commands_modular/messaggi.py:1097` |
| `campagne` | `horoscope` | `schedule_edit` | Edit a horoscope campaign schedule | `app/plugins/commands_modular/messaggi.py:1126` |
| `campagne` | `horoscope` | `schedule_list` | List horoscope campaign schedules | `app/plugins/commands_modular/messaggi.py:1159` |
| `campagne` | `horoscope` | `schedule_remove` | Remove a horoscope campaign schedule | `app/plugins/commands_modular/messaggi.py:1155` |
| `campagne` | `horoscope` | `schedule_show` | Show a horoscope campaign schedule | `app/plugins/commands_modular/messaggi.py:1150` |
| `campagne` | `horoscope` | `status` | Show horoscope campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:1086` |
| `campagne` | `news` | `off` | Disable news campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:905` |
| `campagne` | `news` | `on` | Enable news campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:901` |
| `campagne` | `news` | `run` | Run the news campaign immediately | `app/plugins/commands_modular/messaggi.py:985` |
| `campagne` | `news` | `schedule_add` | Add a news campaign schedule | `app/plugins/commands_modular/messaggi.py:921` |
| `campagne` | `news` | `schedule_edit` | Edit a news campaign schedule | `app/plugins/commands_modular/messaggi.py:950` |
| `campagne` | `news` | `schedule_list` | List news campaign schedules | `app/plugins/commands_modular/messaggi.py:981` |
| `campagne` | `news` | `schedule_remove` | Remove a news campaign schedule | `app/plugins/commands_modular/messaggi.py:977` |
| `campagne` | `news` | `schedule_show` | Show a news campaign schedule | `app/plugins/commands_modular/messaggi.py:972` |
| `campagne` | `news` | `status` | Show news campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:909` |
| `campagne` | `—` | `off` | Disable campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:493` |
| `campagne` | `—` | `on` | Enable campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:482` |
| `campagne` | `prompt` | `off` | Disable prompt campaigns in the current channel | `app/plugins/commands_modular/triggers.py:627` |
| `campagne` | `prompt` | `on` | Enable prompt campaigns in the current channel | `app/plugins/commands_modular/triggers.py:615` |
| `campagne` | `prompt` | `run` | Run a prompt campaign schedule now | `app/plugins/commands_modular/triggers.py:760` |
| `campagne` | `prompt` | `schedule_add` | Add a prompt campaign schedule | `app/plugins/commands_modular/triggers.py:658` |
| `campagne` | `prompt` | `schedule_edit` | Edit a prompt campaign schedule | `app/plugins/commands_modular/triggers.py:804` |
| `campagne` | `prompt` | `schedule_list` | List prompt campaign schedules | `app/plugins/commands_modular/triggers.py:717` |
| `campagne` | `prompt` | `schedule_remove` | Remove a prompt campaign schedule | `app/plugins/commands_modular/triggers.py:745` |
| `campagne` | `prompt` | `schedule_show` | Show a prompt campaign schedule | `app/plugins/commands_modular/triggers.py:731` |
| `campagne` | `prompt` | `status` | Show prompt campaign status for the current channel | `app/plugins/commands_modular/triggers.py:639` |
| `campagne` | `quiet` | `config_reset` | Reset quiet hours configuration | `app/plugins/commands_modular/messaggi.py:557` |
| `campagne` | `quiet` | `config_set` | Set quiet hours configuration | `app/plugins/commands_modular/messaggi.py:541` |
| `campagne` | `quiet` | `config_show` | Show quiet hours configuration | `app/plugins/commands_modular/messaggi.py:549` |
| `campagne` | `quiet` | `off` | Disable quiet hours | `app/plugins/commands_modular/messaggi.py:524` |
| `campagne` | `quiet` | `on` | Enable quiet hours | `app/plugins/commands_modular/messaggi.py:517` |
| `campagne` | `quiet` | `status` | Show quiet hours status | `app/plugins/commands_modular/messaggi.py:531` |
| `campagne` | `—` | `status` | Show campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:504` |
| `campagne` | `weather` | `off` | Disable weather campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:993` |
| `campagne` | `weather` | `on` | Enable weather campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:989` |
| `campagne` | `weather` | `run` | Run the weather campaign immediately | `app/plugins/commands_modular/messaggi.py:1074` |
| `campagne` | `weather` | `schedule_add` | Add a weather campaign schedule | `app/plugins/commands_modular/messaggi.py:1008` |
| `campagne` | `weather` | `schedule_edit` | Edit a weather campaign schedule | `app/plugins/commands_modular/messaggi.py:1037` |
| `campagne` | `weather` | `schedule_list` | List weather campaign schedules | `app/plugins/commands_modular/messaggi.py:1070` |
| `campagne` | `weather` | `schedule_remove` | Remove a weather campaign schedule | `app/plugins/commands_modular/messaggi.py:1066` |
| `campagne` | `weather` | `schedule_show` | Show a weather campaign schedule | `app/plugins/commands_modular/messaggi.py:1061` |
| `campagne` | `weather` | `status` | Show weather campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:997` |
| `commandguard` | `—` | `role_add` | Add a role command policy. | `app/plugins/commands_modular/roles.py:80` |
| `commandguard` | `—` | `role_edit` | Edit a role command policy. | `app/plugins/commands_modular/roles.py:91` |
| `commandguard` | `—` | `role_list` | List all role policies. | `app/plugins/commands_modular/roles.py:122` |
| `commandguard` | `—` | `role_remove` | Remove a role command policy. | `app/plugins/commands_modular/roles.py:102` |
| `commandguard` | `—` | `role_reset` | Reset all policies for a role. | `app/plugins/commands_modular/roles.py:133` |
| `commandguard` | `—` | `role_show` | Show role policies. | `app/plugins/commands_modular/roles.py:110` |
| `commandguard` | `—` | `user_add` | Add a user command policy. | `app/plugins/commands_modular/roles.py:141` |
| `commandguard` | `—` | `user_edit` | Edit a user command policy. | `app/plugins/commands_modular/roles.py:152` |
| `commandguard` | `—` | `user_list` | List all user policies. | `app/plugins/commands_modular/roles.py:183` |
| `commandguard` | `—` | `user_remove` | Remove a user command policy. | `app/plugins/commands_modular/roles.py:163` |
| `commandguard` | `—` | `user_reset` | Reset all policies for a user. | `app/plugins/commands_modular/roles.py:194` |
| `commandguard` | `—` | `user_show` | Show user policies. | `app/plugins/commands_modular/roles.py:171` |
| `domanda` | `—` | `domanda` | Fai una domanda al Q&A | `app/plugins/commands_modular/ask.py:60` |
| `frasi` | `—` | `entry_add` | Add a phrase trigger entry | `app/plugins/commands_modular/triggers.py:304` |
| `frasi` | `—` | `entry_edit` | Edit a phrase trigger entry | `app/plugins/commands_modular/triggers.py:413` |
| `frasi` | `—` | `entry_list` | List phrase trigger entries | `app/plugins/commands_modular/triggers.py:359` |
| `frasi` | `—` | `entry_remove` | Remove a phrase trigger entry | `app/plugins/commands_modular/triggers.py:346` |
| `frasi` | `—` | `entry_show` | Show a phrase trigger entry | `app/plugins/commands_modular/triggers.py:372` |
| `frasi` | `—` | `off` | Disable phrase triggers | `app/plugins/commands_modular/triggers.py:288` |
| `frasi` | `—` | `on` | Enable phrase triggers | `app/plugins/commands_modular/triggers.py:284` |
| `frasi` | `—` | `status` | Show phrase trigger status | `app/plugins/commands_modular/triggers.py:292` |
| `frasi` | `—` | `template_global_reset` | Reset the global phrase template | `app/plugins/commands_modular/triggers.py:556` |
| `frasi` | `—` | `template_global_set` | Set the global phrase template | `app/plugins/commands_modular/triggers.py:529` |
| `frasi` | `—` | `template_global_show` | Show the global phrase template | `app/plugins/commands_modular/triggers.py:543` |
| `frasi` | `—` | `template_milestone_reset` | Reset all milestone templates | `app/plugins/commands_modular/triggers.py:516` |
| `frasi` | `—` | `template_milestone_set` | Create or update a milestone template | `app/plugins/commands_modular/triggers.py:486` |
| `frasi` | `—` | `template_milestone_show` | Show milestone templates | `app/plugins/commands_modular/triggers.py:503` |
| `frasi` | `—` | `template_user_reset` | Reset a user-specific phrase template | `app/plugins/commands_modular/triggers.py:604` |
| `frasi` | `—` | `template_user_set` | Set a user-specific phrase template | `app/plugins/commands_modular/triggers.py:574` |
| `frasi` | `—` | `template_user_show` | Show a user-specific phrase template | `app/plugins/commands_modular/triggers.py:591` |
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
| `inactivity` | `grace` | `config_reset` | Reset the inactivity grace period configuration. | `app/plugins/commands_modular/inattivi.py:280` |
| `inactivity` | `grace` | `config_set` | Set the inactivity grace period configuration. | `app/plugins/commands_modular/inattivi.py:265` |
| `inactivity` | `grace` | `config_show` | Show the inactivity grace period configuration. | `app/plugins/commands_modular/inattivi.py:272` |
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
| `inactivity` | `tempban` | `config_reset` | Reset the inactivity tempban configuration. | `app/plugins/commands_modular/inattivi.py:327` |
| `inactivity` | `tempban` | `config_set` | Set the inactivity tempban configuration. | `app/plugins/commands_modular/inattivi.py:312` |
| `inactivity` | `tempban` | `config_show` | Show the inactivity tempban configuration. | `app/plugins/commands_modular/inattivi.py:319` |
| `inactivity` | `tempban` | `off` | Disable temporary bans after inactivity kicks. | `app/plugins/commands_modular/inattivi.py:296` |
| `inactivity` | `tempban` | `on` | Enable temporary bans after inactivity kicks. | `app/plugins/commands_modular/inattivi.py:287` |
| `inactivity` | `tempban` | `status` | Show the inactivity tempban status. | `app/plugins/commands_modular/inattivi.py:303` |
| `insights` | `—` | `off` | Disable insights in the current channel | `app/plugins/commands_modular/triggers.py:986` |
| `insights` | `—` | `on` | Enable insights in the current channel | `app/plugins/commands_modular/triggers.py:982` |
| `insights` | `—` | `status` | Show insights status for the current channel | `app/plugins/commands_modular/triggers.py:990` |
| `insights` | `—` | `template_reset` | Reset the insights template to defaults | `app/plugins/commands_modular/triggers.py:1026` |
| `insights` | `—` | `template_set` | Set the insights template | `app/plugins/commands_modular/triggers.py:1004` |
| `insights` | `—` | `template_show` | Show the insights template | `app/plugins/commands_modular/triggers.py:1014` |
| `mod` | `channel` | `notify_reset` | Reset the moderation notification channel. | `app/plugins/commands_modular/moderazione_utenti.py:174` |
| `mod` | `channel` | `notify_set` | Set the moderation notification channel. | `app/plugins/commands_modular/moderazione_utenti.py:159` |
| `mod` | `channel` | `notify_show` | Show the moderation notification channel. | `app/plugins/commands_modular/moderazione_utenti.py:166` |
| `mod` | `channel` | `off` | Disable moderation notifications for the channel setting. | `app/plugins/commands_modular/moderazione_utenti.py:145` |
| `mod` | `channel` | `on` | Enable moderation notifications for a channel. | `app/plugins/commands_modular/moderazione_utenti.py:132` |
| `mod` | `channel` | `status` | Show the moderation channel configuration status. | `app/plugins/commands_modular/moderazione_utenti.py:152` |
| `mod` | `channel` | `template_reset` | Reset a moderation notification template. | `app/plugins/commands_modular/moderazione_utenti.py:216` |
| `mod` | `channel` | `template_set` | Set a moderation notification template. | `app/plugins/commands_modular/moderazione_utenti.py:182` |
| `mod` | `channel` | `template_show` | Show moderation notification templates. | `app/plugins/commands_modular/moderazione_utenti.py:194` |
| `mod` | `channel` | `user_card_reset` | Reset the moderation notification user card setting. | `app/plugins/commands_modular/moderazione_utenti.py:243` |
| `mod` | `channel` | `user_card_set` | Set whether moderation notifications include the user card. | `app/plugins/commands_modular/moderazione_utenti.py:228` |
| `mod` | `channel` | `user_card_show` | Show whether the moderation notification user card is enabled. | `app/plugins/commands_modular/moderazione_utenti.py:235` |
| `mod` | `users` | `ban` | Ban a user permanently. | `app/plugins/commands_modular/moderazione_utenti.py:309` |
| `mod` | `users` | `ban_list` | List active permanent bans. | `app/plugins/commands_modular/moderazione_utenti.py:324` |
| `mod` | `users` | `grace` | Assign a manual grace period to a user. | `app/plugins/commands_modular/moderazione_utenti.py:373` |
| `mod` | `users` | `grace_list` | List active grace periods. | `app/plugins/commands_modular/moderazione_utenti.py:403` |
| `mod` | `users` | `kick` | Kick a user. | `app/plugins/commands_modular/moderazione_utenti.py:285` |
| `mod` | `users` | `kick_list` | List recent kicks. | `app/plugins/commands_modular/moderazione_utenti.py:300` |
| `mod` | `users` | `tempban` | Ban a user temporarily. | `app/plugins/commands_modular/moderazione_utenti.py:333` |
| `mod` | `users` | `tempban_list` | List active temporary bans. | `app/plugins/commands_modular/moderazione_utenti.py:364` |
| `privacy` | `—` | `off` | Disable voice privacy. | `app/plugins/commands_modular/privacy.py:90` |
| `privacy` | `—` | `on` | Enable voice privacy. | `app/plugins/commands_modular/privacy.py:68` |
| `privacy` | `—` | `status` | Show the current voice privacy status. | `app/plugins/commands_modular/privacy.py:113` |
| `qna` | `—` | `bonus_reset` | Reset a user's QnA bonus | `app/plugins/commands_modular/triggers.py:972` |
| `qna` | `—` | `bonus_set` | Set a QnA bonus for a user | `app/plugins/commands_modular/triggers.py:941` |
| `qna` | `—` | `bonus_show` | Show a user's QnA bonus | `app/plugins/commands_modular/triggers.py:961` |
| `qna` | `—` | `limits_reset` | Reset QnA daily limits to defaults | `app/plugins/commands_modular/triggers.py:931` |
| `qna` | `—` | `limits_set` | Set a QnA daily limit | `app/plugins/commands_modular/triggers.py:910` |
| `qna` | `—` | `limits_show` | Show QnA daily limits | `app/plugins/commands_modular/triggers.py:886` |
| `qna` | `—` | `off` | Disable QnA in the current channel | `app/plugins/commands_modular/triggers.py:876` |
| `qna` | `—` | `on` | Enable QnA in the current channel | `app/plugins/commands_modular/triggers.py:872` |
| `qna` | `—` | `status` | Show QnA status for the current channel | `app/plugins/commands_modular/triggers.py:880` |
| `resocontocanale` | `aura` | `ieri` | Show manual channel aura details for yesterday. | `app/plugins/commands_modular/resoconto.py:630` |
| `resocontocanale` | `aura` | `oggi` | Show manual channel aura details for today. | `app/plugins/commands_modular/resoconto.py:622` |
| `resocontocanale` | `aura` | `range` | Show manual channel aura details for a range. | `app/plugins/commands_modular/resoconto.py:670` |
| `resocontocanale` | `aura` | `ultimi` | Show manual channel aura details for the last window. | `app/plugins/commands_modular/resoconto.py:658` |
| `resocontocanale` | `—` | `ieri` | Show manual channel aura details for yesterday. | `app/plugins/commands_modular/resoconto.py:626` |
| `resocontocanale` | `—` | `off` | Disable automatic channel summaries for the current channel. | `app/plugins/commands_modular/resoconto.py:408` |
| `resocontocanale` | `—` | `oggi` | Show manual channel aura details for today. | `app/plugins/commands_modular/resoconto.py:618` |
| `resocontocanale` | `—` | `on` | Enable automatic channel summaries for the current channel. | `app/plugins/commands_modular/resoconto.py:392` |
| `resocontocanale` | `—` | `range` | Show manual channel aura details for a range. | `app/plugins/commands_modular/resoconto.py:662` |
| `resocontocanale` | `—` | `schedule_add` | Add a channel summary schedule. | `app/plugins/commands_modular/resoconto.py:467` |
| `resocontocanale` | `—` | `schedule_edit` | Edit a channel summary schedule. | `app/plugins/commands_modular/resoconto.py:495` |
| `resocontocanale` | `—` | `schedule_list` | List channel summary schedules for the current channel. | `app/plugins/commands_modular/resoconto.py:596` |
| `resocontocanale` | `—` | `schedule_remove` | Remove a channel summary schedule. | `app/plugins/commands_modular/resoconto.py:549` |
| `resocontocanale` | `—` | `schedule_show` | Show one channel summary schedule. | `app/plugins/commands_modular/resoconto.py:573` |
| `resocontocanale` | `—` | `status` | Show the channel summary schedule status. | `app/plugins/commands_modular/resoconto.py:424` |
| `resocontocanale` | `—` | `ultimi` | Show manual channel aura details for the last window. | `app/plugins/commands_modular/resoconto.py:642` |
| `resocontoserver` | `aura` | `ieri` | Show manual server aura details for yesterday. | `app/plugins/commands_modular/resoconto.py:902` |
| `resocontoserver` | `aura` | `oggi` | Show manual server aura details for today. | `app/plugins/commands_modular/resoconto.py:893` |
| `resocontoserver` | `aura` | `range` | Show manual server aura details for a range. | `app/plugins/commands_modular/resoconto.py:942` |
| `resocontoserver` | `aura` | `ultimi` | Show manual server aura details for the last window. | `app/plugins/commands_modular/resoconto.py:930` |
| `resocontoserver` | `—` | `ieri` | Show manual server aura details for yesterday. | `app/plugins/commands_modular/resoconto.py:897` |
| `resocontoserver` | `—` | `off` | Disable automatic server summaries. | `app/plugins/commands_modular/resoconto.py:691` |
| `resocontoserver` | `—` | `oggi` | Show manual server aura details for today. | `app/plugins/commands_modular/resoconto.py:888` |
| `resocontoserver` | `—` | `on` | Enable automatic server summaries. | `app/plugins/commands_modular/resoconto.py:674` |
| `resocontoserver` | `—` | `range` | Show manual server aura details for a range. | `app/plugins/commands_modular/resoconto.py:934` |
| `resocontoserver` | `—` | `schedule_add` | Add a server summary schedule. | `app/plugins/commands_modular/resoconto.py:750` |
| `resocontoserver` | `—` | `schedule_edit` | Edit a server summary schedule. | `app/plugins/commands_modular/resoconto.py:778` |
| `resocontoserver` | `—` | `schedule_list` | List server summary schedules. | `app/plugins/commands_modular/resoconto.py:866` |
| `resocontoserver` | `—` | `schedule_remove` | Remove a server summary schedule. | `app/plugins/commands_modular/resoconto.py:827` |
| `resocontoserver` | `—` | `schedule_show` | Show one server summary schedule. | `app/plugins/commands_modular/resoconto.py:847` |
| `resocontoserver` | `—` | `status` | Show the server summary schedule status. | `app/plugins/commands_modular/resoconto.py:707` |
| `resocontoserver` | `—` | `ultimi` | Show manual server aura details for the last window. | `app/plugins/commands_modular/resoconto.py:914` |
| `riassunto` | `—` | `ieri` | Riassunto della giornata di ieri | `app/plugins/commands_modular/riassunto.py:2161` |
| `riassunto` | `—` | `oggi` | Riassunto della giornata di oggi | `app/plugins/commands_modular/riassunto.py:2156` |
| `riassunto` | `—` | `range` | Riassunto per intervallo | `app/plugins/commands_modular/riassunto.py:2167` |
| `riassunto` | `—` | `ultimi` | Riassunto ultimi N periodi | `app/plugins/commands_modular/riassunto.py:2136` |
| `stt` | `—` | `config_reset` | Reset the STT configuration to defaults. | `app/plugins/commands_modular/stt.py:125` |
| `stt` | `—` | `config_set` | Update the STT configuration. | `app/plugins/commands_modular/stt.py:62` |
| `stt` | `—` | `config_show` | Show the STT configuration. | `app/plugins/commands_modular/stt.py:109` |
| `translate` | `—` | `config_reset` | Reset the translation configuration to defaults. | `app/plugins/commands_modular/translate.py:84` |
| `translate` | `—` | `config_set` | Update the translation configuration. | `app/plugins/commands_modular/translate.py:32` |
| `translate` | `—` | `config_show` | Show the translation configuration. | `app/plugins/commands_modular/translate.py:68` |
| `voice_ingest` | `—` | `join` | Join a voice channel manually. | `app/plugins/commands_modular/voice_ingest.py:23` |
| `voice_ingest` | `—` | `leave` | Leave the current voice channel manually. | `app/plugins/commands_modular/voice_ingest.py:47` |

## Issues

- **WARNING localized_param_description** — `barcello`: Parameter 'user1' description looks non-English. (`app/plugins/commands_modular/barcello.py:1740`)
- **WARNING localized_param_description** — `barcello`: Parameter 'user2' description looks non-English. (`app/plugins/commands_modular/barcello.py:1741`)
- **WARNING missing_param_description** — `aura.ieri`: Parameter 'utente' is missing a description. (`app/plugins/commands_modular/aura.py:457`)
- **WARNING missing_param_description** — `aura.oggi`: Parameter 'utente' is missing a description. (`app/plugins/commands_modular/aura.py:452`)
- **WARNING missing_param_description** — `inactivity.dms.template_reminder_set`: Parameter 'text' is missing a description. (`app/plugins/commands_modular/inattivi.py:335`)
- **WARNING missing_param_description** — `mod.channel.template_set`: Parameter 'text' is missing a description. (`app/plugins/commands_modular/moderazione_utenti.py:182`)
- **WARNING missing_param_description** — `resocontocanale.aura.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/resoconto.py:670`)
- **WARNING missing_param_description** — `resocontocanale.aura.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/resoconto.py:670`)
- **WARNING missing_param_description** — `resocontocanale.aura.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/resoconto.py:658`)
- **WARNING missing_param_description** — `resocontocanale.aura.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/resoconto.py:658`)
- **WARNING missing_param_description** — `resocontocanale.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/resoconto.py:662`)
- **WARNING missing_param_description** — `resocontocanale.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/resoconto.py:662`)
- **WARNING missing_param_description** — `resocontocanale.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/resoconto.py:642`)
- **WARNING missing_param_description** — `resocontocanale.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/resoconto.py:642`)
- **WARNING missing_param_description** — `resocontoserver.aura.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/resoconto.py:942`)
- **WARNING missing_param_description** — `resocontoserver.aura.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/resoconto.py:942`)
- **WARNING missing_param_description** — `resocontoserver.aura.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/resoconto.py:930`)
- **WARNING missing_param_description** — `resocontoserver.aura.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/resoconto.py:930`)
- **WARNING missing_param_description** — `resocontoserver.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/resoconto.py:934`)
- **WARNING missing_param_description** — `resocontoserver.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/resoconto.py:934`)
- **WARNING missing_param_description** — `resocontoserver.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/resoconto.py:914`)
- **WARNING missing_param_description** — `resocontoserver.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/resoconto.py:914`)
- **WARNING required_param** — `admin.ai.fallback_set`: Parameter 'model' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/admin.py:601`)
- **WARNING required_param** — `admin.ai.model_set`: Parameter 'model' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/admin.py:558`)
- **WARNING required_param** — `admin.barcello.mood_set`: Parameter 'value' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/barcello.py:213`)
- **WARNING required_param** — `admin.footer.template_service_set`: Parameter 'phrase' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/admin.py:796`)
- **WARNING required_param** — `campagne.cap.config_set`: Parameter 'daily_limit' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/messaggi.py:588`)
- **WARNING required_param** — `campagne.prompt.schedule_show`: Parameter 'id_or_name' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:731`)
- **WARNING required_param** — `campagne.quiet.config_set`: Parameter 'start' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/messaggi.py:541`)
- **WARNING required_param** — `campagne.quiet.config_set`: Parameter 'end' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/messaggi.py:541`)
- **WARNING required_param** — `frasi.template_global_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:529`)
- **WARNING required_param** — `frasi.template_milestone_set`: Parameter 'threshold' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:486`)
- **WARNING required_param** — `frasi.template_milestone_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:486`)
- **WARNING required_param** — `frasi.template_user_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:574`)
- **WARNING required_param** — `inactivity.dms.cooldown_set`: Parameter 'days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:364`)
- **WARNING required_param** — `inactivity.dms.invite_set`: Parameter 'url' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:389`)
- **WARNING required_param** — `inactivity.dms.template_reminder_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:335`)
- **WARNING required_param** — `inactivity.grace.config_set`: Parameter 'days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:265`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'inactive_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:419`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'window_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:420`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'min_messages' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:421`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'mode' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:422`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'inactive_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:463`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'window_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:464`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'min_messages' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:465`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'mode' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:466`)
- **WARNING required_param** — `inactivity.tempban.config_set`: Parameter 'days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:312`)
- **WARNING required_param** — `insights.template_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:1004`)
- **WARNING required_param** — `mod.channel.template_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/moderazione_utenti.py:182`)
- **WARNING required_param** — `mod.channel.user_card_set`: Parameter 'enabled' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/moderazione_utenti.py:228`)
- **WARNING required_param** — `qna.bonus_set`: Parameter 'amount' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:941`)
- **WARNING required_param** — `qna.limits_set`: Parameter 'tier' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:910`)
- **WARNING required_param** — `qna.limits_set`: Parameter 'limit' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:910`)

## Localized exceptions

The following commands remain intentionally localized and are excluded from the English-only rule for now:
- `attivita.ieri`
- `attivita.oggi`
- `attivita.range`
- `attivita.ultimi`
- `aura.ieri`
- `aura.oggi`
- `aura.range`
- `aura.ultimi`
- `domanda`
- `frasi.entry_add`
- `frasi.entry_edit`
- `frasi.entry_list`
- `frasi.entry_remove`
- `frasi.entry_show`
- `frasi.off`
- `frasi.on`
- `frasi.status`
- `frasi.template_global_reset`
- `frasi.template_global_set`
- `frasi.template_global_show`
- `frasi.template_milestone_reset`
- `frasi.template_milestone_set`
- `frasi.template_milestone_show`
- `frasi.template_user_reset`
- `frasi.template_user_set`
- `frasi.template_user_show`
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
- `riassunto.ieri`
- `riassunto.oggi`
- `riassunto.range`
- `riassunto.ultimi`

## Usage

- Run `python -m scripts.validate_commands` for a console report.
- Run `python -m scripts.validate_commands --write-report` to refresh this markdown file.
- Run `pytest tests/test_command_standard_validator.py` to fail CI on validator errors.
